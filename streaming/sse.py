"""FastAPI SSE response wrapper."""

import asyncio
from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse

from config.settings import Settings, get_settings
from schemas.streaming import StreamEvent, StreamEventType
from streaming.events import format_sse, format_sse_comment


class SSEResponse(StreamingResponse):
    """StreamingResponse pre-configured for Server-Sent Events."""

    def __init__(self, content: AsyncIterator[str], **kwargs) -> None:
        super().__init__(
            content=content,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
            **kwargs,
        )


async def stream_with_heartbeat(
    events: AsyncIterator[StreamEvent],
    settings: Settings | None = None,
) -> AsyncIterator[str]:
    """Wrap an event stream with periodic heartbeat comments."""
    cfg = settings or get_settings()
    interval = cfg.sse_heartbeat_interval_sec

    async def _heartbeat() -> AsyncIterator[str]:
        while True:
            await asyncio.sleep(interval)
            yield format_sse_comment("heartbeat")

    event_iter = events.__aiter__()
    heartbeat_task: asyncio.Task | None = None

    try:
        while True:
            try:
                event = await asyncio.wait_for(event_iter.__anext__(), timeout=interval)
                yield format_sse(event)
                if event.event in (StreamEventType.DONE, StreamEventType.ERROR):
                    break
            except TimeoutError:
                yield format_sse_comment("heartbeat")
    except StopAsyncIteration:
        pass
