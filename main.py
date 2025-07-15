# main.py
import os
import json
import logging
import httpx
from openai import AsyncOpenAI # ## CHANGED: Import the async client
from dotenv import load_dotenv
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

# ## DELETED: Removed global client initializations. They will be handled in app lifespan.

# --- 1. FastAPI App Initialization ---
app = FastAPI()

# ## CHANGED: Lifespan events are now defined early and correctly.
# They will manage the lifecycle of our async clients.
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 App startup: Creating clients")
    # Store clients on the app state
    app.state.httpx_client = httpx.AsyncClient()
    app.state.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 App shutdown: Closing clients")
    await app.state.httpx_client.aclose()
    await app.state.openai_client.close()


# --- 2. Define GraphQL Schema and Resolvers with Strawberry ---
@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello! Your GraphQL server is running with Strawberry on FastAPI!"

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)


# --- 3. New Helper Functions for AI and WhatsApp ---

# ## CHANGED: Function now accepts the openai_client as an argument
async def get_openai_response(message: str, openai_client: AsyncOpenAI) -> str:
    """
    Sends a message to the OpenAI API and gets a response using the async client.
    """
    if not openai_client.api_key:
        logger.error("OpenAI API key is not set.")
        return "Sorry, I can't connect to my brain right now."

    try:
        logger.info(f"Sending to OpenAI: '{message}'")
        # ## CHANGED: Use 'await' with the async client
        completion = await openai_client.chat.completions.create(
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

# ## CHANGED: Function now accepts the httpx_client as an argument
async def send_whatsapp_message(to_number: str, message: str, httpx_client: httpx.AsyncClient):
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
        # ## CHANGED: Use the client passed as an argument
        response = await httpx_client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"WhatsApp API response: {response.json()}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Error sending WhatsApp message: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


# --- 4. Define All FastAPI Routes ---

# ## DELETED: Removed the duplicate 'app = FastAPI()' line.

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
    body = await request.json()
    logger.info(f"Incoming webhook message: {json.dumps(body, indent=2)}")

    # ## CHANGED: Get clients from the request/app state
    httpx_client = request.app.state.httpx_client
    openai_client = request.app.state.openai_client

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
        logger.info(f"Received status update for message {status_data['id']}: {status_data['status']}")
        return Response(status_code=200)

    if "messages" in value:
        message_entry = value["messages"][0]
        if message_entry.get("type") == "text":
            from_number = message_entry["from"]
            msg_body = message_entry["text"]["body"]
            logger.info(f"Message from {from_number}: {msg_body}")

            # Get AI response and send it back
            # ## CHANGED: Pass the clients to the helper functions
            ai_response = await get_openai_response(msg_body, openai_client)
            await send_whatsapp_message(from_number, ai_response, httpx_client)
        else:
            logger.info(f"Received a non-text message type: {message_entry.get('type')}. Ignoring.")

    return Response(status_code=200)

# Mount the GraphQL app
app.include_router(graphql_app, prefix="/graphql")

# --- 5. Run the Server ---
# Use the command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload