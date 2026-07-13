from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Path as FastAPIPath, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from loguru import logger
from pydantic import BaseModel, Field

from config.settings import AppConfig

TAG_SYSTEM = "System"
TAG_GPIO = "GPIO"
TAG_SENSORS = "Sensors"
TAG_CAMERA = "Camera"
TAG_MQTT = "MQTT"

_tags_metadata = [
    {"name": TAG_SYSTEM, "description": "Health check and system status endpoints."},
    {"name": TAG_GPIO, "description": "Manage GPIO devices — list and set output states."},
    {"name": TAG_SENSORS, "description": "Read data from connected sensor devices."},
    {"name": TAG_CAMERA, "description": "Camera capture and MJPEG live-stream endpoints."},
    {"name": TAG_MQTT, "description": "Publish messages to the MQTT broker."},
]


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    ts: float = Field(..., description="Unix timestamp of the health check.")
    camera: bool = Field(..., description="Whether the camera capture loop is running.")


class GPIODeviceItem(BaseModel):
    name: str
    type: str
    pin: int


class GPIOListResponse(BaseModel):
    devices: list[GPIODeviceItem]


class GPIOSetResponse(BaseModel):
    device: str
    state: bool


class SensorReading(BaseModel):
    type: str
    value: float | None = Field(default=None, description="Numeric reading if applicable.")
    status: str
    error: str | None = Field(default=None)


class SensorListResponse(BaseModel):
    sensors: dict[str, SensorReading]


class MQTTPublishRequest(BaseModel):
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON payload to publish to the MQTT topic.",
    )


class MQTTPublishResponse(BaseModel):
    topic: str
    status: str = "published"


class ErrorResponse(BaseModel):
    detail: str


def create_app(config: AppConfig, controller=None) -> FastAPI:
    from core.controller import Controller

    app = FastAPI(
        title="DHN-Pi",
        version="0.1.0",
        description="REST API for the DHN-Pi IoT edge controller — GPIO, sensors, camera, and MQTT.",
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
        description="Returns the current status of the service, including camera state.",
        responses={503: {"model": ErrorResponse}},
    )
    async def health():
        if controller is None:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        return {
            "status": "ok",
            "ts": time.time(),
            "camera": controller.camera.is_running,
        }

    # ------------------------------------------------------------------- GPIO
    @app.get(
        "/gpio",
        response_model=GPIOListResponse,
        tags=[TAG_GPIO],
        summary="List GPIO devices",
        description="Returns all configured GPIO devices with their name, type, and pin number.",
        responses={503: {"model": ErrorResponse}},
    )
    async def list_gpio():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        return {"devices": controller.gpio.list_devices()}

    @app.post(
        "/gpio/{name}",
        response_model=GPIOSetResponse,
        tags=[TAG_GPIO],
        summary="Set GPIO output state",
        description="Turn a configured GPIO output device **on** or **off** by name.",
        responses={
            200: {"description": "Device state updated."},
            404: {"description": "Device not found or not writable."},
            503: {"model": ErrorResponse},
        },
    )
    async def set_gpio(
        name: str = FastAPIPath(
            ...,
            description="Name of the GPIO device configured in config.yaml.",
            examples=["led_1", "relay_1"],
        ),
        state: bool = Query(
            ...,
            description="Target state — `true` for on, `false` for off.",
            examples=[True, False],
        ),
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
        response_model=SensorListResponse,
        tags=[TAG_SENSORS],
        summary="Read all sensors",
        description="Triggers a live read of every configured sensor and returns the latest values.",
        responses={503: {"model": ErrorResponse}},
    )
    async def read_sensors():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        data = await controller.sensors.read_all()
        return {"sensors": data}

    # ---------------------------------------------------------------- Camera
    @app.get(
        "/camera/stream",
        tags=[TAG_CAMERA],
        summary="MJPEG camera stream",
        description="Returns an **MJPEG** (Motion JPEG) live stream from the configured camera device.",
        responses={
            200: {
                "content": {"multipart/x-mixed-replace": {}},
                "description": "Live MJPEG stream.",
            },
            503: {"model": ErrorResponse},
        },
    )
    async def camera_stream():
        if not controller or not controller.camera.is_running:
            raise HTTPException(status_code=503, detail="Camera not available")

        async def generate_mjpeg():
            boundary = "frame"
            while True:
                jpeg = controller.camera.get_latest_jpeg()
                if jpeg:
                    yield (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode() + jpeg + b"\r\n"
                await asyncio.sleep(0.03)

        return StreamingResponse(
            generate_mjpeg(),
            media_type=f"multipart/x-mixed-replace; boundary=frame",
        )

    @app.get(
        "/camera/capture",
        tags=[TAG_CAMERA],
        summary="Capture a single image",
        description="Captures a single JPEG frame from the camera and returns it as an image.",
        responses={
            200: {
                "content": {"image/jpeg": {}},
                "description": "A single JPEG image frame.",
            },
            503: {"model": ErrorResponse},
        },
    )
    async def capture_image():
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        jpeg = controller.camera.encode_frame()
        if jpeg is None:
            raise HTTPException(status_code=503, detail="Failed to capture frame")
        return Response(content=jpeg, media_type="image/jpeg")

    # ------------------------------------------------------------------ MQTT
    @app.post(
        "/mqtt/publish",
        response_model=MQTTPublishResponse,
        tags=[TAG_MQTT],
        summary="Publish to an MQTT topic",
        description="Publishes a JSON payload to the specified MQTT topic.",
        responses={503: {"model": ErrorResponse}},
    )
    async def mqtt_publish(
        topic: str = Query(
            ...,
            description="MQTT topic to publish to.",
            examples=["pi/{device_code}/commands"],
        ),
        body: MQTTPublishRequest = Body(...),
    ):
        if not controller:
            raise HTTPException(status_code=503, detail="Controller not initialized")
        controller.mqtt.publish(topic, body.payload)
        return {"topic": topic, "status": "published"}

    # ------------------------------------------------------------ Lifespan
    @app.on_event("startup")
    async def startup():
        if controller and controller.camera._cap:
            asyncio.create_task(controller.camera.start_capture_loop())

    @app.on_event("shutdown")
    async def shutdown():
        pass

    return app
