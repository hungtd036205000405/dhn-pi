import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
CONFIG_YAML_PATH = PROJECT_ROOT / "config.yaml"


class GPIODeviceConfig(BaseModel):
    name: str
    type: str
    pin: int
    pull_up: bool | None = None
    active_high: bool | None = True


class SensorDeviceConfig(BaseModel):
    name: str
    type: str
    pin: int | None = None
    i2c_address: str | None = None


class GPIOConfig(BaseModel):
    devices: list[GPIODeviceConfig] = Field(default_factory=list)


class SensorConfig(BaseModel):
    read_interval: int = 5
    devices: list[SensorDeviceConfig] = Field(default_factory=list)


class CameraConfig(BaseModel):
    enabled: bool = True
    device_index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30


class MQTTTopics(BaseModel):
    sensors: str = "pi/{device_code}/sensors"
    commands: str = "pi/{device_code}/commands"
    status: str = "pi/{device_code}/status"

    def model_post_init(self, __context):
        device_code = os.getenv("DEVICE_CODE", "")
        if not device_code:
            raise ValueError("DEVICE_CODE environment variable is required")
        for field in ("sensors", "commands", "status"):
            val = getattr(self, field)
            if "{device_code}" in val:
                setattr(self, field, val.format(device_code=device_code))


class MQTTConfig(BaseModel):
    broker: str = Field(default="localhost", alias="MQTT_BROKER")
    port: int = Field(default=1883, alias="MQTT_PORT")
    username: str | None = Field(default=None, alias="MQTT_USERNAME")
    password: str | None = Field(default=None, alias="MQTT_PASSWORD")
    client_id: str = Field(default="dhn-pi", alias="MQTT_CLIENT_ID")
    reconnect_delay: int = 5
    keepalive: int = 60
    topics: MQTTTopics = Field(default_factory=MQTTTopics)


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    swagger_enabled: bool = True


class SchedulerConfig(BaseModel):
    sensor_poll_interval: int = 5
    heartbeat_interval: int = 30


class AppConfig(BaseModel):
    gpio: GPIOConfig = Field(default_factory=GPIOConfig)
    sensors: SensorConfig = Field(default_factory=SensorConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    database_url: str = Field(default="sqlite:///dhn_pi.db", alias="DATABASE_URL")
    log_level: str = Field(default="DEBUG", alias="LOG_LEVEL")
    app_env: str = Field(default="development", alias="APP_ENV")
    device_code: str = Field(default="PI-001", alias="DEVICE_CODE")
    version: str = Field(default="0.0.1", alias="VERSION")


def load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_YAML_PATH
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_config() -> AppConfig:
    yaml_data = load_yaml_config()

    mqtt_yaml = yaml_data.get("mqtt", {})
    mqtt_config = {
        "MQTT_BROKER": os.getenv("MQTT_BROKER", mqtt_yaml.get("broker", "localhost")),
        "MQTT_PORT": int(os.getenv("MQTT_PORT", str(mqtt_yaml.get("port", 1883)))),
        "MQTT_USERNAME": os.getenv("MQTT_USERNAME") or mqtt_yaml.get("username"),
        "MQTT_PASSWORD": os.getenv("MQTT_PASSWORD") or mqtt_yaml.get("password"),
        "MQTT_CLIENT_ID": os.getenv("MQTT_CLIENT_ID", mqtt_yaml.get("client_id", "dhn-pi")),
        "reconnect_delay": mqtt_yaml.get("reconnect_delay", 5),
        "keepalive": mqtt_yaml.get("keepalive", 60),
    }
    if "topics" in mqtt_yaml:
        mqtt_config["topics"] = mqtt_yaml["topics"]
    mqtt_data = {
        "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///dhn_pi.db"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "DEBUG"),
        "APP_ENV": os.getenv("APP_ENV", yaml_data.get("web", {}).get("app_env", "development")),
        "DEVICE_CODE": os.getenv("DEVICE_CODE", yaml_data.get("device_code", "PI-001")),
        "VERSION": os.getenv("VERSION", yaml_data.get("version", "0.0.1")),
        "gpio": yaml_data.get("gpio", {}),
        "sensors": yaml_data.get("sensors", {}),
        "camera": yaml_data.get("camera", {}),
        "mqtt": mqtt_config,

        "web": yaml_data.get("web", {}),
        "scheduler": yaml_data.get("scheduler", {}),
    }

    return AppConfig(**mqtt_data)
