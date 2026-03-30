async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert isinstance(payload["workers"], dict)


async def test_ready(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}
