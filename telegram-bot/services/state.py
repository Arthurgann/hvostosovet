from collections import defaultdict

_user_profiles = defaultdict(dict)

def get_profile(user_id: int) -> dict | None:
    return _user_profiles.get(user_id)

def start_profile(
    user_id: int,
    pet_type: str = "unknown",
    context: str = "unknown",
    current_mode: str | None = None,
) -> dict:
    existing = _user_profiles.get(user_id) or {}
    pending_question = existing.get("pending_question")
    _user_profiles[user_id] = {"type": pet_type, "context": context, "step": "basic_info"}
    if pending_question:
        _user_profiles[user_id]["pending_question"] = pending_question
    if current_mode:
        _user_profiles[user_id]["current_mode"] = current_mode
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
