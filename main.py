# main.py
import os
import json
import logging
import httpx
from openai import OpenAI
from dotenv import load_dotenv
# 👇 1. IMPORT `asynccontextmanager`
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status, Query as FastapiQuery
from strawberry.fastapi import GraphQLRouter
import strawberry
from typing import Optional

# --- 0. Load Environment Variables and Initialize Clients ---
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load credentials from .env file
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


# --- 1. FastAPI App Initialization with Lifespan Management ---

# 👇 2. NEW LIFESPAN CONTEXT MANAGER
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code to run on startup
    logger.info("🚀 App startup: Creating httpx_client")
    # Store the client in the app's state
    app.state.httpx_client = httpx.AsyncClient()
    
    yield # The application runs here

    # Code to run on shutdown
    logger.info("🛑 App shutdown: Closing httpx_client")
    await app.state.httpx_client.aclose()


# 👇 3. UPDATED APP INITIALIZATION
app = FastAPI(lifespan=lifespan)


# --- 2. Define GraphQL Schema and Resolvers with Strawberry ---
@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello! Your GraphQL server is running with Strawberry on FastAPI!"

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)


# --- 3. New Helper Functions for AI and WhatsApp ---

async def get_openai_response(message: str) -> str:
    """
    Sends a message to the OpenAI API and gets a response.
    """
    if not openai_client.api_key:
        logger.error("OpenAI API key is not set.")
        return "Sorry, I can't connect to my brain right now."
    try:
        logger.info(f"Sending to OpenAI: '{message}'")
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message}
            ]
        )
        response_text = completion.choices[0].message.content
        logger.info(f"Received from OpenAI: '{response_text}'")
        return response_text
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
        return "I encountered an error. Please try again later."


async def send_whatsapp_message(client: httpx.AsyncClient, to_number: str, message: str):
    """
    Sends a message back to the user via the WhatsApp Cloud API.
    """
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
        logger.info(f"Sending message to {to_number}: '{message}'")
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"WhatsApp API response: {response.json()}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Error sending WhatsApp message: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during WhatsApp send: {e}")


# --- 4. Define All FastAPI Routes and Middleware ---

# 👇 4. REMOVED the deprecated @app.on_event handlers as they are replaced by lifespan

@app.get("/")
def read_root():
    return {"message": "✅ WhatsApp FastAPI Webhook is alive!"}


@app.get("/webhook")
def verify_webhook(
    mode: Optional[str] = FastapiQuery(None, alias="hub.mode"),
    token: Optional[str] = FastapiQuery(None, alias="hub.verify_token"),
    challenge: Optional[str] = FastapiQuery(None, alias="hub.challenge"),
):
    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("WEBHOOK_VERIFIED")
            return Response(content=challenge, status_code=200)
        else:
            logger.warning("Webhook verification failed. Tokens do not match.")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    logger.error("Webhook verification failed. Missing mode or token.")
    return Response(status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/webhook")
async def handle_webhook(request: Request):
    # The logic inside here remains the same, as it correctly uses request.app.state
    body = await request.json()
    logger.info(f"Incoming webhook message: {json.dumps(body, indent=2)}")

    if body.get("object") != "whatsapp_business_account":
        logger.warning("Received a non-WhatsApp webhook")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        logger.error("Could not extract 'value' object from webhook payload")
        return Response(status_code=200)

    if "statuses" in value:
        status_data = value["statuses"][0]
        status = status_data["status"]
        message_id = status_data["id"]
        logger.info(f"Received status update for message {message_id}: {status}")
        return Response(status_code=200)

    if "messages" in value:
        message_entry = value["messages"][0]
        if message_entry.get("type") == "text":
            from_number = message_entry["from"]
            msg_body = message_entry["text"]["body"]
            logger.info(f"Message from {from_number}: {msg_body}")

            ai_response = await get_openai_response(msg_body)
            
            client = request.app.state.httpx_client
            await send_whatsapp_message(client, from_number, ai_response)
        else:
            logger.info(f"Received a non-text message type: {message_entry.get('type')}. Ignoring.")

    return Response(status_code=200)


# Mount the GraphQL app at the /graphql endpoint
app.include_router(graphql_app, prefix="/graphql")


# --- 5. Run the Server (using uvicorn command line) ---
# Use the command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload