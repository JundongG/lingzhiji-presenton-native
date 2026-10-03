# SPDX-License-Identifier: Apache-2.0
# Independent add-on reliability improvement: comments preserve idle SSE streams.
"""Send harmless SSE comments while one upstream event is pending.

This never retries a model request, reveals thinking, or repeats a tool call.
Disconnect cancellation closes the pending event and the underlying iterator.
"""
import asyncio
from contextlib import suppress
from collections.abc import AsyncIterable, AsyncIterator
import anyio
from starlette.responses import StreamingResponse


class ClosingStreamingResponse(StreamingResponse):
    """Close a paused iterator even when ASGI send fails after a heartbeat."""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette's legacy disconnect listener cancels an AnyIO task
            # group. Cleanup must finish inside that cancellation scope too.
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if close is not None:
                    await close()


async def with_sse_keepalive(
    events: AsyncIterable[str], *, interval: float = 15.0
) -> AsyncIterator[str]:
    if interval <= 0:
        raise ValueError("SSE keepalive interval must be positive")
    iterator = events.__aiter__()
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                value = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield value
    finally:
        # The iterator can be canceled while still awaiting its first event,
        # before response-level cleanup runs. Shield this cleanup as well.
        with anyio.CancelScope(shield=True):
            try:
                if pending is not None:
                    if not pending.done():
                        pending.cancel()
                    # Retrieve already-failed tasks too. A live consumer
                    # still receives their exceptions in result() above.
                    with suppress(asyncio.CancelledError, Exception):
                        await pending
            finally:
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    await close()
