import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from config.settings import AppConfig
from core.database import Database
from drivers.gpio import GPIODeviceManager
from drivers.camera_pool import CameraPool
from drivers.recorder import Recorder
from drivers.uxtx import UXManager
from drivers.webrtc_streamer import WebRTCStreamer
from drivers.sensors import SensorManager
from services.mqtt_client import MQTTClient
from services.system_stats import SystemStats
from services.web_server import create_app
from services.camera_scanner import CameraScanner
from services.scheduler import SchedulerService


class Controller:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config)
        self.gpio = GPIODeviceManager(config)
        self.sensors = SensorManager(config)
        self.stats = SystemStats(config)
        self.mqtt = MQTTClient(config, stats=self.stats)
        self.scheduler = SchedulerService(config, self.mqtt, self.sensors, stats=self.stats)

        self.camera_pool = CameraPool(config)
        self.recorder = Recorder(config, self.db, self.camera_pool)
        self.uxtx = UXManager(config, on_recording_trigger=self._on_uxtx_trigger)
        self.webrtc = WebRTCStreamer()
        self.camera_scanner = CameraScanner(config)

        self._web_task: asyncio.Task | None = None
        self._server: Any = None
        self._shutdown_event = asyncio.Event()
        self._on_sensor_data: list[Callable[[str, dict], Coroutine]] = []

    def on_sensor_data(self, callback: Callable[[str, dict], Coroutine]) -> None:
        self._on_sensor_data.append(callback)

    async def _publish_sensor_data(self, topic: str, payload: dict) -> None:
        for cb in self._on_sensor_data:
            await cb(topic, payload)

    async def _on_uxtx_trigger(self, position_id: int) -> None:
        """Toggle recording when UX/TX or GPIO triggers."""
        status = await self.recorder.get_recording_status(position_id)
        if status.get("recording"):
            logger.info(f"UX/TX trigger: stopping recording for position {position_id}")
            result = await self.recorder.stop_recording(position_id)
            if result:
                self.mqtt.publish(
                    f"pi/{self.config.device_code}/recording",
                    {"position_id": position_id, "event": "stopped", **result},
                )
        else:
            logger.info(f"UX/TX trigger: starting recording for position {position_id}")
            ok = await self.recorder.start_recording(position_id)
            self.mqtt.publish(
                f"pi/{self.config.device_code}/recording",
                {"position_id": position_id, "event": "started" if ok else "failed"},
            )

    async def start(self) -> None:
        logger.info("Starting DHN-Pi controller...")

        await self.db.connect()
        await self.db.initialize()

        self.gpio.initialize()

        self.sensors.set_sensor_callback(self._publish_sensor_data)

        # Register cameras from database into camera_pool
        await self._load_cameras()

        self.mqtt.connect()
        self.mqtt.loop_start()

        if await self.mqtt.wait_until_connected(timeout=10):
            self.scheduler.start(event_loop=asyncio.get_event_loop())
        else:
            logger.warning("MQTT not connected, scheduler not started")

        # Load UX/TX configs for positions
        await self._load_uxtx()

        self.uxtx.set_trigger_callback(self._on_uxtx_trigger)
        self.uxtx.start_all()

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
        self._server = uvicorn.Server(server_config)
        self._web_task = asyncio.create_task(self._server.serve())

        logger.info(f"Web server running at http://{self.config.web.host}:{self.config.web.port}")
        if self.config.web.swagger_enabled:
            logger.info(f"Swagger UI  → http://{self.config.web.host}:{self.config.web.port}/docs")

    async def _load_cameras(self) -> None:
        try:
            rows = await self.db.fetchall("SELECT * FROM cameras WHERE enabled = 1")
            for row in rows:
                await self.camera_pool.register_instance(
                    camera_id=row["id"],
                    source_type=row["source_type"],
                    device_index=row["device_index"],
                    rtsp_url=row["rtsp_url"],
                    width=row["width"],
                    height=row["height"],
                    fps=row["fps"],
                )
            logger.info(f"Loaded {len(rows)} camera(s) from database")
        except Exception as e:
            logger.warning(f"Could not load cameras from DB: {e}")

    async def _load_uxtx(self) -> None:
        try:
            rows = await self.db.fetchall(
                """SELECT pu.*, p.id as pid FROM position_uxtx pu
                   JOIN positions p ON p.id = pu.position_id"""
            )
            for row in rows:
                if row["device_type"] == "gpio" and row["gpio_pin"] is not None:
                    self.uxtx.add_gpio_monitor(row["position_id"], row["gpio_pin"])
                    logger.info(
                        f"Loaded GPIO monitor: position {row['position_id']} on pin {row['gpio_pin']}"
                    )
        except Exception as e:
            logger.warning(f"Could not load UX/TX configs: {e}")

    async def stop(self) -> None:
        logger.info("Shutting down DHN-Pi controller...")

        if self._web_task and self._server:
            self._server.should_exit = True
            try:
                await asyncio.wait_for(self._web_task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._web_task.cancel()
                try:
                    await self._web_task
                except asyncio.CancelledError:
                    pass

        if self.webrtc:
            await self.webrtc.stop_all()
        if self.recorder:
            await self.recorder.stop_all()
        if self.camera_pool:
            await self.camera_pool.stop_all()
        if self.uxtx:
            self.uxtx.stop_all()

        self.scheduler.stop()
        self.mqtt.loop_stop()
        self.mqtt.disconnect()
        self.gpio.cleanup()
        await self.db.disconnect()

        self._shutdown_event.set()
        logger.info("Shutdown complete")

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()
