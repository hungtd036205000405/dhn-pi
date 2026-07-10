import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from config.settings import AppConfig
from core.database import Database
from drivers.gpio import GPIODeviceManager
from drivers.camera import CameraManager
from drivers.sensors import SensorManager
from services.mqtt_client import MQTTClient
from services.web_server import create_app
from services.scheduler import SchedulerService


class Controller:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config)
        self.gpio = GPIODeviceManager(config)
        self.sensors = SensorManager(config)
        self.camera = CameraManager(config)
        self.mqtt = MQTTClient(config)
        self.scheduler = SchedulerService(config, self.mqtt, self.sensors)
        self._web_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._on_sensor_data: list[Callable[[str, dict], Coroutine]] = []

    def on_sensor_data(self, callback: Callable[[str, dict], Coroutine]) -> None:
        self._on_sensor_data.append(callback)

    async def _publish_sensor_data(self, topic: str, payload: dict) -> None:
        for cb in self._on_sensor_data:
            await cb(topic, payload)

    async def start(self) -> None:
        logger.info("Starting DHN-Pi controller...")

        await self.db.connect()
        await self.db.initialize()

        self.gpio.initialize()
        self.camera.initialize()

        self.sensors.set_sensor_callback(self._publish_sensor_data)

        self.mqtt.connect()
        self.mqtt.loop_start()

        self.scheduler.start(event_loop=asyncio.get_event_loop())

        app = create_app(self.config, self)
        import uvicorn

        reload = self.config.web.reload
        is_dev = self.config.app_env == "development"

        if reload and not is_dev:
            logger.warning("reload=True is intended for development; set app_env=development")

        server_config = uvicorn.Config(
            app,
            host=self.config.web.host,
            port=self.config.web.port,
            log_level="info",
            reload=reload,
        )
        server = uvicorn.Server(server_config)
        self._web_task = asyncio.create_task(server.serve())

        logger.info(f"Web server running at http://{self.config.web.host}:{self.config.web.port}")
        if self.config.web.swagger_enabled:
            logger.info(f"Swagger UI  → http://{self.config.web.host}:{self.config.web.port}/docs")
            logger.info(f"OpenAPI JSON → http://{self.config.web.host}:{self.config.web.port}/openapi.json")

    async def stop(self) -> None:
        logger.info("Shutting down DHN-Pi controller...")

        if self._web_task:
            self._web_task.cancel()
            try:
                await self._web_task
            except asyncio.CancelledError:
                pass

        self.scheduler.stop()
        self.mqtt.loop_stop()
        self.mqtt.disconnect()
        self.camera.release()
        self.gpio.cleanup()
        await self.db.disconnect()

        self._shutdown_event.set()
        logger.info("Shutdown complete")

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()
