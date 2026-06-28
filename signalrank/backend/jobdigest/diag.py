import os, httpx
key = os.environ.get("ANTHROPIC_API_KEY", "")
print("key length:", len(key), "| starts:", key[:12], "| has newline:", "\n" in key)
r = httpx.post(
    "https://api.anthropic.com/v1/messages",
    headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    json={"model": "claude-haiku-4-5-20251001", "max_tokens": 50,
          "messages": [{"role": "user", "content": "Say hi in one word."}]},
    timeout=30,
)
print("STATUS:", r.status_code)
print(r.text)