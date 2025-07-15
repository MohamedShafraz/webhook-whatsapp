# main.py
import os
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response, status, Query as FastapiQuery
from dotenv import load_dotenv
from openai import OpenAI
import strawberry
from strawberry.fastapi import GraphQLRouter

# --- Load .env ---
load_dotenv()

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Credentials ---
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- OpenAI Client ---
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Creating HTTPX client...")
    app.state.httpx_client = httpx.AsyncClient()
    yield
    logger.info("Closing HTTPX client...")
    await app.state.httpx_client.aclose()

# --- FastAPI App Initialization ---
app = FastAPI(lifespan=lifespan)

# --- GraphQL ---
@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello! Your GraphQL server is running with Strawberry on FastAPI!"

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

# --- Helper Functions ---
async def get_openai_response(message: str) -> str:
    if not openai_client.api_key:
        logger.error("OpenAI API key is not set.")
        return "Sorry, I can't connect to my brain right now."

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
        return "I encountered an error. Please try again later."

async def send_whatsapp_message(to_number: str, message: str, request):
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
        httpx_client = request.app.state.httpx_client
        response = await httpx_client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"WhatsApp API response: {response.json()}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error sending WhatsApp message: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

# --- Routes ---
@app.get("/")
def read_root():
    return {"message": "✅ WhatsApp FastAPI Webhook is alive!"}

@app.get("/webhook")
def verify_webhook(
    mode: Optional[str] = FastapiQuery(None, alias="hub.mode"),
    token: Optional[str] = FastapiQuery(None, alias="hub.verify_token"),
    challenge: Optional[str] = FastapiQuery(None, alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("WEBHOOK_VERIFIED")
        return Response(content=challenge, status_code=200)
    return Response(status_code=status.HTTP_403_FORBIDDEN)

@app.post("/webhook")
async def handle_webhook(request: Request):
    body = await request.json()
    logger.info(f"Incoming webhook message:\n{json.dumps(body, indent=2)}")

    if body.get("object") != "whatsapp_business_account":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        logger.error("Failed to extract message value")
        return Response(status_code=200)

    if "statuses" in value:
        status_data = value["statuses"][0]
        logger.info(f"Status update: {status_data['id']} - {status_data['status']}")
        return Response(status_code=200)

    if "messages" in value:
        message_entry = value["messages"][0]
        if message_entry.get("type") == "text":
            from_number = message_entry["from"]
            msg_body = message_entry["text"]["body"]
            logger.info(f"Message from {from_number}: {msg_body}")

            ai_response = await get_openai_response(msg_body)
            await send_whatsapp_message(from_number, ai_response, request)

    return Response(status_code=200)
