"""Minimal async gateway client for the Fluxer real-time WebSocket API.

Implements the handshake documented for Fluxer: connect -> receive
HELLO (op 10) with a heartbeat_interval -> send IDENTIFY (op 2) with
the bot token/intents -> receive DISPATCH (op 0) events, while a
background task sends HEARTBEAT (op 1) on schedule and reconnects on
drop. This is intentionally dependency-light (raw `websockets`) so it
works identically against the official instance or a self-hosted one —
the ws URL is discovered per-instance via `GET /gateway/bot`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import websockets

from bot.rest import FluxerREST
from common.config import config

log = logging.getLogger("fluxbot.gateway")

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

EventHandler = Callable[[dict], Awaitable[None]]


def _with_gateway_params(url: str) -> str:
    """Ensure the gateway URL carries ?v=<version>&encoding=json.

    Fluxer's own SDKs default to connecting with these query params
    explicitly set (e.g. `wss://gateway.fluxer.app/?v=1&encoding=json`)
    rather than relying on server-side defaults — omitting them gets a
    4012 "Invalid API version" close from at least some instances.
    Existing query params (if any) are preserved/overridden, not
    duplicated.
    """
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    params.setdefault("v", str(config.gateway_version))
    params.setdefault("encoding", "json")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


class GatewayClient:
    def __init__(self, rest: FluxerREST, token: str, intents: int):
        self.rest = rest
        self.token = token
        self.intents = intents
        self._handlers: dict[str, list[EventHandler]] = {}
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._seq: Optional[int] = None
        self._session_id: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self.user: Optional[dict] = None  # populated on READY
        self.connected_at: Optional[float] = None
        self.latency_ms: Optional[float] = None
        self._last_heartbeat_sent: Optional[float] = None

    def on(self, event_name: str) -> Callable[[EventHandler], EventHandler]:
        """Decorator: register a coroutine for a gateway event, e.g. MESSAGE_CREATE."""
        def deco(fn: EventHandler) -> EventHandler:
            self._handlers.setdefault(event_name.upper(), []).append(fn)
            return fn
        return deco

    async def _dispatch(self, event_name: str, data: dict) -> None:
        for handler in self._handlers.get(event_name, []):
            try:
                await handler(data)
            except Exception:
                log.exception("Unhandled error in handler for %s", event_name)

    async def _heartbeat_loop(self, interval_ms: float) -> None:
        # Jitter the first beat per gateway convention.
        await asyncio.sleep((interval_ms / 1000) * random.random())
        while self._running:
            try:
                self._last_heartbeat_sent = time.monotonic()
                await self._ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
            except Exception:
                return
            await asyncio.sleep(interval_ms / 1000)

    async def _identify(self) -> None:
        await self._ws.send(json.dumps({
            "op": OP_IDENTIFY,
            "d": {
                "token": self.token,
                "intents": self.intents,
                "properties": {
                    "os": "linux",
                    "browser": "FluxBot",
                    "device": "FluxBot",
                },
            },
        }))

    async def _connect_once(self) -> None:
        gw = self.rest.gateway_url_hint or (await self.rest.get_gateway_bot())["url"]
        gw = _with_gateway_params(gw)
        log.info("Connecting to gateway %s", gw)
        async with websockets.connect(gw, max_size=None) as ws:
            self._ws = ws
            hello_raw = await ws.recv()
            hello = json.loads(hello_raw)
            if hello.get("op") != OP_HELLO:
                raise RuntimeError(f"Expected HELLO, got op={hello.get('op')}")
            interval_ms = hello["d"]["heartbeat_interval"]
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval_ms))
            await self._identify()

            async for raw in ws:
                payload = json.loads(raw)
                op = payload.get("op")
                if op == OP_DISPATCH:
                    self._seq = payload.get("s", self._seq)
                    event_name = payload.get("t", "")
                    data = payload.get("d", {})
                    if event_name == "READY":
                        self._session_id = data.get("session_id")
                        self.user = data.get("user")
                        self.connected_at = time.monotonic()
                        log.info("Ready as %s", (self.user or {}).get("username", "unknown"))
                    await self._dispatch(event_name, data)
                elif op == OP_HEARTBEAT_ACK:
                    if self._last_heartbeat_sent is not None:
                        self.latency_ms = (time.monotonic() - self._last_heartbeat_sent) * 1000
                    continue
                elif op == OP_RECONNECT:
                    log.info("Gateway requested reconnect")
                    return
                elif op == OP_INVALID_SESSION:
                    log.warning("Invalid session, re-identifying from scratch")
                    self._seq = None
                    self._session_id = None
                    await asyncio.sleep(1 + random.random() * 4)
                    return

    async def run_forever(self) -> None:
        self._running = True
        backoff = 1
        while self._running:
            try:
                await self._connect_once()
                backoff = 1
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning("Gateway connection dropped: %s", e)
            except Exception:
                log.exception("Gateway loop error")
            finally:
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
            if not self._running:
                break
            log.info("Reconnecting in %.1fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def stop(self) -> None:
        self._running = False
