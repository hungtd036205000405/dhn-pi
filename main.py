import asyncio
import signal
import sys

from loguru import logger

from config.settings import load_config
from core.controller import Controller

logger.remove()
logger.add(
    sys.stderr,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
)
logger.add(
    "dhn_pi.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
)

_controller: Controller | None = None


async def main() -> None:
    global _controller

    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"MQTT broker: {config.mqtt.broker}:{config.mqtt.port}")
    logger.info(f"Web server: {config.web.host}:{config.web.port}")
    logger.info(f"Database: {config.database_url}")
    logger.info(f"Camera: {'enabled' if config.camera.enabled else 'disabled'}")

    _controller = Controller(config)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    await _controller.start()
    await _controller.wait_for_shutdown()


async def shutdown() -> None:
    global _controller
    if _controller:
        await _controller.stop()
        _controller = None


if __name__ == "__main__":
    asyncio.run(main())
