from app.services.feedback_service import FeedbackService
from app.utils.whatsapp_utils import generate_payload
from scripts.crons import send_feedback_invites_cron as feedback_cron


def test_generate_payload_preserves_custom_option_ids():
    payload = generate_payload(
        wa_id="255700000000",
        response="How was your chat?",
        options=[
            {"id": "feedback:positive", "title": "Helpful"},
            {"id": "feedback:negative", "title": "Not helpful"},
        ],
    )

    buttons = payload["interactive"]["action"]["buttons"]
    assert buttons[0]["reply"]["id"] == "feedback:positive"
    assert buttons[0]["reply"]["title"] == "Helpful"
    assert buttons[1]["reply"]["id"] == "feedback:negative"


def test_feedback_service_extracts_interactive_reply():
    svc = FeedbackService()
    message_info = {
        "message": {
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "feedback:neutral",
                    "title": "Okay",
                },
            },
        }
    }

    reply = svc._extract_interactive_reply(message_info)

    assert reply == {"id": "feedback:neutral", "title": "Okay"}


def test_feedback_cron_runs_expiry_before_enqueue_and_send(monkeypatch):
    calls = []

    async def _expire(expiry_hours: int, limit: int = 500):
        calls.append(("expire", expiry_hours, limit))
        return 2

    async def _enqueue():
        calls.append(("enqueue",))
        return 5

    async def _send():
        calls.append(("send",))
        return (4, 1)

    monkeypatch.setattr(feedback_cron.db, "expire_stale_feedback_invites", _expire)
    monkeypatch.setattr(feedback_cron, "enqueue_feedback_invites", _enqueue)
    monkeypatch.setattr(feedback_cron, "send_pending_feedback_invites", _send)

    feedback_cron.asyncio.run(feedback_cron.main())

    assert calls[0][0] == "expire"
    assert calls[1] == ("enqueue",)
    assert calls[2] == ("send",)
