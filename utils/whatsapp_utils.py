import os
import httpx
import logging

logger = logging.getLogger(__name__)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

async def send_whatsapp_message(to_number: str, message: str):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"WhatsApp API response: {response.json()}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.text}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
