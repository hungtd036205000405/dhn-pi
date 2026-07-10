from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger


class SensorManager:
    def __init__(self, config) -> None:
        self._config = config
        self._on_data: list[
            Callable[[str, dict[str, Any]], Coroutine]
        ] = []

    def set_sensor_callback(
        self, callback: Callable[[str, dict[str, Any]], Coroutine] | None
    ) -> None:
        if callback:
            self._on_data.append(callback)

    async def read_all(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for device_cfg in self._config.sensors.devices:
            name = device_cfg.name
            sensor_type = device_cfg.type

            if sensor_type == "DHT22":
                results[name] = await self._read_dht22(device_cfg)
            elif sensor_type == "BME280":
                results[name] = await self._read_bme280(device_cfg)
            else:
                logger.warning(f"Unknown sensor type: {sensor_type}")

        return results

    async def read_and_publish(self) -> None:
        data = await self.read_all()
        for sensor_name, values in data.items():
            if values:
                for cb in self._on_data:
                    await cb(f"dhn-pi/sensors", {
                        "sensor": sensor_name,
                        "ts": asyncio.get_event_loop().time(),
                        "values": values,
                    })

    async def _read_dht22(self, cfg) -> dict[str, Any]:
        try:
            import adafruit_dht
            import board

            dht = adafruit_dht.DHT22(getattr(board, f"D{cfg.pin}"))
            temp = dht.temperature
            humidity = dht.humidity
            dht.exit()
            return {"temperature": temp, "humidity": humidity}
        except Exception as e:
            logger.error(f"DHT22 read error ({cfg.name}): {e}")
            return {}

    async def _read_bme280(self, cfg) -> dict[str, Any]:
        try:
            import smbus2

            bus = smbus2.SMBus(1)
            addr = int(cfg.i2c_address, 16) if cfg.i2c_address else 0x76
            bus.close()
            return {"address": hex(addr), "note": "BME280 init stub - implement full read"}
        except Exception as e:
            logger.error(f"BME280 read error ({cfg.name}): {e}")
            return {}

    def stop(self) -> None:
        logger.info("Sensor manager stopped")
