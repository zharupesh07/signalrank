"""Test which OpenRouter models are currently responding.

Usage:
    cd signalrank/backend
    set -a && source .env && set +a
    uv run python -m tools.test_models
"""
import asyncio
import os
import time

import httpx

MODELS = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "arcee-ai/trinity-large-preview:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-3-4b-it:free",
    "google/gemma-3n-e4b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "openai/gpt-oss-20b:free",
    "minimax/minimax-m2.5:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "z-ai/glm-4.5-air:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
]

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
TEST_PROMPT = "Return JSON: {\"status\": \"ok\", \"model\": \"your_name\"}"


async def test_model(client: httpx.AsyncClient, model: str, api_key: str) -> dict:
    start = time.time()
    try:
        r = await client.post(
            BASE_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Return valid JSON only."},
                    {"role": "user", "content": TEST_PROMPT},
                ],
                "max_tokens": 64,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        elapsed = time.time() - start
        if r.status_code == 200:
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            actual_model = data.get("model", "?")
            return {"model": model, "status": "ok", "time": elapsed, "actual": actual_model, "response": content[:80]}
        else:
            return {"model": model, "status": f"HTTP {r.status_code}", "time": elapsed, "response": r.text[:80]}
    except httpx.TimeoutException:
        return {"model": model, "status": "timeout", "time": time.time() - start}
    except Exception as e:
        return {"model": model, "status": "error", "time": time.time() - start, "response": str(e)[:80]}


async def main():
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set")
        raise SystemExit(1)

    print(f"Testing {len(MODELS)} models...\n")
    print(f"{'Model':<50} {'Status':<12} {'Time':>6}  {'Details'}")
    print("-" * 120)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[test_model(client, m, api_key) for m in MODELS])

    working = []
    for r in results:
        status = r["status"]
        t = f"{r['time']:.1f}s"
        detail = r.get("actual", r.get("response", ""))[:50]
        icon = "+" if status == "ok" else "x"
        print(f"[{icon}] {r['model']:<48} {status:<12} {t:>6}  {detail}")
        if status == "ok":
            working.append(r)

    print(f"\n{'='*60}")
    print(f"Working: {len(working)}/{len(MODELS)}")
    if working:
        fastest = min(working, key=lambda x: x["time"])
        print(f"Fastest: {fastest['model']} ({fastest['time']:.1f}s)")
        print(f"\nRecommended FALLBACK_MODELS order:")
        for r in sorted(working, key=lambda x: x["time"]):
            print(f"  \"{r['model']}\",")


if __name__ == "__main__":
    asyncio.run(main())
