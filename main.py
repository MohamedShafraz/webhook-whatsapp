from fastapi import FastAPI
from dotenv import load_dotenv
from utils.logging_config import configure_logging
from schema.graphql_schema import schema
from strawberry.fastapi import GraphQLRouter
from routes.webhook import router as webhook_router

load_dotenv()
configure_logging()

app = FastAPI()

# Register GraphQL and webhook routes
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")
app.include_router(webhook_router)

@app.get("/")
def read_root():
    return {"message": "✅ WhatsApp FastAPI Webhook is alive!"}
