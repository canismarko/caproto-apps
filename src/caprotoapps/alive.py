"""A PV group resembling the EPICS IOC alive record.

Example usage:

.. code-block:: python

    class RobotIOC(PVGroup):
        alive = SubGroup(AliveGroup, prefix="alive",
                         remote_host="alived.example.com",
                         remote_port=1234)

"""


#!/usr/bin/env python3
from contextlib import contextmanager
import logging
import sys
import time
import asyncio
from functools import partial
from threading import Lock
import re
import os
import enum
import struct
import socket

from caproto import ChannelType, SkipWrite
from caproto.server import (
    PVGroup,
    pvproperty,
    PvpropertyDouble,
    PvpropertyShort,
    PvpropertyShortRO,
    PvpropertyChar,
    SubGroup,
    scan_wrapper,
)

log = logging.getLogger(__name__)


HEARTBEAT_PERIOD = 15


class NoIOCName(AttributeError):
    """Could not discern a valid name for this IOC."""
    ...


def heartbeat_message(magic_number: int, incarnation: int|float,
                      current_time: int|float, heartbeat_value: int, period: int|float,
                      flags: int, return_port: int, user_message: int, ioc_name: str):
    """Create a UDP message that tells the server the IOC is alive.

    Convert the various parameters into a UDP message based on the
    EPICS alive record specification:

    https://epics-modules.github.io/alive/aliveRecord.html

    *incarnation* and *current_time* are expected to be in unix time
     and will be converted to epics time.

    """
    PROTOCOL_VERSION = 5
    msg = bytes()
    msg += struct.pack(">L", magic_number)  # 0-3
    msg += struct.pack(">H", PROTOCOL_VERSION)  # 4-5
    msg += struct.pack(">L", round(epics_time(incarnation)))  # 6-9
    msg += struct.pack(">L", round(epics_time(current_time)))  # 10-13
    msg += struct.pack(">L", heartbeat_value)  # 14-17
    msg += struct.pack(">H", period)  # 18-19
    msg += struct.pack(">H", flags)  # 20-21
    msg += struct.pack(">H", return_port)  # 22-23
    msg += struct.pack(">L", user_message)  # 24-*
    msg += ioc_name.encode('ascii')
    # Null terminator
    msg += b'\x00'
    return msg


def epics_time(unix_time):
    return unix_time - 631152000


class AliveGroup(PVGroup):
    _sock = None
    incarnation: int
    default_ioc_name: str
    default_remote_host: str
    default_remote_port: int

    class HostReadStatus(enum.IntEnum):
        IDLE = 0
        QUEUED = 1
        DUE = 2
        OVERDUE = 3

    class InformationPortStatus(enum.IntEnum):
        UNDETERMINED = 0
        OPERABLE = 1
        INOPERABLE = 2

    def __init__(self, remote_host: str="localhost", remote_port: int=5678, ioc_name: str=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_remote_host = remote_host
        self.default_remote_port = remote_port
        self.default_ioc_name = ioc_name

    @contextmanager
    def socket(self):
        # Create the socket
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        yield self._sock
        
    async def resolve_hostname(self, hostname):
        """Determine the host's IP address.

        Returns
        =======
        addr
          The resolved hostname.
        """
        loop = self.async_lib.get_running_loop()
        addr = await loop.run_in_executor(
            None, socket.gethostbyname, hostname,
        )
        return addr

    def server_address(self):
        """Determine which server to use for sending heartbeats.

        Checks the .RADDR and .AADDR fields to determine which to use.

        Returns
        =======
        addr
          The IP address of the host.
        port
          The port for the heartbeat message.

        """
        invalid_addrs = ["", "invalid AHOST", "invalid RHOST"]
        addr = None
        port = None
        # Check for a valid remote host
        addr_is_valid = self.raddr.value not in invalid_addrs
        port_is_valid = self.rport.value > 0
        if addr_is_valid and port_is_valid:
            addr = self.raddr.value
            port = self.rport.value
        # Check for a valid auxillary host
        addr_is_valid = self.aaddr.value not in invalid_addrs
        port_is_valid = self.aport.value > 0
        if addr_is_valid and port_is_valid:
            addr = self.aaddr.value
            port = self.aport.value
        return (addr, port)

    async def send_heartbeat(self) -> bool:
        """Send a heartbeat message to the alive server.

        Returns
        =======
        heartbeat_sent
          True if the heartbeat message was sent, otherwise false.
        sock
          An open socket object.
        
        """
        if self.hrtbt.value == "Off":
            log.debug("No heartbeat this round, .HRTBT is off.")
            return False
        # Build TCP trigger flags
        flags = 0
        if bool(self.itrig.value):
            flags |= 0b1
        if bool(self.isup.value):
            flags |= 0b10
        # Prepare the UDP message
        next_heartbeat = self.val.value + 1
        message = heartbeat_message(
            magic_number=self.hmag.value,
            incarnation=self.incarnation,
            current_time=time.time(),
            heartbeat_value=next_heartbeat,
            period=self.hprd.value,
            flags=flags,
            return_port=self.iport.value,
            user_message=self.msg.value,
            ioc_name=self.iocnm.value,
        )
        # Send the message
        addr, port = self.server_address()
        if addr is not None and port is not None:
            print(f"Sending UDP to {(addr, port)}, #{next_heartbeat}")
            await self.send_udp_message(message=message, address=(addr, port))
            # Update the heartbeat counter
            await self.val.write(next_heartbeat)
        else:
            log.debug(f"Skipping heartbeat, {(addr, port)} invalid.")

    async def send_udp_message(self, message, address):
        """Open a socket and deliver the *message* via UDP to *address*."""
        with self.socket() as sock:
            sock.connect(address)
            loop = self.async_lib.get_running_loop()
            await loop.sock_sendall(sock=sock, data=message)
    
    val = pvproperty(
        name=".VAL",
        value=0,
        dtype=int,
        doc="Heartbeat Value",
        read_only=True
    )

    @val.scan(HEARTBEAT_PERIOD)
    async def val(self, instance, async_lib):
        # Send heartbeat message
        await self.send_heartbeat()

    @val.startup
    async def val(self, instance, async_lib):
        self.async_lib = async_lib.library
        self.incarnation = time.time()
        await self.rhost.write(self.default_remote_host)
        await self.rport.write(self.default_remote_port)

    rhost = pvproperty(
        name=".RHOST",
        value="",
        dtype=ChannelType.STRING,
        doc="Remote Host Name or IP Address",
        read_only=True,
    )
    @rhost.putter
    async def rhost(self, instance, value):
        addr = await self.resolve_hostname(value)
        await self.raddr.write(addr)
    
    raddr = pvproperty(
        name=".RADDR",
        value="",
        dtype=ChannelType.STRING,
        doc="Remote Host IP Address",
        read_only=True,
    )
    rport = pvproperty(
        name=".RPORT",
        value=0,
        dtype=int,
        doc="Remote Host UDP Port Number",
        read_only=True,
    )
    rrsts = pvproperty(
        name=".RRSTS",
        value=HostReadStatus.IDLE,
        dtype=HostReadStatus,
        doc="Remote Host Read Status",
        read_only=True,
    )
    ahost = pvproperty(
        name=".AHOST",
        value="",
        dtype=ChannelType.STRING,
        doc="Aux. Remote Host Name or IP Address",
        read_only=False,
    )
    @ahost.putter
    async def ahost(self, instance, value):
        addr = await self.resolve_hostname(value)
        await self.aaddr.write(addr)

    aaddr = pvproperty(
        name=".AADDR",
        value="",
        dtype=ChannelType.STRING,
        doc="Aux. Remote Host IP Address",
        read_only=True,
    )
    aport = pvproperty(
        name=".APORT",
        value=0,
        dtype=int,
        doc="Aux. Remote Host UDP Port Number",
        read_only=False,
    )
    arsts = pvproperty(
        name=".ARSTS",
        value=HostReadStatus.IDLE,
        dtype=HostReadStatus,
        doc="Aux. Remote Host Read Status",
        read_only=True,
    )
    hrtbt = pvproperty(
        name=".HRTBT", value="Off", dtype=bool, doc="Heartbeating State", read_only=False
    )
    hprd = pvproperty(
        name=".HPRD", value=HEARTBEAT_PERIOD, dtype=int, doc="Heartbeat Period", read_only=True
    )
        
    iocnm = pvproperty(
        name=".IOCNM",
        value="",
        dtype=ChannelType.STRING,
        doc="IOC Name Value",
        read_only=True,
    )
    @iocnm.startup
    async def iocnm(self, instance, asyncio_lib):
        """Set the IOC name based on the following, in order:

        1. Given as *ioc_name* to the alive record constructor.
        2. IOC environmental variable
        3. Prefix of the parent
        
        """
        # Determine best ioc name
        if self.default_ioc_name is not None:
            # Use explicit initialization value
            ioc_name = self.default_ioc_name
        elif "IOC" in os.environ.keys():
            # Use environmental variable
            ioc_name = os.environ['IOC']
        elif self.parent is not None:
            # Default, use this group's parent's prefix
            ioc_name = self.parent.prefix.strip(' .:')
        else:
            # Could not determine the ioc name
            raise NoIOCName("AliveGroup has no IOC name. "
                            "Please provide *ioc_name* init parameter, "
                            "or set *IOC* environment variable.")
        # Set IOC name for later sending to the alive daemon
        await instance.write(ioc_name)
        
    hmag = pvproperty(
        name=".HMAG",
        value=305419896,
        dtype=int,
        doc="Heartbeat Magic Number",
        read_only=True,
    )
    msg = pvproperty(
        name=".MSG", value=0, dtype=int, doc="Message to Send", read_only=False
    )
    iport = pvproperty(
        name=".IPORT",
        value=0,
        dtype=int,
        doc="TCP Information Port Number",
        read_only=True,
    )
    ipsts = pvproperty(
        name=".IPSTS",
        value=InformationPortStatus.UNDETERMINED,
        dtype=InformationPortStatus,
        doc="Information Port Status",
        read_only=True,
    )
    itrig = pvproperty(
        name=".ITRIG",
        value=False,
        dtype=bool,
        doc="Trigger Information Request",
        read_only=False,
    )
    isup = pvproperty(
        name=".ISUP",
        value=False,
        dtype=bool,
        doc="Suppress Information Requests",
        read_only=False,
    )
    ver = pvproperty(
        name=".VER",
        value="5.1.3",
        dtype=ChannelType.STRING,
        doc="Record Version",
        read_only=True,
    )
    evd1 = pvproperty(
        name=".EVD1",
        value="",
        dtype=ChannelType.STRING,
        doc="Default Environment Variable Name 1",
        read_only=True,
    )
    evd16 = pvproperty(
        name=".EVD16",
        value="",
        dtype=ChannelType.STRING,
        doc="Default Environment Variable Name 16",
        read_only=True,
    )
    ev1 = pvproperty(
        name=".EV1",
        value="",
        dtype=ChannelType.STRING,
        doc="Environment Variable Name 1",
        read_only=False,
    )
    ev16 = pvproperty(
        name=".EV16",
        value="",
        dtype=ChannelType.STRING,
        doc="Environment Variable Name 16",
        read_only=False,
    )
