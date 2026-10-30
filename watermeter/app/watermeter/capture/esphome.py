"""ESPHome camera client (task B2). Uses `aioesphomeapi`; keeps one connection and reconnects with backoff.

The device has one camera entity and one light entity (`esphome/watermeter-cam.yaml`). A burst is: light on →
settle → N single images → light off. Several API clients may be connected to the device at once, so Home Assistant
can stay connected too.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ..models import Frame
from ..settings import Options

log = logging.getLogger(__name__)

IMAGE_TIMEOUT_S = 5.0        # wait for one image, then ask again
IMAGE_TRIES = 3              # the camera sends nothing for a frame it failed to take (2026-10-30: often)
# The camera driver fills its buffer as soon as the previous image is taken, and the camera is idle between bursts:
# the first image of a burst was shot at the end of the previous one (often in the dark). It is thrown away.
DISCARD_FRAMES = 1
BACKOFF_START_S = 2.0        # wait after the first failed connection attempt
BACKOFF_MAX_S = 60.0


class CameraError(Exception):
    """The camera could not be reached or did not deliver an image."""


def _default_client_factory(options: Options) -> Any:
    from aioesphomeapi import APIClient  # imported here so the tests and the web UI do not need the library

    return APIClient(options.esphome_host, options.esphome_port, None, noise_psk=options.esphome_encryption_key or None)


class CameraClient:
    def __init__(self, options: Options, client_factory: Callable[[Options], Any] = _default_client_factory) -> None:
        self._options = options
        self._factory = client_factory
        self._client: Any = None
        self._connected = False
        self._light_key: int | None = None
        self._camera_key: int | None = None
        self._waiting: asyncio.Future[bytes] | None = None
        self._backoff_s = 0.0
        self._retry_at = 0.0           # loop time before which no new connection attempt is made
        self._lock = asyncio.Lock()    # one burst at a time

    async def connect(self) -> None:
        """Connect and find the camera and the light. Raises CameraError; a failed attempt delays the next one
        (2 s, doubling to 60 s) so a camera that is off is not hammered."""
        if not self._options.esphome_host:
            raise CameraError("no camera address: set esphome_host in the add-on's Configuration tab")
        loop = asyncio.get_running_loop()
        if loop.time() < self._retry_at:
            raise CameraError(f"camera not reachable, trying again in {self._retry_at - loop.time():.0f} s")
        client = self._factory(self._options)
        try:
            await client.connect(on_stop=self._on_stop, login=True)
            entities, _ = await client.list_entities_services()
        except Exception as e:  # aioesphomeapi raises several kinds (APIConnectionError, TimeoutError, ...)
            self._backoff_s = min(max(self._backoff_s * 2, BACKOFF_START_S), BACKOFF_MAX_S)
            self._retry_at = loop.time() + self._backoff_s
            raise CameraError(f"cannot connect to {self._options.esphome_host}: {e}") from e
        from aioesphomeapi import CameraInfo, LightInfo

        self._light_key = self._camera_key = None
        for entity in entities:
            if isinstance(entity, LightInfo) and self._light_key is None:
                self._light_key = entity.key
            elif isinstance(entity, CameraInfo) and self._camera_key is None:
                self._camera_key = entity.key
        if self._light_key is None or self._camera_key is None:
            await client.disconnect()
            raise CameraError("the device has no camera or no light entity (wrong ESPHome config?)")
        client.subscribe_states(self._on_state)
        self._client, self._connected, self._backoff_s, self._retry_at = client, True, 0.0, 0.0
        log.info("camera connected")

    async def _on_stop(self, expected_disconnect: bool) -> None:
        self._connected = False
        if self._waiting and not self._waiting.done():
            self._waiting.set_exception(CameraError("connection to the camera was lost"))
        log.warning("camera connection closed")

    def _on_state(self, state: Any) -> None:
        from aioesphomeapi import CameraState

        if isinstance(state, CameraState) and state.key == self._camera_key:
            if self._waiting and not self._waiting.done():
                self._waiting.set_result(bytes(state.data))

    async def _image(self) -> bytes:
        """One image; asked again up to IMAGE_TRIES times if none comes. A lost connection is not retried."""
        for attempt in range(1, IMAGE_TRIES + 1):
            self._waiting = asyncio.get_running_loop().create_future()
            self._client.request_single_image()
            try:
                return await asyncio.wait_for(self._waiting, IMAGE_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("no image from the camera (try %d of %d)", attempt, IMAGE_TRIES)
            finally:
                self._waiting = None
        raise CameraError(f"the camera sent no image ({IMAGE_TRIES} tries)")

    def _light(self, on: bool, brightness: float = 1.0) -> None:
        if on:
            self._client.light_command(self._light_key, state=True, brightness=brightness, transition_length=0)
        else:
            self._client.light_command(self._light_key, state=False, transition_length=0)

    async def capture_burst(self, frames: int, settle_s: float, brightness: float) -> list[Frame]:
        """Light on (brightness) → wait settle_s → discard the stale buffered image → take `frames` single images →
        light off (also on errors)."""
        async with self._lock:
            if not self._connected:
                await self.connect()
            out: list[Frame] = []
            try:
                self._light(True, brightness)
                await asyncio.sleep(settle_s)
                for _ in range(DISCARD_FRAMES):
                    await self._image()
                for index in range(frames):
                    jpeg = await self._image()
                    out.append(Frame(jpeg=jpeg, captured_at=datetime.now(timezone.utc), index=index))
            finally:
                try:
                    self._light(False)
                except Exception:  # the connection may be gone; the device keeps its light off on restart
                    log.warning("could not switch the light off", exc_info=True)
            return out

    async def close(self) -> None:
        self._connected = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                log.debug("disconnect failed", exc_info=True)
            self._client = None
