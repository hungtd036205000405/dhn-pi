from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Path as FastAPIPath, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from loguru import logger
from pydantic import BaseModel, Field

from config.settings import AppConfig
from models.schemas import (
    CameraCreate,
    CameraResponse,
    CameraUpdate,
    HealthResponse,
    IPCamScanResult,
    PositionCameraAssign,
    PositionCreate,
    PositionDetailResponse,
    PositionResponse,
    PositionUpdate,
    RecordingStartResponse,
    RecordingStatusResponse,
    RecordingStopResponse,
    ScanResponse,
    UXAssign,
    UXDeviceResponse,
    WebCamScanResult,
    WebRTCAnswerResponse,
    WebRTCOfferRequest,
)

TAG_SYSTEM = "System"
TAG_GPIO = "GPIO"
TAG_SENSORS = "Sensors"
TAG_CAMERA = "Camera"
TAG_MQTT = "MQTT"
TAG_POSITION = "Position"
TAG_STREAM = "Stream"
TAG_RECORDING = "Recording"

_tags_metadata = [
    {"name": TAG_SYSTEM, "description": "Health check and system status."},
    {"name": TAG_GPIO, "description": "Manage GPIO devices."},
    {"name": TAG_SENSORS, "description": "Read sensor data."},
    {"name": TAG_CAMERA, "description": "Camera CRUD and management."},
    {"name": TAG_MQTT, "description": "Publish MQTT messages."},
    {"name": TAG_POSITION, "description": "Position (bàn) CRUD, camera assignment, UX/TX."},
    {"name": TAG_STREAM, "description": "Live camera streaming (MJPEG + WebRTC)."},
    {"name": TAG_RECORDING, "description": "Recording control for positions."},
]


class ErrorResponse(BaseModel):
    detail: str


def _row_to_camera(row, online: bool = False, auto_detected: bool | None = None) -> dict:
    if auto_detected is None:
        try:
            auto_detected = bool(row["auto_detected"])
        except (KeyError, IndexError):
            auto_detected = False
    return {
        "id": row["id"],
        "name": row["name"],
        "source_type": row["source_type"],
        "device_index": row["device_index"],
        "rtsp_url": row["rtsp_url"],
        "width": row["width"],
        "height": row["height"],
        "fps": row["fps"],
        "enabled": bool(row["enabled"]),
        "online": online,
        "auto_detected": auto_detected,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_position(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "recording": bool(row["recording"]),
        "recording_started_at": (
            float(row["recording_started_at"]) if row["recording_started_at"] else None
        ),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_app(config: AppConfig, controller=None) -> FastAPI:
    from core.controller import Controller

    app = FastAPI(
        title="DHN-Pi",
        version="0.1.0",
        description="REST API for DHN-Pi IoT edge controller — GPIO, sensors, camera, positions, recording.",
        docs_url="/docs" if config.web.swagger_enabled else None,
        redoc_url=None,
        openapi_tags=_tags_metadata,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ Health
    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=[TAG_SYSTEM],
        summary="Service health check",
    )
    async def health():
        if controller is None:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        stats = controller.stats
        return {
            "status": "ok",
            "ts": time.time(),
            "device_code": config.device_code,
            "hostname": stats._hostname,
            "ip": stats._ip,
            "camera_count": controller.camera_pool.active_count if controller.camera_pool else 0,
            "recording_count": len(controller.recorder._active_recordings) if controller.recorder else 0,
            "cpu_usage": stats.get_dynamic().get("cpuUsage", 0),
            "memory_usage_mb": stats.get_dynamic().get("memoryUsageMb", 0),
            "disk_free_gb": stats.get_dynamic().get("diskFreeGb", 0),
        }

    # ------------------------------------------------------------------- GPIO
    @app.get(
        "/gpio",
        tags=[TAG_GPIO],
        summary="List GPIO devices",
    )
    async def list_gpio():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        return {"devices": controller.gpio.list_devices()}

    @app.post(
        "/gpio/{name}",
        tags=[TAG_GPIO],
        summary="Set GPIO output state",
    )
    async def set_gpio(
        name: str = FastAPIPath(..., description="GPIO device name"),
        state: bool = Query(..., description="true=on, false=off"),
    ):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        ok = controller.gpio.set_output(name, state)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Device '{name}' not found or not writable")
        return {"device": name, "state": state}

    # ---------------------------------------------------------------- Sensors
    @app.get(
        "/sensors",
        tags=[TAG_SENSORS],
        summary="Read all sensors",
    )
    async def read_sensors():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        data = await controller.sensors.read_all()
        return {"sensors": data}

    # ----------------------------------------------------------- Positions CRUD
    @app.get(
        "/api/positions",
        response_model=list[PositionResponse],
        tags=[TAG_POSITION],
        summary="List all positions",
    )
    async def list_positions():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        rows = await controller.db.fetchall("SELECT * FROM positions ORDER BY id")
        return [_row_to_position(r) for r in rows]

    @app.post(
        "/api/positions",
        response_model=PositionResponse,
        tags=[TAG_POSITION],
        summary="Create a position",
        status_code=201,
    )
    async def create_position(body: PositionCreate):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        cursor = await controller.db.execute(
            "INSERT INTO positions (name, description) VALUES (?, ?)",
            (body.name, body.description),
        )
        await controller.db.commit()
        row = await controller.db.fetchone(
            "SELECT * FROM positions WHERE id = ?", (cursor.lastrowid,)
        )
        return _row_to_position(row)

    @app.get(
        "/api/positions/{position_id}",
        response_model=PositionDetailResponse,
        tags=[TAG_POSITION],
        summary="Get position with cameras and UX/TX",
    )
    async def get_position(position_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        row = await controller.db.fetchone(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")

        result = _row_to_position(row)

        cam_rows = await controller.db.fetchall(
            """SELECT c.* FROM cameras c
               JOIN position_cameras pc ON pc.camera_id = c.id
               WHERE pc.position_id = ?""",
            (position_id,),
        )
        live_usb = set(await controller.camera_scanner.get_available_usb())
        result["cameras"] = [
            _row_to_camera(r, online=(
                r["device_index"] in live_usb if r["source_type"] == "webcam"
                else await controller.camera_scanner._check_rtsp(r["rtsp_url"], 2) if r["rtsp_url"]
                else False
            ))
            for r in cam_rows
        ]

        ux = await controller.db.fetchone(
            "SELECT * FROM position_uxtx WHERE position_id = ?", (position_id,)
        )
        if ux:
            result["uxtx"] = {
                "device_type": ux["device_type"],
                "gpio_pin": ux["gpio_pin"],
                "uxtx_id": ux["uxtx_id"],
            }

        return result

    @app.put(
        "/api/positions/{position_id}",
        response_model=PositionResponse,
        tags=[TAG_POSITION],
        summary="Update a position",
    )
    async def update_position(position_id: int, body: PositionUpdate):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        row = await controller.db.fetchone(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Position not found")

        fields = {}
        if body.name is not None:
            fields["name"] = body.name
        if body.description is not None:
            fields["description"] = body.description
        if fields:
            fields["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [position_id]
            await controller.db.execute(
                f"UPDATE positions SET {set_clause} WHERE id = ?", tuple(vals)
            )
            await controller.db.commit()

        row = await controller.db.fetchone(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        )
        return _row_to_position(row)

    @app.delete(
        "/api/positions/{position_id}",
        tags=[TAG_POSITION],
        summary="Delete a position",
        status_code=204,
    )
    async def delete_position(position_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        if controller.recorder:
            await controller.recorder.stop_recording(position_id)
        await controller.db.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        await controller.db.commit()

    # ------------------------------------------------------------ Cameras CRUD
    @app.get(
        "/api/cameras",
        response_model=list[CameraResponse],
        tags=[TAG_CAMERA],
        summary="List all cameras",
    )
    async def list_cameras():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        rows = await controller.db.fetchall("SELECT * FROM cameras ORDER BY id")
        live_usb = await controller.camera_scanner.get_available_usb()
        live_usb_set = set(live_usb)

        seen_indices: set[int] = set()
        for r in rows:
            if r["source_type"] == "webcam" and r["device_index"] is not None:
                seen_indices.add(r["device_index"])

        for idx in sorted(live_usb_set):
            if idx not in seen_indices:
                cursor = await controller.db.execute(
                    """INSERT INTO cameras (name, source_type, device_index, auto_detected)
                       VALUES (?, ?, ?, 1)""",
                    (f"USB Webcam {idx}", "webcam", idx),
                )
                await controller.db.commit()
                if controller.camera_pool:
                    await controller.camera_pool.register_instance(
                        camera_id=cursor.lastrowid, source_type="webcam",
                        device_index=idx, rtsp_url=None,
                        width=640, height=480, fps=15,
                    )
                seen_indices.add(idx)

        rows = await controller.db.fetchall("SELECT * FROM cameras ORDER BY id")
        live_usb_set = set(live_usb)
        result: list[dict] = []
        for r in rows:
            if r["source_type"] == "webcam":
                online = r["device_index"] in live_usb_set
                if online:
                    live_usb_set.discard(r["device_index"])
            elif r["source_type"] == "ip" and r["rtsp_url"]:
                online = await controller.camera_scanner._check_rtsp(r["rtsp_url"], 2)
            else:
                online = False
            result.append(_row_to_camera(r, online=online))
        return result

    @app.post(
        "/api/cameras",
        response_model=CameraResponse,
        tags=[TAG_CAMERA],
        summary="Create a camera",
        status_code=201,
    )
    async def create_camera(body: CameraCreate):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        if body.source_type == "webcam" and body.device_index is None:
            raise HTTPException(status_code=400, detail="device_index required for webcam")
        if body.source_type == "ip" and not body.rtsp_url:
            raise HTTPException(status_code=400, detail="rtsp_url required for IP camera")

        cursor = await controller.db.execute(
            """INSERT INTO cameras (name, source_type, device_index, rtsp_url, width, height, fps)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (body.name, body.source_type, body.device_index, body.rtsp_url,
             body.width, body.height, body.fps),
        )
        await controller.db.commit()
        row = await controller.db.fetchone(
            "SELECT * FROM cameras WHERE id = ?", (cursor.lastrowid,)
        )

        if controller.camera_pool:
            await controller.camera_pool.register_instance(
                camera_id=row["id"],
                source_type=row["source_type"],
                device_index=row["device_index"],
                rtsp_url=row["rtsp_url"],
                width=row["width"],
                height=row["height"],
                fps=row["fps"],
            )

        return _row_to_camera(row)

    @app.get(
        "/api/cameras/{camera_id}",
        response_model=CameraResponse,
        tags=[TAG_CAMERA],
        summary="Get a camera",
    )
    async def get_camera(camera_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        row = await controller.db.fetchone(
            "SELECT * FROM cameras WHERE id = ?", (camera_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        return _row_to_camera(row)

    @app.put(
        "/api/cameras/{camera_id}",
        response_model=CameraResponse,
        tags=[TAG_CAMERA],
        summary="Update a camera",
    )
    async def update_camera(camera_id: int, body: CameraUpdate):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        row = await controller.db.fetchone(
            "SELECT * FROM cameras WHERE id = ?", (camera_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")

        fields = {}
        for key in ("name", "source_type", "device_index", "rtsp_url", "width", "height", "fps", "enabled"):
            val = getattr(body, key, None)
            if val is not None:
                fields[key] = val
        if fields:
            fields["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [camera_id]
            await controller.db.execute(
                f"UPDATE cameras SET {set_clause} WHERE id = ?", tuple(vals)
            )
            await controller.db.commit()

            if controller.camera_pool:
                controller.camera_pool.unregister_instance(camera_id)
                await controller.camera_pool.register_instance(
                    camera_id=camera_id,
                    source_type=fields.get("source_type", row["source_type"]),
                    device_index=fields.get("device_index", row["device_index"]),
                    rtsp_url=fields.get("rtsp_url", row["rtsp_url"]),
                    width=fields.get("width", row["width"]),
                    height=fields.get("height", row["height"]),
                    fps=fields.get("fps", row["fps"]),
                )

        row = await controller.db.fetchone(
            "SELECT * FROM cameras WHERE id = ?", (camera_id,)
        )
        return _row_to_camera(row)

    @app.delete(
        "/api/cameras/{camera_id}",
        tags=[TAG_CAMERA],
        summary="Delete a camera",
        status_code=204,
    )
    async def delete_camera(camera_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        if controller.camera_pool:
            await controller.camera_pool.stop_camera(camera_id)
            controller.camera_pool.unregister_instance(camera_id)
        await controller.db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
        await controller.db.commit()

    # ---------------------------------------------------- Position-Camera Assignment
    @app.post(
        "/api/positions/{position_id}/cameras",
        tags=[TAG_POSITION],
        summary="Assign camera to position",
        status_code=201,
    )
    async def assign_camera(position_id: int, body: PositionCameraAssign):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")

        pos = await controller.db.fetchone(
            "SELECT id FROM positions WHERE id = ?", (position_id,)
        )
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found")
        cam = await controller.db.fetchone(
            "SELECT id FROM cameras WHERE id = ?", (body.camera_id,)
        )
        if not cam:
            raise HTTPException(status_code=404, detail="Camera not found")

        pos_count = await controller.db.fetchone(
            "SELECT COUNT(*) as cnt FROM position_cameras WHERE position_id = ?",
            (position_id,),
        )
        if pos_count and pos_count["cnt"] >= 2:
            raise HTTPException(status_code=400, detail="Max 2 cameras per position")

        cam_count = await controller.db.fetchone(
            "SELECT COUNT(*) as cnt FROM position_cameras WHERE camera_id = ?",
            (body.camera_id,),
        )
        if cam_count and cam_count["cnt"] >= 2:
            raise HTTPException(status_code=400, detail="Camera already assigned to 2 positions")

        try:
            await controller.db.execute(
                "INSERT INTO position_cameras (position_id, camera_id) VALUES (?, ?)",
                (position_id, body.camera_id),
            )
            await controller.db.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="Camera already assigned to this position")

        logger.info(f"Camera {body.camera_id} assigned to position {position_id}")
        return {"position_id": position_id, "camera_id": body.camera_id}

    @app.delete(
        "/api/positions/{position_id}/cameras/{camera_id}",
        tags=[TAG_POSITION],
        summary="Remove camera from position",
        status_code=204,
    )
    async def remove_camera(position_id: int, camera_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        await controller.db.execute(
            "DELETE FROM position_cameras WHERE position_id = ? AND camera_id = ?",
            (position_id, camera_id),
        )
        await controller.db.commit()

    @app.get(
        "/api/positions/{position_id}/cameras",
        response_model=list[CameraResponse],
        tags=[TAG_POSITION],
        summary="List cameras for a position",
    )
    async def list_position_cameras(position_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        rows = await controller.db.fetchall(
            """SELECT c.* FROM cameras c
               JOIN position_cameras pc ON pc.camera_id = c.id
               WHERE pc.position_id = ?""",
            (position_id,),
        )
        live_usb = set(await controller.camera_scanner.get_available_usb())
        return [
            _row_to_camera(r, online=(
                r["device_index"] in live_usb if r["source_type"] == "webcam"
                else await controller.camera_scanner._check_rtsp(r["rtsp_url"], 2) if r["rtsp_url"]
                else False
            ))
            for r in rows
        ]

    # ---------------------------------------------------- Position UX/TX
    @app.post(
        "/api/positions/{position_id}/uxtx",
        tags=[TAG_POSITION],
        summary="Assign UX/TX or GPIO to position",
        status_code=201,
    )
    async def assign_uxtx(position_id: int, body: UXAssign):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        pos = await controller.db.fetchone(
            "SELECT id FROM positions WHERE id = ?", (position_id,)
        )
        if not pos:
            raise HTTPException(status_code=404, detail="Position not found")

        await controller.db.execute(
            "DELETE FROM position_uxtx WHERE position_id = ?", (position_id,)
        )

        if body.device_type == "gpio" and body.gpio_pin is not None:
            await controller.db.execute(
                "INSERT INTO position_uxtx (position_id, device_type, gpio_pin) VALUES (?, ?, ?)",
                (position_id, body.device_type, body.gpio_pin),
            )
            if controller.uxtx:
                controller.uxtx.remove_gpio_monitor(position_id)
                controller.uxtx.add_gpio_monitor(position_id, body.gpio_pin)
                controller.uxtx.start_all()
        elif body.device_type == "uxtx" and body.uxtx_id:
            await controller.db.execute(
                "INSERT INTO position_uxtx (position_id, device_type, uxtx_id) VALUES (?, ?, ?)",
                (position_id, body.device_type, body.uxtx_id),
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid UX/TX configuration")

        await controller.db.commit()
        logger.info(f"UX/TX assigned to position {position_id}: {body.device_type}")
        return {"position_id": position_id, **body.model_dump()}

    @app.delete(
        "/api/positions/{position_id}/uxtx",
        tags=[TAG_POSITION],
        summary="Remove UX/TX from position",
        status_code=204,
    )
    async def remove_uxtx(position_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        if controller.uxtx:
            controller.uxtx.remove_gpio_monitor(position_id)
        await controller.db.execute(
            "DELETE FROM position_uxtx WHERE position_id = ?", (position_id,)
        )
        await controller.db.commit()

    @app.get(
        "/api/positions/{position_id}/uxtx",
        response_model=UXDeviceResponse,
        tags=[TAG_POSITION],
        summary="Get UX/TX for position",
    )
    async def get_uxtx(position_id: int):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        ux = await controller.db.fetchone(
            "SELECT * FROM position_uxtx WHERE position_id = ?", (position_id,)
        )
        if not ux:
            return UXDeviceResponse()
        return UXDeviceResponse(
            device_type=ux["device_type"],
            gpio_pin=ux["gpio_pin"],
            uxtx_id=ux["uxtx_id"],
        )

    # ------------------------------------------------------------- Camera Scan
    @app.get(
        "/api/cameras/scan",
        response_model=ScanResponse,
        tags=[TAG_CAMERA],
        summary="Scan for available webcams and IP cameras",
    )
    async def scan_cameras(subnet: str | None = Query(None, description="Subnet to scan, e.g. 192.168.1.0/24")):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        webcams = await controller.camera_scanner.scan_webcams()
        ip_cams = await controller.camera_scanner.scan_network(subnet)
        return ScanResponse(webcams=webcams, ip_cameras=ip_cams)

    # ---------------------------------------------------------- Camera Stream
    @app.get(
        "/api/cameras/{camera_id}/stream",
        tags=[TAG_STREAM],
        summary="MJPEG stream from a specific camera",
    )
    async def camera_stream(camera_id: int):
        if not controller or not controller.camera_pool:
            raise HTTPException(status_code=503, detail="Camera pool not initialized")

        await _ensure_camera_active(camera_id, controller)

        async def generate_mjpeg():
            boundary = "frame"
            while True:
                jpeg = controller.camera_pool.get_latest_jpeg(camera_id)
                if jpeg:
                    yield (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode() + jpeg + b"\r\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(
            generate_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get(
        "/api/cameras/{camera_id}/capture",
        tags=[TAG_STREAM],
        summary="Capture a single frame from a camera",
    )
    async def capture_frame(camera_id: int):
        if not controller or not controller.camera_pool:
            raise HTTPException(status_code=503, detail="Camera pool not initialized")

        await _ensure_camera_active(camera_id, controller)
        jpeg = controller.camera_pool.get_latest_jpeg(camera_id)
        if jpeg is None:
            raise HTTPException(status_code=503, detail="Failed to capture frame")
        return Response(content=jpeg, media_type="image/jpeg")

    # ---------------------------------------------------- Legacy stream aliases
    @app.get(
        "/camera/stream",
        tags=[TAG_STREAM],
        summary="[Legacy] MJPEG stream from first available camera",
    )
    async def legacy_camera_stream():
        if not controller or not controller.camera_pool:
            raise HTTPException(status_code=503, detail="Camera not available")
        active = controller.camera_pool.list_active()
        if not active:
            raise HTTPException(status_code=503, detail="No active cameras")
        camera_id = active[0]

        async def generate_mjpeg():
            boundary = "frame"
            while True:
                jpeg = controller.camera_pool.get_latest_jpeg(camera_id)
                if jpeg:
                    yield (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode() + jpeg + b"\r\n"
                await asyncio.sleep(0.03)

        return StreamingResponse(
            generate_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get(
        "/camera/capture",
        tags=[TAG_STREAM],
        summary="[Legacy] Capture from first available camera",
    )
    async def legacy_capture():
        if not controller or not controller.camera_pool:
            raise HTTPException(status_code=503, detail="Camera not available")
        active = controller.camera_pool.list_active()
        if not active:
            raise HTTPException(status_code=503, detail="No active cameras")
        jpeg = controller.camera_pool.get_latest_jpeg(active[0])
        if jpeg is None:
            raise HTTPException(status_code=503, detail="Failed to capture frame")
        return Response(content=jpeg, media_type="image/jpeg")

    # -------------------------------------------------------- WebRTC (IP Camera)
    @app.post(
        "/api/cameras/{camera_id}/webrtc",
        response_model=WebRTCAnswerResponse,
        tags=[TAG_STREAM],
        summary="WebRTC offer/answer for IP camera",
    )
    async def webrtc_offer(camera_id: int, body: WebRTCOfferRequest):
        if not controller or not controller.camera_pool:
            raise HTTPException(status_code=503, detail="Camera pool not initialized")

        cam_row = await controller.db.fetchone(
            "SELECT source_type FROM cameras WHERE id = ?", (camera_id,)
        )
        if not cam_row:
            raise HTTPException(status_code=404, detail="Camera not found")

        if not controller.webrtc or not controller.webrtc.available:
            raise HTTPException(status_code=501, detail="WebRTC not available (aiortc not installed)")

        await _ensure_camera_active(camera_id, controller)

        def _get_frame():
            return controller.camera_pool.get_latest_jpeg(camera_id)

        result = await controller.webrtc.create_answer(
            body.sdp, _get_frame, camera_id
        )
        if result is None:
            raise HTTPException(status_code=500, detail="WebRTC negotiation failed")
        return result

    # ------------------------------------------------------------- Recording
    @app.post(
        "/api/positions/{position_id}/recording/start",
        response_model=RecordingStartResponse,
        tags=[TAG_RECORDING],
        summary="Start recording for a position",
    )
    async def start_recording(position_id: int):
        if not controller or not controller.recorder:
            raise HTTPException(status_code=503, detail="Recorder not initialized")

        ok = await controller.recorder.start_recording(position_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to start recording (no cameras or already recording)")
        return RecordingStartResponse(position_id=position_id)

    @app.post(
        "/api/positions/{position_id}/recording/stop",
        response_model=RecordingStopResponse,
        tags=[TAG_RECORDING],
        summary="Stop recording for a position",
    )
    async def stop_recording(position_id: int):
        if not controller or not controller.recorder:
            raise HTTPException(status_code=503, detail="Recorder not initialized")
        result = await controller.recorder.stop_recording(position_id)
        if result is None:
            raise HTTPException(status_code=400, detail="Position is not recording")
        return RecordingStopResponse(
            position_id=position_id,
            duration_seconds=result.get("duration_seconds"),
        )

    @app.get(
        "/api/positions/{position_id}/recording/status",
        response_model=RecordingStatusResponse,
        tags=[TAG_RECORDING],
        summary="Get recording status for a position",
    )
    async def get_recording_status(position_id: int):
        if not controller or not controller.recorder:
            raise HTTPException(status_code=503, detail="Recorder not initialized")
        status = await controller.recorder.get_recording_status(position_id)
        return RecordingStatusResponse(position_id=position_id, **status)

    # ------------------------------------------------------------------ MQTT
    @app.post(
        "/mqtt/publish",
        tags=[TAG_MQTT],
        summary="Publish to an MQTT topic",
    )
    async def mqtt_publish(
        topic: str = Query(..., description="MQTT topic"),
        body: dict = Body(default_factory=dict),
    ):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        controller.mqtt.publish(topic, body)
        return {"topic": topic, "status": "published"}

    # ------------------------------------------------------------ Lifespan
    @app.on_event("startup")
    async def startup():
        pass

    @app.on_event("shutdown")
    async def shutdown():
        pass

    return app


async def _ensure_camera_active(camera_id: int, controller) -> None:
    """Start a camera in the pool if it's registered but not active."""
    inst = controller.camera_pool.get_instance(camera_id)
    if inst is None:
        row = await controller.db.fetchone(
            "SELECT * FROM cameras WHERE id = ?", (camera_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Camera not found")
        await controller.camera_pool.register_instance(
            camera_id=row["id"],
            source_type=row["source_type"],
            device_index=row["device_index"],
            rtsp_url=row["rtsp_url"],
            width=row["width"],
            height=row["height"],
            fps=row["fps"],
        )
        inst = controller.camera_pool.get_instance(camera_id)

    if inst and not inst.is_running:
        ok = await controller.camera_pool.start_camera(camera_id)
        if not ok:
            raise HTTPException(status_code=503, detail="Failed to start camera")
