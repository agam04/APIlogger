"""Unit tests for the HTTP probe."""
import pytest
import respx
import httpx
from app.probe import probe


@pytest.mark.asyncio
@respx.mock
async def test_probe_up():
    respx.get("https://api.example.com/health").mock(return_value=httpx.Response(200))
    result = await probe("https://api.example.com/health", "GET", 5000, 200, {}, None)
    assert result.status == "up"
    assert result.status_code == 200
    assert result.response_ms is not None
    assert result.error_message is None


@pytest.mark.asyncio
@respx.mock
async def test_probe_wrong_status():
    respx.get("https://api.example.com/health").mock(return_value=httpx.Response(503))
    result = await probe("https://api.example.com/health", "GET", 5000, 200, {}, None)
    assert result.status == "down"
    assert result.status_code == 503
    assert "503" in result.error_message


@pytest.mark.asyncio
@respx.mock
async def test_probe_timeout():
    respx.get("https://slow.example.com/").mock(side_effect=httpx.ReadTimeout("timed out"))
    result = await probe("https://slow.example.com/", "GET", 100, 200, {}, None)
    assert result.status == "timeout"
    assert result.status_code is None


@pytest.mark.asyncio
@respx.mock
async def test_probe_connection_error():
    respx.get("https://dead.example.com/").mock(side_effect=httpx.ConnectError("refused"))
    result = await probe("https://dead.example.com/", "GET", 5000, 200, {}, None)
    # After MAX_PROBE_RETRIES connection errors, status should be 'error'
    assert result.status == "error"
    assert result.response_ms is None


@pytest.mark.asyncio
@respx.mock
async def test_probe_custom_headers():
    route = respx.get("https://api.example.com/private").mock(return_value=httpx.Response(200))
    await probe("https://api.example.com/private", "GET", 5000, 200, {"X-API-Key": "secret"}, None)
    assert route.called
    assert route.calls[0].request.headers.get("x-api-key") == "secret"


@pytest.mark.asyncio
@respx.mock
async def test_probe_post_with_body():
    respx.post("https://api.example.com/submit").mock(return_value=httpx.Response(201))
    result = await probe("https://api.example.com/submit", "POST", 5000, 201, {}, '{"key": "value"}')
    assert result.status == "up"
    assert result.status_code == 201
