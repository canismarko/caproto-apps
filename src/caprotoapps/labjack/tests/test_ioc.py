from unittest import mock
import asyncio
import datetime as dt

import pytest
from time_machine import travel
from labjack import ljm

from caprotoapps.labjack import LabJackT4, LabJackDriver, LabJackDisconnected
from caproto.asyncio.server import AsyncioAsyncLayer


@pytest.fixture
def ioc():
    ioc = LabJackT4(prefix="test_ioc:", identifier="labjack.example.com")
    ioc.driver.api = mock.MagicMock()
    yield ioc


def test_pvs(ioc):
    # analog inputs
    assert "test_ioc:Ai0" in ioc.pvdb
    assert "test_ioc:AiEnable0" in ioc.pvdb
    assert "test_ioc:AiMode0" in ioc.pvdb
    assert "test_ioc:AiTempUnits0" in ioc.pvdb
    assert "test_ioc:AiDiff0" in ioc.pvdb
    assert "test_ioc:AiRange0" in ioc.pvdb
    assert "test_ioc:AiResolution0" in ioc.pvdb
    # analog outputs
    assert "test_ioc:Ao0" in ioc.pvdb
    assert "test_ioc:Ao0TweakVal" in ioc.pvdb
    assert "test_ioc:Ao0TweakUp" in ioc.pvdb
    assert "test_ioc:Ao0TweakDown" in ioc.pvdb
    # digital I/O
    assert "test_ioc:Bi0" in ioc.pvdb
    assert "test_ioc:Bo0" in ioc.pvdb
    assert "test_ioc:Bd0" in ioc.pvdb
    assert "test_ioc:DIOIn" in ioc.pvdb
    assert "test_ioc:EIOIn" in ioc.pvdb
    assert "test_ioc:FIOIn" in ioc.pvdb
    assert "test_ioc:CIOIn" in ioc.pvdb
    assert "test_ioc:MIOIn" in ioc.pvdb


@pytest.mark.asyncio
async def test_load_device_info(ioc):
    # Set up fake replies to api calls
    ioc.driver.api.getHandleInfo.return_value = [
        7,  # Model number: "T7"
        1,  # Connection type: "USB"
        "579934",  # Serial number
        "127.0.0.1", # IP address
        5000,  # Port
        2048,  # Max bytes per MB (not used)
    ]
    ioc.driver.api.eReadName.return_value = "1.0.1"
    await ioc.driver.connect()
    # Get the device info and check it
    await ioc.load_device_info()
    assert ioc.firmware_version.value == "1.0.1"
    assert ioc.serial_number.value == "579934"
    assert ioc.ljm_version.value == ljm.__version__
    assert ioc.driver_version.value == "3.0.0"
    assert ioc.last_error_message.value == "No error"


@pytest.mark.asyncio
async def test_read_inputs(ioc):
    # Set fake data
    await ioc.driver.connect()
    ioc.driver.api.eReadNames.return_value = [
        float(0b01001101000111011010),  # DIO_STATE
        0.0,  # DIO_DIRECTION
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
    # Ask the IOC to update its inputs
    await ioc.read_inputs()
    # Check that the inputs were cached, not updated
    assert ioc.pvdb["test_ioc:Ai0"].value != 0.7542197081184724
    ioc._ai_cache["AIN0"] == 0.7542197081184724
    # Check that the digital inputs were updated
    assert ioc.pvdb["test_ioc:Bi0"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi1"].value == "High"
    assert ioc.pvdb["test_ioc:Bi2"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi3"].value == "High"
    assert ioc.pvdb["test_ioc:Bi4"].value == "High"
    assert ioc.pvdb["test_ioc:Bi5"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi6"].value == "High"
    assert ioc.pvdb["test_ioc:Bi7"].value == "High"
    assert ioc.pvdb["test_ioc:Bi8"].value == "High"
    assert ioc.pvdb["test_ioc:Bi9"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi10"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi11"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi12"].value == "High"
    assert ioc.pvdb["test_ioc:Bi13"].value == "Low"
    assert ioc.pvdb["test_ioc:Bi14"].value == "High"
    assert ioc.pvdb["test_ioc:Bi15"].value == "High"
    # Check that the digital words were updated
    assert ioc.pvdb["test_ioc:DIOIn"].value == 0b01001101000111011010
    # FIO0:7 == DIO0:7
    assert ioc.pvdb["test_ioc:FIOIn"].value == 0b11011010
    # EIO0:7 == DIO8:15
    assert ioc.pvdb["test_ioc:EIOIn"].value == 0b11010001
    # CIO0:7 == DIO16:19
    assert ioc.pvdb["test_ioc:CIOIn"].value == 0b0100


@pytest.mark.asyncio
async def test_poll_time(ioc):
    await ioc.driver.connect()
    # Set an initial time
    # d0 = dt.datetime(2023, 11, 1, 10, 55, 11, 589330)
    t0 = 1698854768.6413221
    await ioc.update_poll_time(t0)
    traveller = travel(t0, tick=False)
    fake_time = traveller.start()
    
    # Set fake data
    def read_names(*args, **kwargs):
        """Mocked read names that takes ~50 ms."""
        # Pretend it takes 53.3 milliseconds to read the thing
        fake_time.shift(0.0513)
        return [
            float(0b01001101000111011010),  # DIO_STATE
            0.0,  # DIO_DIRECTION
            0.7542197081184724,  # AIN0
        ]
    
    ioc.driver.api.eReadNames.side_effect = read_names
    # Ask the IOC to update its inputs
    await ioc.read_inputs()
    # Check that the poll time was updated
    assert ioc.poll_time_ms.value == pytest.approx(51.3)


@pytest.mark.asyncio
async def test_update_poll_time(ioc):
    tn = 1698854768.6413221
    # Pretend we've measured 13 read events
    times = [0.75565086, 0.19431558, 0.54190896, 0.35342251, 0.25425838,
             0.13587837, 0.12274659, 0.62698737, 0.88789073, 0.26674585,
             0.43186444, 0.46955297]
    await ioc.update_poll_time(tn)
    for t in times:
        tn += t
        await ioc.update_poll_time(tn)
    # Check that the poll time is the average of the last time read events
    poll_time_s = sum(times[2:]) / 10
    assert ioc.poll_time_ms.value == pytest.approx(poll_time_s * 1000)

@pytest.mark.asyncio
async def test_scan_analog_input(ioc):
    """Check that the analog inputs update from cached values when scanned."""
    ai = ioc.analog_inputs.ai0
    pv = ioc.pvdb["test_ioc:Ai0"]
    # Pretend we've already cached some values
    ioc._ai_cache = {
        "AIN0": 1.334,
    }
    await ai.update_value(instance=pv)
    # Check that the PV got updated
    assert pv.value == 1.334
    

@pytest.mark.asyncio
async def test_digital_outputs(ioc):
    ioc.driver.api = mock.MagicMock()
    await ioc.driver.connect()
    # Set one of the binary outputs
    await ioc.pvdb["test_ioc:Bo0"].write(1)
    # Check that the binary output was written
    assert ioc.driver.api.eWriteName.called


@pytest.mark.asyncio
async def test_analog_outputs(ioc):
    ioc.driver.api = mock.MagicMock()
    await ioc.driver.connect()
    # Set one of the binary outputs
    await ioc.pvdb["test_ioc:Ao0"].write(3.14159)
    # Check that the binary output was written
    assert ioc.driver.api.eWriteName.called
    # Check that the PV was also updated
    assert ioc.pvdb["test_ioc:Ao0"].value == 3.14159


@pytest.mark.asyncio
async def test_digital_directions(ioc):
    ioc.driver.api = mock.MagicMock()
    await ioc.driver.connect()
    # Set one of the binary outputs
    await ioc.pvdb["test_ioc:Bd0"].write("Output")
    # Check that the binary output was written
    assert ioc.driver.api.eWriteName.called
