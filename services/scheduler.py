from __future__ import annotations

import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import AppConfig
from services.system_stats import SystemStats


class SchedulerService:
    def __init__(self, config: AppConfig, mqtt_client, sensor_manager, stats: SystemStats | None = None) -> None:
        self._config = config
        self._mqtt = mqtt_client
        self._sensors = sensor_manager
        self._stats = stats
        self._scheduler: AsyncIOScheduler | None = None

    def start(self, event_loop=None) -> None:
        interval = self._config.scheduler.sensor_poll_interval
        heartbeat_interval = self._config.scheduler.heartbeat_interval

        self._scheduler = AsyncIOScheduler(event_loop=event_loop)

        self._scheduler.add_job(
            self._poll_sensors,
            "interval",
            seconds=interval,
            id="poll_sensors",
            replace_existing=True,
        )

        self._scheduler.add_job(
            self._send_heartbeat,
            "interval",
            seconds=heartbeat_interval,
            id="send_heartbeat",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            f"Scheduler started: sensor_poll={interval}s, heartbeat={heartbeat_interval}s"
        )

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def _poll_sensors(self) -> None:
        try:
            data = await self._sensors.read_all()
            payload = {"ts": time.time(), "sensors": data}
            self._mqtt.publish(self._config.mqtt.topics.sensors, payload)
        except Exception as e:
            logger.error(f"Scheduler sensor poll error: {e}")

    async def _send_heartbeat(self) -> None:
        try:
            payload = self._stats.get_status_payload(extra={"type": "heartbeat"}) if self._stats else {"status": "online", "ts": time.time(), "type": "heartbeat"}
            self._mqtt.publish(self._config.mqtt.topics.status, payload)
        except Exception as e:
            logger.error(f"Scheduler heartbeat error: {e}")
