from collections import defaultdict

_user_profiles = defaultdict(dict)

PRO_STEP_NONE = "pro_none"
PRO_STEP_SPECIES = "pro_species"
PRO_STEP_NAME = "pro_name"
PRO_STEP_AGE = "pro_age"
PRO_STEP_SEX = "pro_sex"
PRO_STEP_BREED = "pro_breed"
PRO_STEP_WEIGHT_MODE = "pro_weight_mode"
PRO_STEP_WEIGHT_KG = "pro_weight_kg"
PRO_STEP_WEIGHT_BCS = "pro_weight_bcs"
PRO_STEP_WEIGHT_AFTER_BCS_ASK_KG = "pro_weight_after_bcs_ask_kg"
PRO_STEP_DONE = "pro_done"
PRO_STEP_POST_MENU = "pro_post_menu"
PRO_STEP_HEALTH_PICK = "pro_health_pick"
PRO_STEP_HEALTH_NOTE = "pro_health_note"
PRO_STEP_VACCINES = "pro_vaccines"
PRO_STEP_PARASITES = "pro_parasites"
PRO_STEP_OWNER_NOTE = "pro_owner_note"


def get_profile(user_id: int) -> dict | None:
    return _user_profiles.get(user_id)


def get_pro_profile(user_id: int) -> dict:
    p = _user_profiles.get(user_id) or {}
    return p.get("profile") or {}


def set_pro_profile(user_id: int, profile: dict) -> None:
    p = _user_profiles[user_id]
    p["profile"] = profile
    p["pet_profile"] = profile


def get_pet_profile(user_id: int) -> dict | None:
    p = _user_profiles.get(user_id) or {}
    return p.get("pet_profile")


def set_pet_profile(user_id: int, profile: dict) -> None:
    p = _user_profiles[user_id]
    p["pet_profile"] = profile


def get_pet_profile_loaded(user_id: int) -> bool:
    p = _user_profiles.get(user_id) or {}
    return bool(p.get("pet_profile_loaded"))


def set_pet_profile_loaded(user_id: int, loaded: bool) -> None:
    p = _user_profiles[user_id]
    p["pet_profile_loaded"] = loaded


def set_skip_basic_info(user_id: int, value: bool) -> None:
    p = _user_profiles[user_id]
    p["skip_basic_info"] = bool(value)


def get_skip_basic_info(user_id: int) -> bool:
    p = _user_profiles.get(user_id) or {}
    return bool(p.get("skip_basic_info"))


def set_profile_field(user_id: int, path: str, value) -> None:
    p = _user_profiles[user_id]
    profile = p.get("profile") or p.get("pet_profile") or {}
    cursor = profile
    parts = path.split(".")
    for part in parts[:-1]:
        node = cursor.get(part)
        if not isinstance(node, dict):
            node = {}
            cursor[part] = node
        cursor = node
    cursor[parts[-1]] = value
    p["profile"] = profile
    p["pet_profile"] = profile


def get_pro_step(user_id: int) -> str:
    p = _user_profiles.get(user_id) or {}
    return p.get("pro_step") or PRO_STEP_NONE


def set_pro_step(user_id: int, step: str, awaiting_button: bool) -> None:
    p = _user_profiles[user_id]
    p["pro_step"] = step
    p["awaiting_button"] = awaiting_button


def is_awaiting_button(user_id: int) -> bool:
    p = _user_profiles.get(user_id)
    if not p:
        return False
    return bool(p.get("awaiting_button"))


def get_pro_temp(user_id: int) -> dict:
    p = _user_profiles.get(user_id) or {}
    return p.get("pro_temp") or {}


def set_pro_temp_field(user_id: int, key: str, value) -> None:
    p = _user_profiles[user_id]
    temp = p.get("pro_temp") or {}
    temp[key] = value
    p["pro_temp"] = temp


def reset_pro_profile(user_id: int) -> None:
    p = _user_profiles.get(user_id)
    if not p:
        return
    p.pop("profile", None)
    p.pop("pro_step", None)
    p.pop("awaiting_button", None)
    p.pop("pro_temp", None)
    p.pop("pro_profile_created_shown", None)
    p.pop("last_limits", None)


def add_health_tag(user_id: int, tag: str) -> None:
    p = _user_profiles[user_id]
    profile = p.get("profile") or {}
    health = profile.get("health") or {}
    tags = health.get("tags") or []
    if tag not in tags:
        tags.append(tag)
    health["tags"] = tags
    health["notes_by_tag"] = health.get("notes_by_tag") or {}
    profile["health"] = health
    p["profile"] = profile
    p["pet_profile"] = profile


def set_health_note(user_id: int, tag: str, note: str) -> None:
    p = _user_profiles[user_id]
    profile = p.get("profile") or {}
    health = profile.get("health") or {}
    notes_by_tag = health.get("notes_by_tag") or {}
    notes_by_tag[tag] = note
    health["notes_by_tag"] = notes_by_tag
    health["tags"] = health.get("tags") or []
    profile["health"] = health
    p["profile"] = profile
    p["pet_profile"] = profile


def set_health_category(user_id: int, category: str | None) -> None:
    set_pro_temp_field(user_id, "health_category", category)


def get_health_category(user_id: int) -> str | None:
    return get_pro_temp(user_id).get("health_category")


def set_owner_note(user_id: int, note: str) -> None:
    set_profile_field(user_id, "owner_note", note)


def get_last_limits(user_id: int) -> dict | None:
    p = _user_profiles.get(user_id)
    if not p:
        return None
    return p.get("last_limits")


def set_last_limits(user_id: int, limits: dict | None) -> None:
    p = _user_profiles[user_id]
    p["last_limits"] = limits


def get_profile_created_shown(user_id: int) -> bool:
    p = _user_profiles.get(user_id)
    if not p:
        return False
    return bool(p.get("pro_profile_created_shown"))


def set_profile_created_shown(user_id: int, shown: bool) -> None:
    p = _user_profiles[user_id]
    p["pro_profile_created_shown"] = shown

def start_profile(
    user_id: int,
    pet_type: str = "unknown",
    context: str = "unknown",
    current_mode: str | None = None,
) -> dict:
    existing = _user_profiles.get(user_id) or {}
    pending_question = existing.get("pending_question")
    preserved = {
        "profile": existing.get("profile"),
        "pet_profile": existing.get("pet_profile"),
        "pet_profile_loaded": existing.get("pet_profile_loaded"),
        "last_limits": existing.get("last_limits"),
        "pro_profile_created_shown": existing.get("pro_profile_created_shown"),
        "skip_basic_info": existing.get("skip_basic_info"),
    }
    _user_profiles[user_id] = {"type": pet_type, "context": context, "step": "basic_info"}
    if pending_question:
        _user_profiles[user_id]["pending_question"] = pending_question
    if current_mode:
        _user_profiles[user_id]["current_mode"] = current_mode
    for key, value in preserved.items():
        if value is not None:
            _user_profiles[user_id][key] = value
    return _user_profiles[user_id]

def set_basic_info(user_id: int, text: str) -> None:
    p = _user_profiles[user_id]
    p["basic_info"] = text.strip()
    p["step"] = "question"

def set_question(user_id: int, text: str) -> None:
    p = _user_profiles[user_id]
    p["question"] = text.strip()
    p["step"] = "done"

def set_waiting_question(user_id: int) -> None:
    p = _user_profiles.get(user_id)
    if not p:
        return
    p["step"] = "question"

def set_pending_question(user_id: int, text: str) -> None:
    p = _user_profiles[user_id]
    p["pending_question"] = text.strip()

def get_pending_question(user_id: int) -> str | None:
    p = _user_profiles.get(user_id)
    if not p:
        return None
    return p.get("pending_question")

def pop_pending_question(user_id: int) -> str | None:
    p = _user_profiles.get(user_id)
    if not p:
        return None
    return p.pop("pending_question", None)

def clear_profile(user_id: int) -> None:
    _user_profiles.pop(user_id, None)
