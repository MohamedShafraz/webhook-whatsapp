import json
import os
import logging
from fastapi import APIRouter, Request, Response, status, Query as FastapiQuery
from local_agents.openai_agent import get_openai_response
from utils.whatsapp_utils import send_whatsapp_message

router = APIRouter()
logger = logging.getLogger(__name__)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

@router.get("/webhook")
def verify_webhook(
    mode: str = FastapiQuery(None, alias="hub.mode"),
    token: str = FastapiQuery(None, alias="hub.verify_token"),
    challenge: str = FastapiQuery(None, alias="hub.challenge"),
):
    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("WEBHOOK_VERIFIED")
            return Response(content=challenge, status_code=200)
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return Response(status_code=status.HTTP_400_BAD_REQUEST)

@router.post("/webhook")
async def handle_webhook(request: Request):
    body = await request.json()
    logger.info(f"Incoming webhook message: {json.dumps(body, indent=2)}")

    if body.get("object") != "whatsapp_business_account":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        return Response(status_code=200)

    if "statuses" in value:
        status_data = value["statuses"][0]
        logger.info(f"Status update for {status_data['id']}: {status_data['status']}")
        return Response(status_code=200)

    if "messages" in value:
        message_entry = value["messages"][0]
        if message_entry.get("type") == "text":
            from_number = message_entry["from"]
            msg_body = message_entry["text"]["body"]
            ai_response = await get_openai_response(msg_body)
            await send_whatsapp_message(from_number, ai_response)

    return Response(status_code=200)
