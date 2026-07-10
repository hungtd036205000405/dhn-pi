import pytest
from unittest.mock import patch, MagicMock

from config.settings import AppConfig, MQTTConfig, MQTTTopics


@pytest.fixture
def mqtt_config() -> AppConfig:
    return AppConfig(
        mqtt=MQTTConfig(
            MQTT_BROKER="localhost",
            MQTT_PORT=1883,
            MQTT_CLIENT_ID="test-dhn-pi",
            topics=MQTTTopics(
                sensors="test/sensors",
                commands="test/commands",
                status="test/status",
            ),
        )
    )


def test_mqtt_client_connect(mqtt_config: AppConfig) -> None:
    from services.mqtt_client import MQTTClient

    with patch("paho.mqtt.client.Client") as mock_mqtt:
        mock_instance = mock_mqtt.return_value

        client = MQTTClient(mqtt_config)
        client.connect()

        mock_instance.connect.assert_called_once_with("localhost", 1883, 60)


def test_mqtt_client_publish_dict(mqtt_config: AppConfig) -> None:
    from services.mqtt_client import MQTTClient

    with patch("paho.mqtt.client.Client") as mock_mqtt:
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value.rc = 0

        client = MQTTClient(mqtt_config)
        client.publish("test/topic", {"key": "value"})

        mock_instance.publish.assert_called_once()
        args, kwargs = mock_instance.publish.call_args
        assert args[0] == "test/topic"
        assert '"key": "value"' in args[1]


def test_mqtt_client_subscribe(mqtt_config: AppConfig) -> None:
    from services.mqtt_client import MQTTClient

    with patch("paho.mqtt.client.Client") as mock_mqtt:
        mock_instance = mock_mqtt.return_value

        client = MQTTClient(mqtt_config)
        client.subscribe("test/commands")

        mock_instance.subscribe.assert_called_once_with("test/commands", qos=1)


def test_mqtt_message_handler(mqtt_config: AppConfig) -> None:
    from services.mqtt_client import MQTTClient

    with patch("paho.mqtt.client.Client") as mock_mqtt:
        client = MQTTClient(mqtt_config)

        received = []
        client.on_topic("test/commands", lambda topic, payload: received.append(payload))

        msg = MagicMock()
        msg.topic = "test/commands"
        msg.payload = b'{"cmd": "toggle", "device": "led_1"}'

        client._on_message(None, None, msg)
        assert len(received) == 1
        assert received[0]["cmd"] == "toggle"
        assert received[0]["device"] == "led_1"
