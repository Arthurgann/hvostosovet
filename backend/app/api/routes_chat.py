from fastapi import APIRouter, Depends

from app.core.auth import require_bot_token

router = APIRouter()


@router.post("/chat/ask", dependencies=[Depends(require_bot_token)])
def chat_ask() -> dict:
    return {
        "answer_text": "",
        "safety_level": "low",
        "recommended_actions": [],
        "should_go_to_vet": False,
        "followup_question": None,
        "session": {"session_id": None, "expires_at": None},
        "limits": {"remaining_in_window": 0, "cooldown_sec": 0},
        "upsell": {"show": False, "reason": None, "cta": None},
        "research": {"used_this_period": 0, "limit": 0, "reset_at": None},
    }
