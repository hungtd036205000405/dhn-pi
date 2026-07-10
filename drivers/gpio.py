from __future__ import annotations

from typing import Any

try:
    from gpiozero import LED, Button, OutputDevice, Device
    _HAS_GPIOZERO = True
except ImportError:
    LED = None
    Button = None
    OutputDevice = None
    Device = None
    _HAS_GPIOZERO = False

from loguru import logger

from config.settings import AppConfig, GPIODeviceConfig

_DEVICE_TYPES: dict[str, type] = {}
if _HAS_GPIOZERO:
    _DEVICE_TYPES = {
        "LED": LED,
        "Button": Button,
        "OutputDevice": OutputDevice,
    }


class GPIODeviceManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._devices: dict[str, Device] = {}

    def initialize(self) -> None:
        if not _HAS_GPIOZERO:
            logger.warning("gpiozero not available (not running on Raspberry Pi)")
            return
        if not self._config.gpio.devices:
            logger.info("No GPIO devices configured")
            return

        for device_cfg in self._config.gpio.devices:
            self._register_device(device_cfg)
        logger.info(f"Initialized {len(self._devices)} GPIO device(s)")

    def _register_device(self, cfg: GPIODeviceConfig) -> None:
        device_cls = _DEVICE_TYPES.get(cfg.type)
        if device_cls is None:
            logger.warning(f"Unknown GPIO device type: {cfg.type}")
            return

        kwargs: dict[str, Any] = {"pin": cfg.pin}
        if cfg.type == "OutputDevice" and cfg.active_high is not None:
            kwargs["active_high"] = cfg.active_high
        if cfg.pull_up is not None:
            kwargs["pull_up"] = cfg.pull_up

        try:
            device = device_cls(**kwargs)
            self._devices[cfg.name] = device
            logger.info(f"GPIO device registered: {cfg.name} ({cfg.type}) on pin {cfg.pin}")
        except Exception as e:
            logger.error(f"Failed to register GPIO device '{cfg.name}': {e}")

    def get(self, name: str) -> Device | None:
        return self._devices.get(name)

    def get_led(self, name: str) -> None:
        if not _HAS_GPIOZERO or LED is None:
            return None
        device = self._devices.get(name)
        return device if isinstance(device, LED) else None

    def get_button(self, name: str) -> None:
        if not _HAS_GPIOZERO or Button is None:
            return None
        device = self._devices.get(name)
        return device if isinstance(device, Button) else None

    def set_output(self, name: str, state: bool) -> bool:
        device = self._devices.get(name)
        if device is None:
            return False
        try:
            if state:
                device.on()
            else:
                device.off()
            return True
        except (AttributeError, TypeError):
            return False

    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "type": type(dev).__name__, "pin": dev.pin.number if dev.pin else None}
            for name, dev in self._devices.items()
        ]

    def cleanup(self) -> None:
        for device in self._devices.values():
            try:
                device.close()
            except Exception:
                pass
        self._devices.clear()
        logger.info("GPIO devices cleaned up")
