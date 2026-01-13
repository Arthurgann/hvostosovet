import json
from datetime import datetime

from psycopg.types.json import Json


def deep_merge_dict(base: dict | None, patch: dict | None) -> dict:
    """
    Deep-merge словарей: patch имеет приоритет, base сохраняется.
    Для dict -> рекурсивно.
    Для list/str/int/etc -> patch полностью заменяет значение.
    """
    base = base or {}
    patch = patch or {}
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _parse_birth_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def get_active_pet(cur, user_id):
    cur.execute(
        "select id, user_id, type, name, sex, birth_date, age_text, breed, profile, "
        "created_at, archived_at, updated_at "
        "from pets "
        "where user_id = %s and archived_at is null "
        "order by created_at desc "
        "limit 1",
        (user_id,),
    )
    return cur.fetchone()


def build_pet_dict_from_row(active_pet_row) -> dict:
    """
    Собирает полный pet_dict из колонок pets + jsonb profile.
    Колонки считаем источником правды для базовых полей.
    """
    if not active_pet_row:
        return {}

    # active_pet_row:
    # 0 id, 1 user_id, 2 type, 3 name, 4 sex, 5 birth_date, 6 age_text, 7 breed, 8 profile, ...
    pet_type = active_pet_row[2]
    name = active_pet_row[3]
    sex = active_pet_row[4]
    birth_date = active_pet_row[5]
    age_text = active_pet_row[6]
    breed = active_pet_row[7]
    profile = active_pet_row[8] or {}

    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}
    if not isinstance(profile, dict):
        profile = {}

    base = {
        "type": pet_type,
        "name": name,
        "sex": sex,
        "birth_date": birth_date.isoformat() if birth_date else None,
        "age_text": age_text,
        "breed": breed,
    }

    # profile может содержать те же ключи - но базовые поля из колонок важнее
    merged = dict(profile)
    merged.update({k: v for k, v in base.items() if v is not None})

    # sex может быть "unknown" - это тоже валидно
    if "sex" not in merged and sex:
        merged["sex"] = sex

    return merged


_PET_SERVICE_KEYS = {"step", "context", "current_mode", "question"}


def normalize_pet_dict(pet_dict: dict | None) -> dict | None:
    if not isinstance(pet_dict, dict):
        return None
    return {k: v for k, v in pet_dict.items() if k not in _PET_SERVICE_KEYS}


_HEALTH_ALLOWED_TAGS = {"allergy", "gi", "skin_coat", "mobility", "other"}


def _as_clean_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        return t if t else None
    t = str(v).strip()
    return t if t else None


def normalize_health_block(pet_dict: dict | None) -> dict | None:
    """
    Канон хранения health в pets.profile:
      health: { notes_by_tag: {allergy, gi, skin_coat, mobility, other} }
    Правила:
    - health.tags НЕ сохраняем (удаляем).
    - health.notes_by_tag должен быть dict[str, str] только по разрешённым ключам.
    - если пришли неизвестные ключи - аккуратно добавляем их в other (как "key: value"),
      чтобы не терять информацию.
    """
    if not isinstance(pet_dict, dict):
        return pet_dict

    health = pet_dict.get("health")
    if health is None:
        return pet_dict

    if isinstance(health, str):
        t = health.strip()
        if t:
            pet_dict["health"] = {"notes_by_tag": {"other": t}}
        else:
            pet_dict.pop("health", None)
        return pet_dict

    if not isinstance(health, dict):
        pet_dict.pop("health", None)
        return pet_dict

    notes = health.get("notes_by_tag")
    if notes is None:
        notes = {}
    if not isinstance(notes, dict):
        notes = {}

    out_notes: dict[str, str] = {}

    for k in _HEALTH_ALLOWED_TAGS:
        v = _as_clean_text(notes.get(k))
        if v:
            out_notes[k] = v

    extra_lines = []
    for k, v in notes.items():
        if k in _HEALTH_ALLOWED_TAGS:
            continue
        vv = _as_clean_text(v)
        if vv:
            extra_lines.append(f"{k}: {vv}")

    if extra_lines:
        prev_other = out_notes.get("other")
        extra_text = "\n".join(extra_lines)
        out_notes["other"] = f"{prev_other}\n{extra_text}".strip() if prev_other else extra_text

    if out_notes:
        pet_dict["health"] = {"notes_by_tag": out_notes}
    else:
        pet_dict.pop("health", None)

    return pet_dict


def is_minimal_pet_profile(pet_dict: dict | None) -> bool:
    if not isinstance(pet_dict, dict) or not pet_dict:
        return True
    keys_without_type = [k for k in pet_dict.keys() if k != "type"]
    return not keys_without_type


def upsert_active_pet(cur, user_id, pet_dict):
    pet_dict = pet_dict or {}
    active_pet = get_active_pet(cur, user_id)
    if active_pet:
        existing_full = build_pet_dict_from_row(active_pet)
        pet_dict = deep_merge_dict(existing_full, pet_dict)

    pet_type = pet_dict.get("type")
    if not pet_type:
        raise ValueError("missing pet.type")
    name = pet_dict.get("name")
    sex = pet_dict.get("sex") or "unknown"
    birth_date = _parse_birth_date(pet_dict.get("birth_date"))
    age_text = pet_dict.get("age_text")
    breed = pet_dict.get("breed")
    profile = Json(pet_dict)

    if active_pet:
        pet_id = active_pet[0]
        cur.execute(
            "update pets "
            "set type = %s, name = %s, sex = %s, birth_date = %s, age_text = %s, "
            "breed = %s, profile = %s, updated_at = now() "
            "where id = %s",
            (
                pet_type,
                name,
                sex,
                birth_date,
                age_text,
                breed,
                profile,
                pet_id,
            ),
        )
        return pet_id

    cur.execute(
        "insert into pets "
        "(user_id, type, name, sex, birth_date, age_text, breed, profile, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
        "returning id",
        (
            user_id,
            pet_type,
            name,
            sex,
            birth_date,
            age_text,
            breed,
            profile,
        ),
    )
    row = cur.fetchone()
    return row[0] if row else None


def resolve_effective_pet_profile(cur, user_plan, user_id, pet_dict):
    effective_pet_profile = None
    pet_profile_source = "none"
    pet_profile_pet_id = None
    if not is_minimal_pet_profile(pet_dict):
        effective_pet_profile = pet_dict
        pet_profile_source = "request"
    else:
        if user_plan == "pro" and user_id:
            active_pet = get_active_pet(cur, user_id)
            if active_pet:
                effective_pet_profile = build_pet_dict_from_row(active_pet)
                pet_profile_source = "db"
                pet_profile_pet_id = (
                    str(active_pet[0]) if active_pet[0] is not None else None
                )
        elif effective_pet_profile is None and user_plan == "pro":
            pet_profile_source = "none"
        if effective_pet_profile is None and user_plan != "pro":
            effective_pet_profile = pet_dict or None
            pet_profile_source = "request" if pet_dict else "none"
    if isinstance(effective_pet_profile, str):
        try:
            effective_pet_profile = json.loads(effective_pet_profile)
        except json.JSONDecodeError:
            effective_pet_profile = None
            pet_profile_source = "none"
    return effective_pet_profile, pet_profile_source, pet_profile_pet_id
