import asyncio
import json
import os
import re
from collections import defaultdict

import aiohttp
from dotenv import load_dotenv
from openai import AsyncOpenAI

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = "https://openrouter.ai/api/v1"
MODELS_ENDPOINT = f"{BASE_URL}/models"

MAX_CONCURRENCY = 2
CALL_COOLDOWN = 3.0

# --------------------------------------------------
# REALISTIC TESTS (MATCH main.py)
# --------------------------------------------------
TESTS = {
    "basic": {
        "prompt": "Reply with exactly one word: hello",
        "max_tokens": 5,
    },
    "long_context": {
        "prompt": (
            "Extract concepts from text.\n"
            "One per line.\n\n"
            + ("machine learning models and evaluation metrics. " * 400)
        ),
        "max_tokens": 200,
    },
    "structured_card": {
        "prompt": """
Create ONE flashcard.

Front:
What is logistic regression

Back:
Explain briefly.
End with:
ELI5:
""",
        "max_tokens": 200,
    },
}

# --------------------------------------------------
# CLIENT
# --------------------------------------------------
client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=BASE_URL,
    default_headers={
        "HTTP-Referer": "http://localhost",
        "X-Title": "AAIC-Anki-Model-Probe",
    },
)


# --------------------------------------------------
# PROVIDER RESOLUTION
# --------------------------------------------------
def resolve_provider(model):
    if model.get("provider"):
        return model["provider"]
    if model.get("owned_by"):
        return model["owned_by"]

    mid = model["id"]
    return mid.split("/")[0] if "/" in mid else "unknown"


# --------------------------------------------------
# FETCH FREE MODELS
# --------------------------------------------------
async def fetch_free_models():
    async with aiohttp.ClientSession() as session:
        async with session.get(MODELS_ENDPOINT) as resp:
            data = await resp.json()

    models = []
    for m in data.get("data", []):
        pricing = m.get("pricing", {})
        if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
            models.append(
                {
                    "id": m["id"],
                    "provider": resolve_provider(m),
                }
            )

    return models


# --------------------------------------------------
# TEST ONE MODEL
# --------------------------------------------------
async def test_model(model, semaphore):
    results = {}
    errors = {}

    async with semaphore:
        for name, cfg in TESTS.items():
            try:
                resp = await client.chat.completions.create(
                    model=model["id"],
                    messages=[{"role": "user", "content": cfg["prompt"]}],
                    temperature=0,
                    max_tokens=cfg["max_tokens"],
                )
                text = resp.choices[0].message.content.strip()

                # basic sanity checks
                if name == "structured_card":
                    if "Front:" not in text or "Back:" not in text:
                        raise ValueError("Missing Front/Back structure")

                results[name] = True
                await asyncio.sleep(CALL_COOLDOWN)

            except Exception as e:
                results[name] = False
                errors[name] = str(e)
                break

    return model, results, errors


# --------------------------------------------------
# MAIN
# --------------------------------------------------
async def main():
    models = await fetch_free_models()
    print(f"Found {len(models)} free models\n")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [test_model(m, semaphore) for m in models]

    provider_pass = defaultdict(list)
    detailed_log = []

    for coro in asyncio.as_completed(tasks):
        model, results, errors = await coro
        passed = all(results.values())

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {model['provider']} :: {model['id']} → {results}")

        if errors:
            for k, v in errors.items():
                print(f"    └─ {k} error: {v}")

        detailed_log.append(
            {
                "model": model["id"],
                "provider": model["provider"],
                "results": results,
                "errors": errors,
            }
        )

        if passed:
            provider_pass[model["provider"]].append(model["id"])

    # --------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------
    with open("telemetry/model_test_detailed.json", "w") as f:
        json.dump(detailed_log, f, indent=2)

    with open("telemetry/working_models.json", "w") as f:
        json.dump(provider_pass, f, indent=2)

    print("\n==============================")
    print("RECOMMENDED MODELS (FOR main.py)")
    print("==============================")
    for provider, ids in provider_pass.items():
        print(f"\nProvider: {provider}")
        for m in ids:
            print(f"  - {m}")

    print("\nSaved:")
    print("  telemetry/working_models.json")
    print("  telemetry/model_test_detailed.json")


if __name__ == "__main__":
    asyncio.run(main())
