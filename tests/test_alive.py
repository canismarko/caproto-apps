from unittest import mock
import struct
import asyncio
import socket

import pytest
from caproto.server import SubGroup, PVGroup

from caprotoapps import alive


def test_heartbeat_message():
    result = alive.heartbeat_message(
        magic_number=305419896,
        incarnation=1686795752.651364,
        current_time=1686795860.727304,
        heartbeat_value=25,
        period=15,
        request_read=False,
        suppress_environment=True,
        return_port=0,
        user_message=9,
        ioc_name="25idAustin",
    )
    assert type(result) == bytes
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
    assert result[28:38].decode("ascii") == "25idAustin"
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
    await alive_group.hrtbt.write(False)
    await alive_group.send_heartbeat()
    assert alive_group.val.value == 5
    assert not alive_group.send_udp_message.called
    # Now with the HRTBT field on (send heartbeat)
    await alive_group.hrtbt.write(True)
    await alive_group.send_heartbeat()
    assert alive_group.val.value == 6
    # Check the message was sent properly
    assert alive_group.send_udp_message.called
    assert alive_group.send_udp_message.call_args.kwargs["address"] == (
        "192.0.2.0",
        5895,
    )


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
    with pytest.raises(alive.InvalidServerAddress):
        addr, port = alive_group.server_address()
    # Check a valid rhost
    await alive_group.rhost.write("127.0.0.1")
    await alive_group.rport.write(88)
    addr, port = alive_group.server_address()
    assert addr == "127.0.0.1"
    assert port == 88
    # Check that AUX host comes back
    await alive_group.ahost.write("127.0.0.2")
    await alive_group.aport.write(89)
    addr, port = alive_group.server_address(use_aux=True)
    assert addr == "127.0.0.2"
    assert port == 89


@pytest.mark.asyncio
async def test_heartbeat_flags(test_ioc):
    alive_group = test_ioc.alive
    await alive_group.rport.write(5000)
    await alive_group.raddr.write("127.0.0.1")
    await alive_group.hrtbt.write(True)
    sock = mock.MagicMock()
    await alive_group.send_heartbeat()
    # No flags set
    assert alive_group.send_udp_message.called
    message = alive_group.send_udp_message.call_args.kwargs["message"]
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b01
    # Flag for ITRIG being set
    sock.sendto.clear()
    await alive_group.itrig.write(1)
    await alive_group.send_heartbeat()
    message = alive_group.send_udp_message.call_args.kwargs["message"]
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b1
    # Flag for ISUP being set
    sock.sendto.clear()
    await alive_group.isup.write(1)
    await alive_group.send_heartbeat()
    message = alive_group.send_udp_message.call_args.kwargs["message"]
    flags = struct.unpack(">H", message[20:22])[0]
    assert flags == 0b11


@pytest.mark.asyncio
async def test_ioc_name(monkeypatch):
    ioc = alive.AliveGroup(prefix="alive")
    # Check that if fails if no IOC name is discernable
    with pytest.raises(alive.NoIOCName):
        await ioc.iocnm.startup(ioc.iocnm, None)
    # Check parent IOC prefix
    IOC = type("IOC", (PVGroup,), {"alive": SubGroup(alive.AliveGroup)})
    ioc = IOC(prefix="my_awesome_ioc:")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "my_awesome_ioc"
    # Check IOC environmental variable
    monkeypatch.setenv("IOC", "our_ioc")
    IOC = type("IOC", (PVGroup,), {"alive": SubGroup(alive.AliveGroup)})
    ioc = IOC(prefix="my_awesome_ioc")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "our_ioc"
    # Check explicit IOC name as argument
    IOC = type(
        "IOC", (PVGroup,), {"alive": SubGroup(alive.AliveGroup, ioc_name="my_ioc")}
    )
    ioc = IOC(prefix="my_awesome_ioc")
    await ioc.alive.iocnm.startup(ioc.alive.iocnm, None)
    assert ioc.alive.iocnm.value == "my_ioc"


@pytest.fixture()
def writer():
    writer = mock.AsyncMock()
    writer.get_extra_info = mock.MagicMock(return_value = ("9.9.9.9", 0))
    writer.write = mock.MagicMock()
    writer.close = mock.MagicMock()
    yield writer


@pytest.mark.asyncio
async def test_env_callback_suppressed(test_ioc, writer):
    alive_group = test_ioc.alive
    reader = mock.AsyncMock()
    # Set the ISUP flag to true
    await alive_group.isup.write(1)
    # Check that request was refused
    await alive_group.handle_env_request(reader, writer)
    assert not writer.write.called
    assert writer.close.called


@pytest.mark.asyncio
async def test_env_callback_badhost(test_ioc, writer):
    alive_group = test_ioc.alive
    reader = mock.AsyncMock()
    # Set the ISUP flag to true just in case
    await alive_group.isup.write(0)
    # Check that request was refused
    await alive_group.handle_env_request(reader, writer)
    assert not writer.write.called
    assert writer.close.called


@pytest.mark.asyncio
async def test_env_callback(test_ioc, writer):
    alive_group = test_ioc.alive
    await alive_group.isup.write(0)
    await alive_group.raddr.write("9.9.9.9")
    reader = mock.AsyncMock()
    # Ask for some environmental variables
    await alive_group.handle_env_request(reader, writer)
    assert writer.write.called
    # Check response messages
    messages = [call.args[0] for call in writer.write.call_args_list]
    # Information message
    info_target = (
        b"\x00\x05"  # Version
        b"\x00\x02"  # IOC type: Linux
    )
    assert messages[0].startswith(info_target)


def test_env_messages(monkeypatch):
    env_variables = [
        ("ENGINEER", "Quig"),
        ("PREFIX", "test_ioc:"),
    ]
    body_length = sum([len(k) + len(v) for k, v in env_variables])
    for key, val in env_variables:
        monkeypatch.setenv(key, val)
    messages = alive.env_messages(version=4, ioc_type=alive.IOCType.LINUX,
                                  env_variables=[d[0] for d in env_variables])
    # Check the header
    header, *remaining_messages = messages
    expected_length = 10 + sum([len(m) for m in remaining_messages])
    expected_header = b"".join([
        b"\x00\x04",  # Version
        b"\x00\x02",  # IOC type: Linux
        struct.pack(">I", expected_length), # E.g. b"\x00\x00\x00\x50" 
        b"\x00\x02", # Variable count
    ])
    assert header == expected_header
    # Check individual variable's messages
    assert len(remaining_messages) == len(env_variables) + 3  # +3 for IOC-specific data


@pytest.mark.asyncio
async def test_env_variable_list(test_ioc):
    alive_group = test_ioc.alive
    # Set some environmental variables to ask for
    await alive_group.evd1.write("ENGINEER")
    await alive_group.evd2.write("ARCH")
    await alive_group.evd3.write("")
    await alive_group.evd4.write("")
    await alive_group.evd5.write("")
    await alive_group.ev2.write("HOST_ARCH")
    assert list(alive_group.env_variables.keys()) == ["ENGINEER", "HOST_ARCH"]
    
    
@pytest.mark.asyncio
async def test_read_status_fields(test_ioc, writer):
    """Check that the ITRIG field gets set automatically."""
    reader = mock.AsyncMock()
    alive_group = test_ioc.alive
    await alive_group.raddr.write("9.9.9.9")
    await alive_group.rport.write(999)
    await alive_group.rrsts.write("Idle")
    # Check that the flag is off if no env update is requested
    await alive_group.send_heartbeat()
    assert alive_group.send_udp_message.called
    msg = alive_group.send_udp_message.call_args.kwargs['message']
    flags = msg[20:22]
    assert flags == b"\x00\x00"
    # Setup the trigger status
    assert alive_group.rrsts.value == "Idle"
    await alive_group.itrig.write(True)
    assert alive_group.itrig.value == "Off"
    assert alive_group.rrsts.value == "Queued"
    # Does the ITRIG field get once the next heartbeat goes out?
    await alive_group.send_heartbeat()
    assert alive_group.itrig.value == "Off"
    assert alive_group.rrsts.value == "Due"
    # Check that the message had the right flags set
    assert alive_group.send_udp_message.called
    msg = alive_group.send_udp_message.call_args.kwargs['message']
    flags = msg[20:22]
    assert flags == b"\x00\x01"
    # Check that the read status flag gets cleared
    await alive_group.handle_env_request(reader, writer)
    assert alive_group.rrsts.value == "Idle"


@pytest.mark.asyncio
async def test_changing_env_variables(test_ioc):
    """Check that the read status is updated if the environmental variables change."""
    alive_group = test_ioc.alive
    await alive_group.ev1.write("ENGINEER")
    await alive_group.rrsts.write("Idle")
    # from caproto.asyncio.server import AsyncioAsyncLayer
    # print(alive_group.rrsts.scan)
    await alive_group.check_env(alive_group.rrsts.scan, None)
    # Check that queued was set
    assert alive_group.rrsts.value == "Queued"
