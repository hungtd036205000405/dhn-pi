from __future__ import annotations

import asyncio
import time
from threading import Lock

import cv2
import numpy as np
from loguru import logger

from config.settings import AppConfig


class CameraInstance:
    def __init__(
        self,
        camera_id: int,
        source_type: str,
        width: int,
        height: int,
        fps: int,
        device_index: int | None = None,
        rtsp_url: str | None = None,
    ) -> None:
        self.id = camera_id
        self.source_type = source_type
        self.width = width
        self.height = height
        self.fps = fps
        self.device_index = device_index
        self.rtsp_url = rtsp_url

        self._cap: cv2.VideoCapture | None = None
        self._lock = Lock()
        self._running = False
        self._latest_jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._video_writer: cv2.VideoWriter | None = None
        self._recording_path: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_recording(self) -> bool:
        return self._video_writer is not None

    def _open_capture(self) -> bool:
        source = self.device_index if self.source_type == "webcam" else self.rtsp_url
        if source is None:
            logger.warning(f"Camera {self.id}: no source configured")
            return False

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            logger.warning(f"Camera {self.id}: could not open source {source}")
            return False

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        self._cap = cap
        logger.info(f"Camera {self.id} opened: {source} ({self.width}x{self.height} @ {self.fps}fps)")
        return True

    def _capture_one(self) -> tuple[np.ndarray | None, bytes | None]:
        if self._cap is None:
            return None, None
        with self._lock:
            ret, frame = self._cap.read()
            if not ret:
                return None, None
            ret, jpeg = cv2.imencode(".jpg", frame)
            jpeg_bytes = jpeg.tobytes() if ret else None
            return frame, jpeg_bytes

    def start_recording(self, output_path: str, width: int, height: int, fps: int) -> bool:
        if self._video_writer is not None:
            return False
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(output_path, fourcc, float(fps), (width, height))
        if not writer.isOpened():
            logger.error(f"Camera {self.id}: failed to open VideoWriter at {output_path}")
            return False
        self._video_writer = writer
        self._recording_path = output_path
        logger.info(f"Camera {self.id}: recording started -> {output_path}")
        return True

    def stop_recording(self) -> str | None:
        path = self._recording_path
        if self._video_writer:
            self._video_writer.release()
            self._video_writer = None
        self._recording_path = None
        if path:
            logger.info(f"Camera {self.id}: recording stopped -> {path}")
        return path

    async def start(self) -> bool:
        if self._running:
            return True
        if not self._open_capture():
            return False
        self._running = True
        self._loop = asyncio.get_event_loop()
        asyncio.create_task(self._capture_loop())
        logger.info(f"Camera {self.id} capture loop started")
        return True

    async def _capture_loop(self) -> None:
        interval = 1.0 / self.fps if self.fps > 0 else 1.0 / 15
        while self._running:
            frame, jpeg = await self._loop.run_in_executor(None, self._capture_one)
            if jpeg:
                self._latest_jpeg = jpeg
            if frame is not None:
                self._latest_frame = frame
                writer = self._video_writer
                if writer and writer.isOpened():
                    writer.write(frame)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False
        self.stop_recording()
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
        logger.info(f"Camera {self.id} stopped")

    def get_latest_jpeg(self) -> bytes | None:
        return self._latest_jpeg

    def get_latest_frame(self) -> np.ndarray | None:
        return self._latest_frame


class CameraPool:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool_config = config.camera_pool
        self._instances: dict[int, CameraInstance] = {}
        self._active_count = 0

    async def register_instance(self, camera_id: int, source_type: str,
                                 device_index: int | None = None,
                                 rtsp_url: str | None = None,
                                 width: int = 640, height: int = 480,
                                 fps: int = 15) -> CameraInstance:
        inst = CameraInstance(
            camera_id=camera_id,
            source_type=source_type,
            width=width,
            height=height,
            fps=fps,
            device_index=device_index,
            rtsp_url=rtsp_url,
        )
        self._instances[camera_id] = inst
        return inst

    def unregister_instance(self, camera_id: int) -> None:
        inst = self._instances.pop(camera_id, None)
        if inst and inst.is_running:
            asyncio.create_task(inst.stop())

    def get_instance(self, camera_id: int) -> CameraInstance | None:
        return self._instances.get(camera_id)

    async def start_camera(self, camera_id: int) -> bool:
        if self._active_count >= self._pool_config.max_active:
            logger.warning(f"Max active cameras ({self._pool_config.max_active}) reached")
            return False
        inst = self._instances.get(camera_id)
        if not inst:
            logger.warning(f"Camera {camera_id} not registered")
            return False
        ok = await inst.start()
        if ok:
            self._active_count += 1
        return ok

    async def stop_camera(self, camera_id: int) -> bool:
        inst = self._instances.get(camera_id)
        if not inst:
            return False
        await inst.stop()
        self._active_count = max(0, self._active_count - 1)
        return True

    def get_latest_jpeg(self, camera_id: int) -> bytes | None:
        inst = self._instances.get(camera_id)
        if inst and inst.is_running:
            return inst.get_latest_jpeg()
        return None

    def list_active(self) -> list[int]:
        return [cid for cid, inst in self._instances.items() if inst.is_running]

    def list_all(self) -> list[int]:
        return list(self._instances.keys())

    async def stop_all(self) -> None:
        for camera_id in list(self._instances.keys()):
            await self.stop_camera(camera_id)
        self._instances.clear()
        logger.info("All cameras stopped")

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def max_active(self) -> int:
        return self._pool_config.max_active
