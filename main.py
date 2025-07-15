import os
import json
import logging
import httpx
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from openai import AsyncOpenAI
from fastapi import FastAPI, Request, Response, status, Query as FastapiQuery
from strawberry.fastapi import GraphQLRouter
import strawberry
from typing import Optional

# --- 0. Load Environment Variables and Initialize ---
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


# --- 1. Lifespan Manager for Client Initialization and Shutdown ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's lifespan.
    Initializes HTTPX and OpenAI clients on startup and closes them on shutdown.
    """
    # --- Startup ---
    logger.info("Application starting up...")
    # Initialize clients and store them in the app's state
    app.state.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    app.state.httpx_client = httpx.AsyncClient()
    logger.info("HTTPX and OpenAI clients initialized.")
    
    yield  # The application runs while the 'yield' is active
    
    # --- Shutdown ---
    logger.info("Application shutting down...")
    # Gracefully close the clients
    await app.state.openai_client.close()
    await app.state.httpx_client.aclose()
    logger.info("Clients gracefully closed.")


# --- 2. FastAPI App Initialization ---
# Attach the lifespan manager to the FastAPI app
app = FastAPI(lifespan=lifespan)


# --- 3. Define GraphQL Schema and Resolvers with Strawberry ---
@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello! Your GraphQL server is running with Strawberry on FastAPI!"

schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)


# --- 4. Helper Functions for AI and WhatsApp ---

async def get_openai_response(request: Request, message: str) -> str:
    """
    Sends a message to the OpenAI API and gets a response.
    Accesses the client from the application state.
    """
    openai_client = request.app.state.openai_client
    if not openai_client.api_key:
        logger.error("OpenAI API key is not set.")
        return "Sorry, I can't connect to my brain right now."

    try:
        logger.info(f"Sending to OpenAI: '{message}'")
        # Use 'await' with the AsyncOpenAI client
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


async def send_whatsapp_message(request: Request, to_number: str, message: str):
    """
    Sends a message back to the user via the WhatsApp Cloud API.
    Accesses the client from the application state.
    """
    httpx_client = request.app.state.httpx_client
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
        response = await httpx_client.post(url, headers=headers, json=payload)
        response.raise_for_status()  # Raise an exception for bad status codes
        logger.info(f"WhatsApp API response: {response.json()}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Error sending WhatsApp message: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


# --- 5. Define All FastAPI Routes and Middleware ---

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

    if body.get("object") != "whatsapp_business_account":
        logger.warning("Received a non-WhatsApp webhook")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        logger.error("Could not extract 'value' object from webhook payload")
        return Response(status_code=200) # Still return 200 to acknowledge receipt

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

            # Get AI response and send it back, passing the request object
            ai_response = await get_openai_response(request, msg_body)
            await send_whatsapp_message(request, from_number, ai_response)
        else:
            logger.info(f"Received a non-text message type: {message_entry.get('type')}. Ignoring.")

    return Response(status_code=200)


# Mount the GraphQL app at the /graphql endpoint
app.include_router(graphql_app, prefix="/graphql")