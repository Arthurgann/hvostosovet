from collections import defaultdict

_user_profiles = defaultdict(dict)

def get_profile(user_id: int) -> dict | None:
    return _user_profiles.get(user_id)

def start_profile(user_id: int, pet_type: str, context: str) -> dict:
    _user_profiles[user_id] = {"type": pet_type, "context": context, "step": "basic_info"}
    return _user_profiles[user_id]

def set_basic_info(user_id: int, text: str) -> None:
    p = _user_profiles[user_id]
    p["basic_info"] = text.strip()
    p["step"] = "question"

def set_question(user_id: int, text: str) -> None:
    p = _user_profiles[user_id]
    p["question"] = text.strip()
    p["step"] = "done"

def clear_profile(user_id: int) -> None:
    _user_profiles.pop(user_id, None)