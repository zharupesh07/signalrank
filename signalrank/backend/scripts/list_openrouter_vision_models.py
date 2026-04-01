import argparse
import asyncio
import os

from llm.openrouter import OpenRouterClient, fetch_free_vision_models


async def main() -> int:
    parser = argparse.ArgumentParser(description="List current free OpenRouter image-capable models.")
    parser.add_argument("--probe", action="store_true", help="Send a tiny image+JSON prompt to confirm the model responds.")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required")

    models = await fetch_free_vision_models(api_key)
    print(f"Found {len(models)} free vision model(s):")
    for model in models:
        print(f" - {model}")

    if not args.probe:
        return 0

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
        b"\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    client = OpenRouterClient(api_key=api_key)
    try:
        for model in models:
            result = await client.llm_json_vision(
                [tiny_png],
                "Return exactly this JSON: {\"ok\": true}",
                vision_models=[model],
                max_tokens=32,
            )
            status = "ok" if result.get("ok") is True else f"failed ({result.get('_details', result)})"
            print(f"   {model}: {status}")
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
