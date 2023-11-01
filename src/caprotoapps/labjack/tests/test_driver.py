from unittest import mock

import pytest
from labjack import ljm

from caprotoapps.labjack import LabJackDriver, LabJackDisconnected


@pytest.fixture()
def driver():
    api = mock.MagicMock()
    api.openS.return_value = 2
    # Mock device information
    identifier = "255idlabjack00.xray.aps.anl.gov"
    driver = LabJackDriver(identifier, api=api)
    driver._handle = 1
    return driver


@pytest.mark.asyncio
async def test_handle():
    """Does the handle get created properly in the driver."""
    api = mock.MagicMock()
    api.openS.return_value = 2
    identifier = "255idlabjack00.xray.aps.anl.gov"
    driver = LabJackDriver(identifier, api=api)
    # Confirm that we can't access the labjack handle before connecting
    assert not api.openS.called
    with pytest.raises(LabJackDisconnected):
        driver.handle
    # Confirm that we can access the labjack handle once connected
    await driver.connect()
    assert api.openS.called
    api.openS.assert_called_with("ANY", "ANY", identifier)
    assert driver.handle == 2


@pytest.mark.asyncio
async def test_hostname_resolution(driver):
    """Does the driver convert hostnames to IP addresses."""
    # Prepare the driver for testing
    api = mock.MagicMock()
    api.openS.return_value = 2
    identifier = "localhost"
    driver = LabJackDriver(identifier, api=api)
    assert driver.identifier == "localhost"
    # Check that the identifier is converted during connecting
    await driver.connect()
    assert driver.identifier == "127.0.0.1"


@pytest.mark.asyncio
async def test_device_info(driver):
    await driver.connect()
    # Set some fake device info
    driver.api.getHandleInfo.return_value = (
        7,  # T7
        3,  # Ethernet
        8038574,  # Serial number
        -1539930247,  # IP address
        502,  # Port
        1040,  # Max bytes per packet
    )
    driver.api.eReadName.return_value = 1.34445
    # Check that the device info is read properly
    info = await driver.device_info()
    assert info == {
        "driver_version": "3.0.0",
        "model_name": "T7",
        "serial_number": "8038574",
        "firmware_version": "1.34445",
    }
    assert driver.ljm_version == ljm.__version__


@pytest.mark.asyncio
async def test_read_registers(driver):
    driver.api.eReadNames.return_value = [0.0]
    assert await driver.read_registers(["AIN0"]) == {
        "AIN0": 0.0,
    }


@pytest.mark.asyncio
async def test_read_inputs(driver):
    driver.api.eReadNames.return_value = [
        float(8388607),  # DIO_STATE
        float(0),  # DIO_DIRECTION
        0.7542197081184724,  # AIN0
        0.5278198329636620,  # AIN1
        0.9013162824853298,  # AIN2
        0.9585645891744154,  # AIN3
        0.0877954589716192,  # AIN4
        0.6531741744255257,  # AIN5
        0.1692810190784566,  # AIN6
        0.9081275311814707,  # AIN7
        0.2128145149923829,  # AIN8
        0.2869844556845337,  # AIN9
        0.5396007779162098,  # AIN10
        0.9378320987673755,  # AIN11
        0.3076448430555906,  # AIN12
        0.6858320718644135,  # AIN13
        0.5475323777280595,  # AIN14
        0.0662560636422623,  # AIN15
    ]
    result = await driver.read_inputs()
    assert result == {
        "DIO_STATE": 0b11111111111111111111111,
        "DIO_DIRECTION": 0b0,
        "AIN0": 0.7542197081184724,  # AIN0
        "AIN1": 0.5278198329636620,  # AIN1
        "AIN2": 0.9013162824853298,  # AIN2
        "AIN3": 0.9585645891744154,  # AIN3
        "AIN4": 0.0877954589716192,  # AIN4
        "AIN5": 0.6531741744255257,  # AIN5
        "AIN6": 0.1692810190784566,  # AIN6
        "AIN7": 0.9081275311814707,  # AIN7
        "AIN8": 0.2128145149923829,  # AIN8
        "AIN9": 0.2869844556845337,  # AIN9
        "AIN10": 0.5396007779162098,  # AIN10
        "AIN11": 0.9378320987673755,  # AIN11
        "AIN12": 0.3076448430555906,  # AIN12
        "AIN13": 0.6858320718644135,  # AIN13
        "AIN14": 0.5475323777280595,  # AIN14
        "AIN15": 0.0662560636422623,  # AIN15
    }
    # Check type conversion
    assert type(result["DIO_STATE"]) is int
    assert type(result["DIO_DIRECTION"]) is int
    assert type(result["AIN0"]) is float


@pytest.mark.asyncio
async def test_write_digital_output(driver):
    await driver.connect()
    # Write a value
    await driver.write_digital_output(dio_num=0, value=1)
    # Check that the driver was called properly
    assert driver.api.eWriteName.called
    driver.api.eWriteName.assert_called_with(2, "DIO0", 1)


@pytest.mark.asyncio
async def test_write_digital_output(driver):
    await driver.connect()
    # Write a value
    await driver.write_analog_output(ao_num=1, value=3.14159)
    # Check that the driver was called properly
    assert driver.api.eWriteName.called
    handle = 2
    driver.api.eWriteName.assert_called_with(handle, "DAC1", 3.14159)


@pytest.mark.asyncio
async def test_write_digital_direction_input(driver):
    await driver.connect()
    # Set fake initial state coming from the API
    driver.api.eReadName.return_value = 0b111111111
    # Write a value
    await driver.write_digital_direction(dio_num=1, direction=0)
    # Check that the driver was called properly
    assert driver.api.eWriteName.called
    handle = 2
    driver.api.eWriteName.assert_called_with(handle, "DIO_DIRECTION", 0b111111101)


@pytest.mark.asyncio
async def test_write_digital_direction_output(driver):
    await driver.connect()
    # Set fake initial state coming from the API
    driver.api.eReadName.return_value = 0b000000001000
    # Write a value
    await driver.write_digital_direction(dio_num=11, direction=1)
    # Check that the driver was called properly
    assert driver.api.eWriteName.called
    handle = 2
    driver.api.eWriteName.assert_called_with(handle, "DIO_DIRECTION", 0b100000001000)
