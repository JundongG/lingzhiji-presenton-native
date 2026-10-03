# SPDX-License-Identifier: Apache-2.0
import asyncio
import unittest

from starlette.requests import ClientDisconnect
from utils.sse_keepalive import ClosingStreamingResponse, with_sse_keepalive


class SseKeepaliveTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_events_without_duplicate_upstream_calls(self):
        calls = []

        async def events():
            calls.append("start")
            yield "data: first\n\n"
            await asyncio.sleep(.035)
            calls.append("done")
            yield "data: second\n\n"

        received = [x async for x in with_sse_keepalive(events(), interval=.01)]
        self.assertEqual([x for x in received if not x.startswith(":")], ["data: first\n\n", "data: second\n\n"])
        self.assertGreaterEqual(received.count(": keep-alive\n\n"), 2)
        self.assertEqual(calls, ["start", "done"])

    async def test_close_cancels_pending_provider_and_closes_iterator(self):
        closed = asyncio.Event()
        started = asyncio.Event()

        async def events():
            try:
                started.set()
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed.set()

        stream = with_sse_keepalive(events(), interval=.01)
        self.assertEqual(await anext(stream), ": keep-alive\n\n")
        self.assertTrue(started.is_set())
        await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_disconnect_cancellation_is_not_swallowed(self):
        closed = asyncio.Event()

        async def events():
            try:
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed.set()

        stream = with_sse_keepalive(events(), interval=10)
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(closed.is_set())

    async def test_upstream_exception_is_preserved(self):
        async def events():
            raise RuntimeError("synthetic failure")
            yield "never"

        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            _ = [x async for x in with_sse_keepalive(events(), interval=.01)]

    async def test_close_retrieves_failure_that_arrived_after_heartbeat(self):
        release = asyncio.Event()
        closed = asyncio.Event()
        unhandled = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: unhandled.append(context))

        async def events():
            try:
                await release.wait()
                raise RuntimeError("synthetic late failure")
                yield "never"
            finally:
                closed.set()

        try:
            stream = with_sse_keepalive(events(), interval=.01)
            self.assertEqual(await anext(stream), ": keep-alive\n\n")
            release.set()
            await closed.wait()
            await asyncio.sleep(0)
            await stream.aclose()
            await asyncio.sleep(0)
            self.assertEqual(unhandled, [])
        finally:
            loop.set_exception_handler(previous)

    async def test_empty_stream_completes(self):
        async def events():
            if False:
                yield "unused"
        self.assertEqual([x async for x in with_sse_keepalive(events())], [])

    async def test_asgi_send_failure_closes_paused_upstream(self):
        closed = asyncio.Event()

        async def events():
            try:
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed.set()

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("synthetic disconnected client")

        response = ClosingStreamingResponse(with_sse_keepalive(events(), interval=.01), media_type="text/event-stream")
        with self.assertRaises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        self.assertTrue(closed.is_set())

    async def test_legacy_asgi_disconnect_closes_upstream(self):
        closed = asyncio.Event()
        sent = []

        async def events():
            try:
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed.set()

        async def receive():
            await asyncio.sleep(.025)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        response = ClosingStreamingResponse(with_sse_keepalive(events(), interval=.01), media_type="text/event-stream")
        await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)
        self.assertTrue(any(x["type"] == "http.response.body" for x in sent))
        self.assertTrue(closed.is_set())

    async def test_legacy_disconnect_before_first_heartbeat_finishes_async_cleanup(self):
        closed = asyncio.Event()

        async def events():
            try:
                await asyncio.Event().wait()
                yield "never"
            finally:
                await asyncio.sleep(.005)
                closed.set()

        async def receive():
            await asyncio.sleep(.01)
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        response = ClosingStreamingResponse(with_sse_keepalive(events(), interval=10), media_type="text/event-stream")
        await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)
        self.assertTrue(closed.is_set())

    async def test_invalid_interval_is_rejected(self):
        async def events():
            if False:
                yield "unused"
        with self.assertRaises(ValueError):
            _ = [x async for x in with_sse_keepalive(events(), interval=0)]


if __name__ == "__main__":
    unittest.main()
