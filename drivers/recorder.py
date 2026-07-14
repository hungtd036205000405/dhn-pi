from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock

from loguru import logger

from config.settings import AppConfig
from core.database import Database
from drivers.camera_pool import CameraPool


class Recorder:
    def __init__(self, config: AppConfig, db: Database, camera_pool: CameraPool) -> None:
        self._config = config
        self._db = db
        self._camera_pool = camera_pool
        self._cfg = config.recording
        self._pool_config = config.camera_pool
        self._output_dir = Path(self._cfg.output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._active_recordings: dict[int, dict[int, str]] = {}
        self._locks: dict[int, Lock] = {}

    def _get_lock(self, position_id: int) -> Lock:
        if position_id not in self._locks:
            self._locks[position_id] = Lock()
        return self._locks[position_id]

    def _make_output_path(self, position_id: int, camera_id: int) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"pos_{position_id}_cam_{camera_id}_{ts}.avi"
        return str(self._output_dir / fname)

    async def start_recording(self, position_id: int) -> bool:
        lock = self._get_lock(position_id)
        with lock:
            if position_id in self._active_recordings:
                logger.warning(f"Position {position_id} already recording")
                return False

            rows = await self._db.fetchall(
                "SELECT camera_id FROM position_cameras WHERE position_id = ?",
                (position_id,),
            )
            if not rows:
                logger.warning(f"Position {position_id} has no cameras")
                return False

            cam_files: dict[int, str] = {}
            for row in rows:
                cam_id = row["camera_id"]
                inst = self._camera_pool.get_instance(cam_id)
                if not inst:
                    logger.warning(f"Camera {cam_id} not registered in pool, skipping")
                    continue
                if not inst.is_running:
                    logger.warning(f"Camera {cam_id} not running, skipping")
                    continue

                path = self._make_output_path(position_id, cam_id)
                w = self._pool_config.record_width
                h = self._pool_config.record_height
                fps = self._pool_config.record_fps
                ok = inst.start_recording(path, w, h, fps)
                if ok:
                    cam_files[cam_id] = path

            if not cam_files:
                logger.warning(f"Position {position_id}: no cameras could start recording")
                return False

            self._active_recordings[position_id] = cam_files

        await self._db.execute(
            "UPDATE positions SET recording = 1, recording_started_at = ? WHERE id = ?",
            (time.time(), position_id),
        )
        await self._db.commit()

        logger.info(f"Recording started for position {position_id} ({len(cam_files)} camera(s))")
        return True

    async def stop_recording(self, position_id: int) -> dict | None:
        lock = self._get_lock(position_id)
        with lock:
            cam_files = self._active_recordings.pop(position_id, None)
            if cam_files is None:
                logger.warning(f"Position {position_id} not recording")
                return None

            duration = None
            started_row = await self._db.fetchone(
                "SELECT recording_started_at FROM positions WHERE id = ?",
                (position_id,),
            )
            if started_row and started_row["recording_started_at"]:
                duration = time.time() - float(started_row["recording_started_at"])

            files_info = []
            for cam_id, path in cam_files.items():
                inst = self._camera_pool.get_instance(cam_id)
                if inst:
                    inst.stop_recording()
                if os.path.exists(path):
                    fsize = os.path.getsize(path)
                    files_info.append({"camera_id": cam_id, "path": path, "size_bytes": fsize})

                await self._db.execute(
                    "INSERT INTO recording_files (position_id, camera_id, file_path, stopped_at, duration_seconds) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (position_id, cam_id, path, time.time(), duration),
                )

        await self._db.execute(
            "UPDATE positions SET recording = 0, recording_started_at = NULL WHERE id = ?",
            (position_id,),
        )
        await self._db.commit()

        logger.info(f"Recording stopped for position {position_id} ({duration:.1f}s)")
        return {"duration_seconds": duration, "files": files_info}

    async def get_recording_status(self, position_id: int) -> dict:
        row = await self._db.fetchone(
            "SELECT recording, recording_started_at FROM positions WHERE id = ?",
            (position_id,),
        )
        if not row:
            return {"recording": False}
        recording = bool(row["recording"])
        started_at = float(row["recording_started_at"]) if row["recording_started_at"] else None

        cameras = []
        if recording and position_id in self._active_recordings:
            for cam_id in self._active_recordings[position_id]:
                cameras.append({"camera_id": cam_id})

        return {
            "recording": recording,
            "started_at": started_at,
            "cameras": cameras,
        }

    async def stop_all(self) -> None:
        for pos_id in list(self._active_recordings.keys()):
            await self.stop_recording(pos_id)
        logger.info("All recordings stopped")
