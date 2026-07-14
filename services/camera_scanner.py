from __future__ import annotations

import platform
from typing import Any

import cv2
from loguru import logger

from config.settings import AppConfig


class CameraScanner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def scan_webcams(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        system = platform.system()

        if system == "Linux":
            import glob
            video_devs = sorted(glob.glob("/dev/video*"))
            for dev in video_devs:
                try:
                    idx_str = dev.replace("/dev/video", "")
                    idx = int(idx_str)
                    cap = cv2.VideoCapture(idx)
                    available = cap.isOpened()
                    name = dev
                    if available:
                        w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                        h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                        name = f"{dev} ({int(w)}x{int(h)})"
                        cap.release()
                    results.append({"index": idx, "name": name, "available": available})
                except (ValueError, OSError):
                    continue
        elif system == "Darwin":
            for idx in range(4):
                cap = cv2.VideoCapture(idx)
                available = cap.isOpened()
                name = f"Camera {idx}"
                if available:
                    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    name = f"Camera {idx} ({int(w)}x{int(h)})"
                    cap.release()
                results.append({"index": idx, "name": name, "available": available})
        elif system == "Windows":
            for idx in range(8):
                cap = cv2.VideoCapture(idx)
                available = cap.isOpened()
                name = f"Camera {idx}"
                if available:
                    cap.release()
                results.append({"index": idx, "name": name, "available": available})

        logger.info(f"Webcam scan found {len([r for r in results if r['available']])} device(s)")
        return results

    async def get_available_usb(self) -> list[int]:
        available: list[int] = []
        system = platform.system()
        if system == "Linux":
            import glob, subprocess
            for dev in sorted(glob.glob("/dev/video*")):
                try:
                    r = subprocess.run(
                        ["ffmpeg", "-f", "v4l2", "-t", "0.2", "-i", dev, "-f", "null", "-"],
                        capture_output=True, timeout=2,
                    )
                    if r.returncode == 0:
                        idx = int(dev.replace("/dev/video", ""))
                        available.append(idx)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    pass
        elif system == "Darwin":
            for idx in range(4):
                try:
                    cap = cv2.VideoCapture(idx)
                    if cap.isOpened():
                        available.append(idx)
                        cap.release()
                except Exception:
                    pass
        return available

    async def scan_network(self, subnet: str | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        target_subnet = subnet or self._config.scan.subnet
        ports = self._config.scan.rtsp_ports
        timeout = self._config.scan.network_scan_timeout

        logger.info(f"Scanning network {target_subnet} for RTSP cameras on ports {ports}")

        try:
            from ipaddress import ip_network

            import socket

            net = ip_network(target_subnet, strict=False)
            hosts = list(net.hosts())[:254]

            for host in hosts:
                ip = str(host)
                for port in ports:
                    rtsp_url = f"rtsp://{ip}:{port}"
                    if await self._check_rtsp(rtsp_url, timeout):
                        results.append({
                            "ip": ip,
                            "port": port,
                            "rtsp_url": rtsp_url,
                            "manufacturer": None,
                            "model": None,
                        })
                        logger.info(f"Found RTSP camera at {rtsp_url}")
                        break
        except ImportError:
            logger.warning("ipaddress module not available for network scan")
        except Exception as e:
            logger.error(f"Network scan error: {e}")

        logger.info(f"Network scan found {len(results)} camera(s)")
        return results

    async def _check_rtsp(self, url: str, timeout: int) -> bool:
        try:
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                return ret
            cap.release()
        except Exception:
            pass
        return False
