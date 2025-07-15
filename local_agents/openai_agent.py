import logging
import os
from openai import OpenAI

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def get_openai_response(message: str) -> str:
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
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
        return "I encountered an error. Please try again later."
