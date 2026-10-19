"""
WebSocket client (PC Fijo → laptop JARVIS server).

Keeps a resilient connection, forwards agent events, and optionally plays TTS chunks.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = os.environ.get("JARVIS_WS_URL", "ws://127.0.0.1:8765")
RECONNECT_BASE_SEC = float(os.environ.get("JARVIS_WS_RECONNECT", "3"))


class JarvisWsClient:
    def __init__(
        self,
        url: str = DEFAULT_WS_URL,
        *,
        on_message: Optional[Callable[[dict[str, Any]], None]] = None,
        on_tts_chunk: Optional[Callable[[bytes, str], None]] = None,
        client_role: str = "agent",
    ) -> None:
        self.url = url
        self.on_message = on_message
        self.on_tts_chunk = on_tts_chunk
        self.client_role = client_role
        self._ws: Optional[WebSocketClientProtocol] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._out_queue: Optional[asyncio.Queue[dict[str, Any]]] = None
        self._running = False
        self._connected = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="JarvisWsClient", daemon=True)
        self._thread.start()
        if not self._connected.wait(timeout=15):
            logger.warning("WebSocket not connected after 15s (%s)", self.url)

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._out_queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    async def _shutdown(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        self._connected.clear()

    async def _main(self) -> None:
        backoff = RECONNECT_BASE_SEC
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=16 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    backoff = RECONNECT_BASE_SEC
                    logger.info("Connected to %s", self.url)
                    await ws.send(json.dumps({"type": "hello", "role": self.client_role}, ensure_ascii=False))
                    consumer = asyncio.create_task(self._send_worker(ws))
                    try:
                        async for raw in ws:
                            if isinstance(raw, bytes):
                                continue
                            self._handle_incoming(raw)
                    finally:
                        consumer.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await consumer
            except Exception as exc:
                logger.warning("WS disconnected: %s", exc)
            finally:
                self._ws = None
                self._connected.clear()
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)

    async def _send_worker(self, ws: WebSocketClientProtocol) -> None:
        assert self._out_queue is not None
        while True:
            payload = await self._out_queue.get()
            await ws.send(json.dumps(payload, ensure_ascii=False))

    def _handle_incoming(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("type") == "tts_chunk" and data.get("data"):
            chunk = base64.b64decode(data["data"])
            mime = str(data.get("mime") or "audio/mpeg")
            if self.on_tts_chunk:
                self.on_tts_chunk(chunk, mime)
            else:
                _default_play_tts_chunk(chunk)
        if self.on_message:
            self.on_message(data)

    def send_json(self, payload: dict[str, Any], *, wait: bool = False) -> None:
        if not self._loop or self._out_queue is None:
            raise RuntimeError("Client not started")
        fut = asyncio.run_coroutine_threadsafe(self._out_queue.put(payload), self._loop)
        if wait:
            fut.result(timeout=10)

    def set_state(self, state: str) -> None:
        self.send_json({"type": "state", "state": state})

    def send_subtitle(self, text: str) -> None:
        self.send_json({"type": "subtitle", "text": text})

    def send_audio_wav(self, wav_bytes: bytes, *, wait: bool = False) -> None:
        self.send_json(
            {
                "type": "audio",
                "format": "wav",
                "sample_rate": 16000,
                "channels": 1,
                "data": base64.b64encode(wav_bytes).decode("ascii"),
            },
            wait=wait,
        )

    def send_audio_pcm(self, pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> None:
        self.send_json(
            {
                "type": "audio",
                "format": "pcm",
                "sample_rate": sample_rate,
                "channels": channels,
                "data": base64.b64encode(pcm_bytes).decode("ascii"),
            }
        )


_tts_player_lock = threading.Lock()
_tts_buffer = bytearray()


def _default_play_tts_chunk(chunk: bytes) -> None:
    global _tts_buffer
    with _tts_player_lock:
        _tts_buffer.extend(chunk)
        if len(_tts_buffer) < 4096:
            return
        data = bytes(_tts_buffer)
        _tts_buffer.clear()
    try:
        import tempfile
        from pathlib import Path

        path = Path(tempfile.gettempdir()) / f"jarvis_tts_{int(time.time() * 1000)}.mp3"
        path.write_bytes(data)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("TTS chunk playback skipped: %s", exc)
