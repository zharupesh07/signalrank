import os

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from openai import AsyncOpenAI

# ---------------------------------
# LOAD ENV
# ---------------------------------
load_dotenv()

# ---------------------------------
# CONFIG
# ---------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

FREE_MODEL = os.getenv("FREE_MODEL", "openrouter/free")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-latest")

# ---------------------------------
# APP
# ---------------------------------
app = FastAPI()

# ---------------------------------
# CLIENTS
# ---------------------------------
openrouter = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": os.getenv("APP_URL", "http://localhost"),
        "X-Title": os.getenv("APP_NAME", "llm-router"),
    },
)

claude = anthropic.AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY
)

# ---------------------------------
# ESCALATION LOGIC
# ---------------------------------
def requires_escalation(text: str):
    if not text:
        return True

    t = text.lower()

    failure_patterns = [
        "i cannot",
        "i'm not sure",
        "unable to",
        "as an ai"
    ]

    if any(p in t for p in failure_patterns):
        return True

    if len(text) < 20:
        return True

    return False


# ---------------------------------
# FREE MODEL CALL
# ---------------------------------
async def call_free(prompt):

    resp = await openrouter.chat.completions.create(
        model=FREE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    text = resp.choices[0].message.content
    used_model = resp.model

    return text, used_model


# ---------------------------------
# CLAUDE FALLBACK
# ---------------------------------
async def call_claude(prompt):

    resp = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    return resp.content[0].text


# ---------------------------------
# API ENDPOINT
# ---------------------------------
@app.post("/generate")
async def generate(prompt: str):

    cheap_response, model_used = await call_free(prompt)

    if not requires_escalation(cheap_response):
        return {
            "provider": "openrouter",
            "model": model_used,
            "response": cheap_response,
        }

    claude_response = await call_claude(prompt)

    return {
        "provider": "anthropic",
        "model": CLAUDE_MODEL,
        "response": claude_response,
    }