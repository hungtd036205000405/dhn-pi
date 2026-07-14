from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from loguru import logger

from config.settings import AppConfig

try:
    from gpiozero import Button
    _HAS_GPIOZERO = True
except ImportError:
    Button = None
    _HAS_GPIOZERO = False


class GPIOMonitor:
    def __init__(self, pin: int, position_id: int,
                 on_trigger: Callable[[int], Coroutine[Any, Any, None]]) -> None:
        self._pin = pin
        self._position_id = position_id
        self._on_trigger = on_trigger
        self._button: Any = None

    def start(self) -> None:
        if not _HAS_GPIOZERO:
            logger.warning(f"gpiozero not available, GPIO pin {self._pin} for position {self._position_id} disabled")
            return
        try:
            self._button = Button(self._pin, pull_up=True)
            self._button.when_pressed = lambda: asyncio.run_coroutine_threadsafe(
                self._on_trigger(self._position_id),
                asyncio.get_event_loop(),
            )
            logger.info(f"GPIO monitor started for position {self._position_id} on pin {self._pin}")
        except Exception as e:
            logger.error(f"Failed to start GPIO monitor on pin {self._pin}: {e}")

    def stop(self) -> None:
        if self._button:
            self._button.close()
            self._button = None
            logger.info(f"GPIO monitor stopped for position {self._position_id}")


class UXDevice:
    def __init__(self, device_id: str, config: dict[str, Any] | None = None) -> None:
        self.device_id = device_id
        self._config = config or {}

    async def send_command(self, command: str) -> bool:
        logger.info(f"UXDevice {self.device_id}: send command '{command}'")
        return True

    async def read_status(self) -> dict[str, Any]:
        return {"device_id": self.device_id, "online": True}


class UXManager:
    def __init__(self, config: AppConfig,
                 on_recording_trigger: Callable[[int], Coroutine[Any, Any, None]] | None = None) -> None:
        self._config = config
        self._gpio_monitors: dict[int, GPIOMonitor] = {}
        self._ux_devices: dict[str, UXDevice] = {}
        self._on_trigger = on_recording_trigger

    def set_trigger_callback(self, cb: Callable[[int], Coroutine[Any, Any, None]]) -> None:
        self._on_trigger = cb

    async def _trigger_recording(self, position_id: int) -> None:
        if self._on_trigger:
            await self._on_trigger(position_id)

    def add_gpio_monitor(self, position_id: int, pin: int) -> GPIOMonitor:
        monitor = GPIOMonitor(pin, position_id, self._trigger_recording)
        self._gpio_monitors[position_id] = monitor
        return monitor

    def remove_gpio_monitor(self, position_id: int) -> None:
        monitor = self._gpio_monitors.pop(position_id, None)
        if monitor:
            monitor.stop()

    def register_ux_device(self, device_id: str, ux_config: dict[str, Any] | None = None) -> UXDevice:
        device = UXDevice(device_id, ux_config)
        self._ux_devices[device_id] = device
        logger.info(f"UX device registered: {device_id}")
        return device

    def get_ux_device(self, device_id: str) -> UXDevice | None:
        return self._ux_devices.get(device_id)

    def start_all(self) -> None:
        for monitor in self._gpio_monitors.values():
            monitor.start()

    def stop_all(self) -> None:
        for monitor in self._gpio_monitors.values():
            monitor.stop()
        self._gpio_monitors.clear()
        self._ux_devices.clear()
        logger.info("All UX/TX devices stopped")
