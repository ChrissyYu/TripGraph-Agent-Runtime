"""Integration tests for SSE chat streaming."""

import pytest


@pytest.mark.asyncio
async def test_chat_stream_returns_sse(async_client) -> None:
    response = await async_client.post(
        "/api/v1/chat",
        json={"session_id": "stream-session", "message": "stream me", "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    text = response.text
    assert "event:" in text
    assert "done" in text
