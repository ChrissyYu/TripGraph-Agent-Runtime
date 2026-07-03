"""Integration tests for HTTP API."""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(async_client) -> None:
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_endpoint(async_client) -> None:
    response = await async_client.post(
        "/api/v1/chat",
        json={"session_id": "test-session", "message": "hello", "stream": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "test-session"
    assert "hello" in body["message"].lower()
