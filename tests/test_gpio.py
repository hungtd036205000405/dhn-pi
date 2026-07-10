import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def gpio_config():
    from config.settings import AppConfig, GPIOConfig, GPIODeviceConfig
    return AppConfig(
        gpio=GPIOConfig(
            devices=[
                GPIODeviceConfig(name="test_led", type="LED", pin=17),
                GPIODeviceConfig(name="test_button", type="Button", pin=18, pull_up=True),
                GPIODeviceConfig(name="test_relay", type="OutputDevice", pin=23, active_high=True),
            ]
        )
    )


def test_gpio_manager_init(gpio_config):
    import drivers.gpio as gpio_mod

    gpio_mod._HAS_GPIOZERO = True

    with patch("drivers.gpio.LED") as mock_led, \
         patch("drivers.gpio.Button") as mock_button, \
         patch("drivers.gpio.OutputDevice") as mock_output:

        gpio_mod._DEVICE_TYPES = {
            "LED": mock_led,
            "Button": mock_button,
            "OutputDevice": mock_output,
        }

        manager = gpio_mod.GPIODeviceManager(gpio_config)
        manager.initialize()

        mock_led.assert_called_once_with(pin=17)
        mock_button.assert_called_once_with(pin=18, pull_up=True)
        mock_output.assert_called_once_with(pin=23, active_high=True)


def test_gpio_list_devices(gpio_config):
    import drivers.gpio as gpio_mod

    gpio_mod._HAS_GPIOZERO = True

    with patch("drivers.gpio.LED") as mock_led, \
         patch("drivers.gpio.Button") as mock_button, \
         patch("drivers.gpio.OutputDevice") as mock_output:

        gpio_mod._DEVICE_TYPES = {
            "LED": mock_led,
            "Button": mock_button,
            "OutputDevice": mock_output,
        }

        mock_led.return_value.pin.number = 17
        mock_button.return_value.pin.number = 18
        mock_output.return_value.pin.number = 23

        manager = gpio_mod.GPIODeviceManager(gpio_config)
        manager.initialize()

        devices = manager.list_devices()
        assert len(devices) == 3

        names = [d["name"] for d in devices]
        assert "test_led" in names
        assert "test_button" in names
        assert "test_relay" in names


def test_gpio_set_output_state(gpio_config):
    import drivers.gpio as gpio_mod

    gpio_mod._HAS_GPIOZERO = True

    with patch("drivers.gpio.LED") as mock_led, \
         patch("drivers.gpio.Button"), \
         patch("drivers.gpio.OutputDevice"):

        gpio_mod._DEVICE_TYPES = {
            "LED": mock_led,
            "Button": MagicMock(),
            "OutputDevice": MagicMock(),
        }

        mock_led_instance = mock_led.return_value
        manager = gpio_mod.GPIODeviceManager(gpio_config)
        manager.initialize()

        manager.set_output("test_led", True)
        mock_led_instance.on.assert_called_once()

        manager.set_output("test_led", False)
        mock_led_instance.off.assert_called_once()
