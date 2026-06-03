"""Integration tests for auth endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    # Register
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@example.com",
        "password": "password123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert "id" in data

    # Login
    resp = await client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    token_data = resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "pw"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_wrong_password_rejected(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={"email": "wp@example.com", "password": "correct"})
    resp = await client.post("/api/v1/auth/login", json={"email": "wp@example.com", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_token(client: AsyncClient):
    resp = await client.get("/api/v1/services")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tampered_token_rejected(client: AsyncClient):
    resp = await client.get(
        "/api/v1/services",
        headers={"Authorization": "Bearer tampered.token.value"},
    )
    assert resp.status_code == 401
