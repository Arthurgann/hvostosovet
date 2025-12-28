from fastapi import APIRouter, Depends

from app.core.auth import require_bot_token

router = APIRouter()


@router.get("/me", dependencies=[Depends(require_bot_token)])
def me() -> dict:
    return {
        "plan": "free",
        "limits": {"remaining_in_window": 0, "cooldown_sec": 0, "reset_at": None},
        "pets": [],
        "consents": {"terms_accepted": False, "data_policy_accepted": False},
        "research": {"available": False, "used_this_period": 0, "limit": 0, "reset_at": None},
    }
