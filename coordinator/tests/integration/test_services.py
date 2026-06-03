"""Integration tests for service CRUD."""
import pytest
from httpx import AsyncClient


async def _auth_headers(client: AsyncClient, email: str = "svc@test.com") -> dict:
    await client.post("/api/v1/auth/register", json={"email": email, "password": "pw"})
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "pw"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_and_get_service(client: AsyncClient):
    headers = await _auth_headers(client, "svc1@test.com")
    payload = {
        "name": "My API",
        "url": "https://httpbin.org/get",
        "interval_secs": 30,
        "expected_status": 200,
    }
    resp = await client.post("/api/v1/services", json=payload, headers=headers)
    assert resp.status_code == 201
    svc = resp.json()
    assert svc["name"] == "My API"
    assert svc["is_active"] is True
    assert svc["status"] is not None

    # Get
    resp2 = await client.get(f"/api/v1/services/{svc['id']}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == svc["id"]


@pytest.mark.asyncio
async def test_list_services_paginated(client: AsyncClient):
    headers = await _auth_headers(client, "svc2@test.com")
    for i in range(5):
        await client.post("/api/v1/services", json={
            "name": f"Service {i}", "url": f"https://example{i}.com",
        }, headers=headers)

    resp = await client.get("/api/v1/services?page=1&page_size=3", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["total"] >= 5
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_service_isolation_between_users(client: AsyncClient):
    h1 = await _auth_headers(client, "user1@test.com")
    h2 = await _auth_headers(client, "user2@test.com")

    resp = await client.post("/api/v1/services", json={"name": "User1 API", "url": "https://user1.example.com"}, headers=h1)
    svc_id = resp.json()["id"]

    # User2 cannot access User1's service
    resp2 = await client.get(f"/api/v1/services/{svc_id}", headers=h2)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_update_service(client: AsyncClient):
    headers = await _auth_headers(client, "upd@test.com")
    resp = await client.post("/api/v1/services", json={"name": "Before", "url": "https://before.com"}, headers=headers)
    svc_id = resp.json()["id"]

    resp2 = await client.patch(f"/api/v1/services/{svc_id}", json={"name": "After", "interval_secs": 120}, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["name"] == "After"
    assert resp2.json()["interval_secs"] == 120


@pytest.mark.asyncio
async def test_delete_service(client: AsyncClient):
    headers = await _auth_headers(client, "del@test.com")
    resp = await client.post("/api/v1/services", json={"name": "ToDelete", "url": "https://delete.com"}, headers=headers)
    svc_id = resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/services/{svc_id}", headers=headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/services/{svc_id}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_interval_rejected(client: AsyncClient):
    headers = await _auth_headers(client, "inv@test.com")
    resp = await client.post("/api/v1/services", json={
        "name": "Bad", "url": "https://bad.com", "interval_secs": 5
    }, headers=headers)
    assert resp.status_code == 422  # Pydantic validation error
