"""Async write queue for non-blocking persistence."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class AsyncWriteQueue:
    """Fire-and-forget async persistence writes with bounded queue."""

    def __init__(self, *, maxsize: int = 1024) -> None:
        self._queue: asyncio.Queue[tuple[Callable[..., Awaitable[Any]], tuple[Any, ...]]] = (
            asyncio.Queue(maxsize=maxsize)
        )
        self._worker: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="persistence-writer")

    async def drain(self, *, timeout: float = 5.0) -> None:
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except TimeoutError:
            logger.warning("Persistence queue drain timed out")

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        self._closed = True
        if self._worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
        except TimeoutError:
            logger.warning("Persistence queue drain timed out")
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    def submit(
        self,
        coro_fn: Callable[..., Awaitable[Any]],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if self._closed:
            return
        try:
            if kwargs:

                async def _invoke() -> None:
                    await coro_fn(*args, **kwargs)

                self._queue.put_nowait((_invoke, ()))
            else:
                self._queue.put_nowait((coro_fn, args))
        except asyncio.QueueFull:
            logger.warning("Persistence queue full; dropping write")

    async def _run(self) -> None:
        while not self._closed or not self._queue.empty():
            try:
                coro_fn, args = await asyncio.wait_for(self._queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            try:
                await coro_fn(*args)
            except Exception:
                logger.exception("Persistence write failed")
            finally:
                self._queue.task_done()
