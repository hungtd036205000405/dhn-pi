from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
    from aiortc.mediastreams import VideoFrame
    _HAS_WEBRTC = True
except ImportError:
    _HAS_WEBRTC = False
    RTCPeerConnection = None
    VideoStreamTrack = object

import numpy as np


if _HAS_WEBRTC:

    class OpenCVVideoTrack(VideoStreamTrack):
        def __init__(self, get_frame_cb, camera_id: int) -> None:
            super().__init__()
            self._get_frame = get_frame_cb
            self._camera_id = camera_id
            self._kind = "video"

        async def recv(self) -> VideoFrame:
            jpeg = await asyncio.get_event_loop().run_in_executor(
                None, self._get_frame
            )
            if jpeg is None:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                frame = VideoFrame.from_ndarray(blank, format="bgr24")
            else:
                import cv2
                arr = np.frombuffer(jpeg, dtype=np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                frame = VideoFrame.from_ndarray(bgr, format="bgr24")
            frame.pts = int(time.time() * 90000)
            frame.time_base = 1 / 90000
            return frame


class WebRTCStreamer:
    def __init__(self) -> None:
        self._pcs: dict[str, RTCPeerConnection] = {}
        self._cleanup_task: asyncio.Task | None = None

    @property
    def available(self) -> bool:
        return _HAS_WEBRTC

    async def create_answer(self, offer_sdp: str, get_frame_cb, camera_id: int) -> dict[str, str] | None:
        if not _HAS_WEBRTC:
            logger.error("aiortc not installed, WebRTC unavailable")
            return None

        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        pc = RTCPeerConnection()
        pc_id = f"cam_{camera_id}_{id(pc)}"

        track = OpenCVVideoTrack(get_frame_cb, camera_id)
        pc.addTrack(track)

        @pc.on("iceconnectionstatechange")
        async def on_ice_state():
            if pc.iceConnectionState in ("failed", "closed", "disconnected"):
                logger.info(f"WebRTC {pc_id}: connection {pc.iceConnectionState}")
                await self._close_pc(pc_id)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        self._pcs[pc_id] = pc
        self._schedule_cleanup()

        return {"sdp": pc.localDescription.sdp, "type": "answer"}

    async def _close_pc(self, pc_id: str) -> None:
        pc = self._pcs.pop(pc_id, None)
        if pc:
            try:
                await pc.close()
            except Exception:
                pass

    def _schedule_cleanup(self) -> None:
        async def _cleanup_loop():
            await asyncio.sleep(300)
            now = time.time()
            for pc_id in list(self._pcs.keys()):
                pc = self._pcs[pc_id]
                if pc.iceConnectionState in ("failed", "closed", "disconnected"):
                    await self._close_pc(pc_id)

        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(_cleanup_loop())

    async def stop_all(self) -> None:
        for pc_id in list(self._pcs.keys()):
            await self._close_pc(pc_id)
        logger.info("All WebRTC connections closed")
