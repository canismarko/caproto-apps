from unittest import mock
import struct
import asyncio
import socket

import pytest
from caproto.server import SubGroup, PVGroup

from caprotoapps import alive




def test_heartbeat_message():
    result = alive.heartbeat_message(magic_number=305419896,
                               incarnation=1686795752.651364,
                               current_time=1686795860.727304,
                               heartbeat_value=25,
                               period=15,
                               flags=0b00000010,
                               return_port=0,
                               user_message=9,
                               ioc_name="25idAustin",
                               )
    assert type(result) == bytes
    print(result)
    # Check magic number message
    EPICS_TIME_CORRECTION = -631152000
    # Magic number
    assert struct.unpack(">L", result[:4])[0] == 305419896
    # Alive protocol version
    assert struct.unpack(">H", result[4:6])[0] == 5
    # Incarnation time
    assert struct.unpack(">L", result[6:10])[0] == 1686795753 + EPICS_TIME_CORRECTION
    # Current time
    assert struct.unpack(">L", result[10:14])[0] == 1686795861 + EPICS_TIME_CORRECTION
    # Heartbeat value
    assert struct.unpack(">L", result[14:18])[0] == 25
    # Period
    assert struct.unpack(">H", result[18:20])[0] == 15
    # Flags
    assert struct.unpack(">H", result[20:22])[0] == 0b00000010
    # Return port
    assert struct.unpack(">H", result[22:24])[0] == 0
    # User message
    assert struct.unpack(">L", result[24:28])[0] == 9
    # IOC name
    assert result[28:38].decode('ascii') == "25idAustin"
    assert len(result) == 39
    # Null terminator
    assert result[38] == 0


class MockIOC(PVGroup):
    alive = SubGroup(alive.AliveGroup)


@pytest.fixture
def test_ioc():
    ioc = MockIOC(prefix="test_ioc:")
    ioc.alive.incarnation = alive.epics_time(1686882446.0032349)
    ioc.alive.async_lib = asyncio
    ioc.alive.send_udp_message = mock.AsyncMock()
    ioc.alive
    yield ioc


@pytest.mark.asyncio
async def test_send_heartbeat(test_ioc):
    alive_group = test_ioc.alive
    sock = mock.MagicMock()
    # Send the message to the server
    await alive_group.raddr.write("192.0.2.0")
    await alive_group.rport.write(5895)
    await alive_group.val.write(5)
    # First with the HRTBT field off (no heartbeat)
    await alive_group.send_heartbeat()
    assert alive_group.val.value == 5
    assert not alive_group.send_udp_message.called
    # Now with the HRTBT field on (send heartbeat)
    await alive_group.hrtbt.write(True)
    await alive_group.send_heartbeat()
    assert alive_group.val.value == 6
    # Check the message was sent properly
    assert alive_group.send_udp_message.called
    assert alive_group.send_udp_message.call_args.kwargs['address'] == ("192.0.2.0", 5895)

@pytest.mark.asyncio
async def test_host_resolution(test_ioc):
    alive_group = test_ioc.alive
    # alive_group.sock.gethostbyname.return_value = "127.0.0.1"
    await alive_group.rhost.write("localhost")
    assert alive_group.raddr.value == "127.0.0.1"

@pytest.mark.asyncio
async def test_server_address(test_ioc):
    """Check that the server address is retrieved from PVs."""
    alive_group = test_ioc.alive
    # First check if both settings are invalid
    addr, port = alive_group.server_address()
    assert addr is None
    assert port is None
    # Check a valid rhost
    await alive_group.rhost.write("127.0.0.1")
    await alive_group.rport.write(88)
    addr, port = alive_group.server_address()
    assert addr == "127.0.0.1"
    assert port == 88
    # Check that AUX host overrules rhost
    await alive_group.ahost.write("127.0.0.2")
    await alive_group.aport.write(89)
    addr, port = alive_group.server_address()
    assert addr == "127.0.0.2"
    assert port == 89

@pytest.mark.asyncio
async def test_heartbeat_flags(test_ioc):
    alive_group = test_ioc.alive
    await alive_group.rport.write(5000)
    await alive_group.raddr.write("127.0.0.1")
    await alive_group.hrtbt.write(True)
    print("Values:", repr(alive_group.rport.value), alive_group.raddr.value)
    sock = mock.MagicMock()
    await alive_group.send_heartbeat()
    # No flags set
    assert alive_group.send_udp_message.called
    message = alive_group.send_udp_message.call_args.kwargs['message']
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b0
    # Flag for ITRIG being set
    sock.sendto.clear()
    await alive_group.itrig.write(1)
    await alive_group.send_heartbeat()
    message = alive_group.send_udp_message.call_args.kwargs['message']
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b1
    # Flag for ISUP being set
    sock.sendto.clear()
    await alive_group.isup.write(1)
    await alive_group.send_heartbeat()
    message = alive_group.send_udp_message.call_args.kwargs['message']
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b11


@pytest.mark.asyncio
async def test_ioc_name(monkeypatch):
    ioc = alive.AliveGroup(prefix="alive")
    # Check that if fails if no IOC name is discernable
    with pytest.raises(alive.NoIOCName):
        await ioc.iocnm.startup(ioc.iocnm, None)
    # Check parent IOC prefix
    IOC = type('IOC', (PVGroup,), {"alive": SubGroup(alive.AliveGroup)})
    ioc = IOC(prefix="my_awesome_ioc:")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "my_awesome_ioc"
    # Check IOC environmental variable
    monkeypatch.setenv("IOC", "our_ioc")
    IOC = type('IOC', (PVGroup,), {"alive": SubGroup(alive.AliveGroup)})
    ioc = IOC(prefix="my_awesome_ioc")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "our_ioc"
    # Check explicit IOC name as argument
    IOC = type('IOC', (PVGroup,), {"alive": SubGroup(alive.AliveGroup, ioc_name="my_ioc")})
    ioc = IOC(prefix="my_awesome_ioc")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "my_ioc"
