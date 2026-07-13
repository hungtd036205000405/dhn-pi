from __future__ import annotations

import socket
import time

import psutil

from config.settings import AppConfig


class SystemStats:
    def __init__(self, config: AppConfig) -> None:
        self._start_time = time.time()
        self._hostname = socket.gethostname()
        self._ip = self._get_ip()
        self._device_code = config.device_code
        self._version = config.version
        self._service_name = "dhn-pi"

    def get_static(self) -> dict:
        return {
            "deviceCode": self._device_code,
            "hostname": self._hostname,
            "ip": self._ip,
            "serviceName": self._service_name,
            "version": self._version,
        }

    def get_dynamic(self) -> dict:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "uptimeSeconds": int(time.time() - self._start_time),
            "cpuUsage": round(psutil.cpu_percent(interval=0), 1),
            "memoryUsageMb": round(mem.used / (1024 * 1024), 1),
            "diskFreeGb": round(disk.free / (1024**3), 1),
        }

    def get_status_payload(
        self, status: str = "online", extra: dict | None = None
    ) -> dict:
        payload = {
            "status": status,
            "ts": time.time(),
            **self.get_static(),
            **self.get_dynamic(),
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _get_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"
