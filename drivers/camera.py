from __future__ import annotations

import asyncio
import time
from threading import Lock

import cv2
import numpy as np
from loguru import logger

from config.settings import AppConfig


class CameraManager:
    def __init__(self, config: AppConfig) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._lock = Lock()
        self._running = False
        self._width = config.camera.width
        self._height = config.camera.height
        self._fps = config.camera.fps
        self._device_index = config.camera.device_index
        self._enabled = config.camera.enabled
        self._frame: bytes | None = None

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def is_running(self) -> bool:
        return self._running

    def initialize(self) -> None:
        if not self._enabled:
            logger.info("Camera disabled in config")
            return

        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            logger.warning(f"Could not open camera at index {self._device_index}")
            self._cap = None
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        logger.info(f"Camera initialized: {self._width}x{self._height} @ {self._fps}fps")

    def read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        with self._lock:
            ret, frame = self._cap.read()
            if ret:
                return frame
            return None

    def encode_frame(self, frame: np.ndarray | None = None) -> bytes | None:
        if frame is None:
            frame = self.read_frame()
        if frame is None:
            return None
        ret, jpeg = cv2.imencode(".jpg", frame)
        if ret:
            return jpeg.tobytes()
        return None

    def get_latest_jpeg(self) -> bytes | None:
        return self._frame

    async def start_capture_loop(self) -> None:
        if self._cap is None:
            return

        self._running = True
        logger.info("Camera capture loop started")

        loop = asyncio.get_event_loop()
        interval = 1.0 / self._fps if self._fps > 0 else 1.0 / 30

        while self._running:
            frame_data = await loop.run_in_executor(None, self.encode_frame)
            if frame_data:
                self._frame = frame_data
            await asyncio.sleep(interval)

    def stop_capture(self) -> None:
        self._running = False

    def release(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
            logger.info("Camera released")
