from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
from loguru import logger

from config.settings import AppConfig
from services.system_stats import SystemStats


class MQTTClient:
    def __init__(self, config: AppConfig, stats: SystemStats | None = None) -> None:
        mqtt_cfg = config.mqtt
        self._stats = stats
        self._broker = mqtt_cfg.broker
        self._port = mqtt_cfg.port
        self._username = mqtt_cfg.username
        self._password = mqtt_cfg.password
        self._client_id = mqtt_cfg.client_id
        self._topics = mqtt_cfg.topics
        self._keepalive = mqtt_cfg.keepalive
        self._reconnect_delay = mqtt_cfg.reconnect_delay

        self._client = mqtt.Client(
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._message_handlers: dict[str, list[Callable[[str, dict], None]]] = {}

    def on_topic(self, topic: str, callback: Callable[[str, dict], None]) -> None:
        if topic not in self._message_handlers:
            self._message_handlers[topic] = []
        self._message_handlers[topic].append(callback)

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected()

    async def wait_until_connected(self, timeout: int = 10) -> bool:
        start = time.time()
        while not self.is_connected:
            if time.time() - start > timeout:
                logger.error(f"MQTT not connected after {timeout}s")
                return False
            await asyncio.sleep(0.2)
        logger.info("MQTT connection ready")
        return True

    def connect(self) -> None:
        if self._username:
            self._client.username_pw_set(self._username, self._password)

        self._client.reconnect_delay_set(min_delay=1, max_delay=self._reconnect_delay)

        logger.info(f"MQTT connecting to {self._broker}:{self._port}")
        try:
            self._client.connect(self._broker, self._port, self._keepalive)
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")

    def loop_start(self) -> None:
        self._client.loop_start()

    def loop_stop(self) -> None:
        self._client.loop_stop()

    def disconnect(self) -> None:
        self._client.disconnect()
        logger.info("MQTT disconnected")

    _RC_MSGS: dict[int, str] = {
        0: "Success",
        1: "Out of memory",
        2: "Protocol error",
        3: "Invalid parameter",
        4: "Not connected",
        5: "Connection refused",
        6: "Not found",
        7: "Connection lost",
        8: "TLS error",
        9: "Payload too large",
        10: "Not supported",
        11: "Authentication failed",
        12: "ACL denied",
        13: "Unknown error",
        14: "Errno error",
        15: "Queue full",
    }

    def publish(self, topic: str, payload: dict[str, Any] | str, qos: int = 1) -> None:
        if not self.is_connected:
            logger.warning(f"MQTT not connected, dropping publish to {topic}")
            return

        if isinstance(payload, dict):
            payload = json.dumps(payload, default=str)

        result = self._client.publish(topic, payload, qos=qos)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"MQTT published -> {topic}")
        else:
            logger.error(f"MQTT publish failed: {self._RC_MSGS.get(result.rc, 'Unknown')} (rc={result.rc})")

    def subscribe(self, topic: str, qos: int = 1) -> None:
        self._client.subscribe(topic, qos=qos)
        logger.info(f"MQTT subscribed: {topic}")

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            logger.info("MQTT connected to EMQX broker")
            self.subscribe(self._topics.commands)
            payload = self._stats.get_status_payload() if self._stats else {"status": "online", "ts": time.time()}
            self.publish(self._topics.status, payload)
        else:
            rc_map = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }
            logger.error(f"MQTT connection failed (rc={rc}): {rc_map.get(rc, f'Unknown error {rc}')}")

    def _on_disconnect(self, client, userdata, rc) -> None:
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly (rc={rc}), will reconnect")
        else:
            logger.info("MQTT disconnected")

    def _on_message(self, client, userdata, msg) -> None:
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8")
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = {"raw": payload_str}

        logger.debug(f"MQTT received: {topic} -> {payload}")

        for handler_topic, handlers in self._message_handlers.items():
            if mqtt.topic_matches_sub(handler_topic, topic):
                for handler in handlers:
                    handler(topic, payload)
