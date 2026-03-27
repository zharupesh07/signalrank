async def test_register_creates_user(client):
    r = await client.post("/api/auth/register", json={"email": "test@example.com", "password": "secret123"})
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "test@example.com"
    assert "id" in data


async def test_register_duplicate_email_returns_409(client):
    await client.post("/api/auth/register", json={"email": "dup@example.com", "password": "password123"})
    r = await client.post("/api/auth/register", json={"email": "dup@example.com", "password": "password123"})
    assert r.status_code == 409


async def test_login_returns_token(client):
    await client.post("/api/auth/register", json={"email": "login@example.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "login@example.com", "password": "password123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_login_wrong_password_returns_401(client):
    await client.post("/api/auth/register", json={"email": "wrong@example.com", "password": "correct123"})
    r = await client.post("/api/auth/login", json={"email": "wrong@example.com", "password": "wrong"})
    assert r.status_code == 401


async def test_protected_route_requires_token(client):
    r = await client.get("/api/profile")
    assert r.status_code == 401


async def test_protected_route_with_valid_token(client):
    await client.post("/api/auth/register", json={"email": "auth@example.com", "password": "password123"})
    login = await client.post("/api/auth/login", json={"email": "auth@example.com", "password": "password123"})
    token = login.json()["access_token"]
    r = await client.get("/api/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_register_short_password_returns_422(client):
    r = await client.post("/api/auth/register", json={"email": "short@example.com", "password": "pass"})
    assert r.status_code == 422
