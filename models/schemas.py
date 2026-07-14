from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UXDeviceResponse(BaseModel):
    device_type: str | None = None
    gpio_pin: int | None = None
    uxtx_id: str | None = None


class CameraResponse(BaseModel):
    id: int
    name: str
    source_type: str
    device_index: int | None = None
    rtsp_url: str | None = None
    width: int
    height: int
    fps: int
    enabled: bool
    created_at: str
    updated_at: str


class PositionResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    recording: bool = False
    recording_started_at: float | None = None
    created_at: str
    updated_at: str


class PositionDetailResponse(PositionResponse):
    cameras: list[CameraResponse] = []
    uxtx: UXDeviceResponse | None = None


class PositionCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None


class PositionUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = None


class CameraCreate(BaseModel):
    name: str = Field(..., max_length=255)
    source_type: Literal["webcam", "ip"]
    device_index: int | None = None
    rtsp_url: str | None = None
    width: int = 640
    height: int = 480
    fps: int = 15


class CameraUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    source_type: Literal["webcam", "ip"] | None = None
    device_index: int | None = None
    rtsp_url: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    enabled: bool | None = None


class PositionCameraAssign(BaseModel):
    camera_id: int


class UXAssign(BaseModel):
    device_type: Literal["gpio", "uxtx"]
    gpio_pin: int | None = None
    uxtx_id: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    ts: float = Field(..., description="Unix timestamp")
    device_code: str
    hostname: str
    ip: str
    camera_count: int = 0
    recording_count: int = 0
    cpu_usage: float = 0
    memory_usage_mb: float = 0
    disk_free_gb: float = 0


class WebCamScanResult(BaseModel):
    index: int
    name: str
    available: bool


class IPCamScanResult(BaseModel):
    ip: str
    port: int
    rtsp_url: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class ScanResponse(BaseModel):
    webcams: list[WebCamScanResult] = []
    ip_cameras: list[IPCamScanResult] = []


class RecordingStatusResponse(BaseModel):
    position_id: int
    recording: bool
    started_at: float | None = None
    cameras: list[dict] = []


class RecordingStartResponse(BaseModel):
    position_id: int
    recording: bool = True
    message: str = "Recording started"


class RecordingStopResponse(BaseModel):
    position_id: int
    recording: bool = False
    message: str = "Recording stopped"
    duration_seconds: float | None = None


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str = "offer"


class WebRTCAnswerResponse(BaseModel):
    sdp: str
    type: str = "answer"
