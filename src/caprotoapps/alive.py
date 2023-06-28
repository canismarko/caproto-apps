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
from collections import OrderedDict
import logging
import sys
import time
import asyncio
from functools import partial
from threading import Lock
import re
import os
import getpass
import grp
import enum
import struct
import socket
from typing import Sequence, Mapping

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


class InvalidServerAddress(ValueError):
    ...


class NoIOCName(AttributeError):
    """Could not discern a valid name for this IOC."""

    ...


def envvar_property(num: int):
    return pvproperty(
        name=f".EV{num}",
        value="",
        dtype=ChannelType.STRING,
        doc=f"Environment Variable Name {num}",
        read_only=False,
    )


def envvar_default_property(num: int, value: str = ""):
    return pvproperty(
        name=f".EVD{num}",
        value=value,
        dtype=ChannelType.STRING,
        doc=f"Default Environment Variable Name {num}",
        read_only=True,
    )

def env_messages(*, version: int=5, ioc_type: int, env_variables: Sequence):
    """Construct the environmental variables message.

    Message is suitable to send back to the remote host.

    """
    # Get the environmental variable messages
    env_messages = []
    encoding = "ascii"
    for key in env_variables:
        name = key.encode(encoding)
        val = os.environ.get(key, "")
        val = val.encode(encoding)
        msg = b"".join([
            struct.pack(">B", len(name)),  # name length
            name,                          # variable name
            struct.pack(">H", len(val)),   # value length
            val,                           # variable value
        ])
        env_messages.append(msg)
    # Build the extra os-specific info
    extra_messages = []
        # Extra data depending on IOC type
    if ioc_type == IOCType.LINUX:
        uid = getpass.getuser().encode(encoding)
        uid_msg = b"".join([
            struct.pack(">B", len(uid)),  # string length
            uid,
        ])
        gid = grp.getgrgid(os.getegid()).gr_name.encode(encoding)
        gid_msg = b"".join([
            struct.pack(">B", len(gid)),  # string length
            gid,
        ])
        hostname = socket.gethostname().encode(encoding)
        hostname_msg = b"".join([
            struct.pack(">B", len(hostname)),  # string length
            hostname,
        ])
        extra_messages = [uid_msg, gid_msg, hostname_msg]
        log.debug(f"Sending extra info: {uid_msg=}, {gid_msg=}, {hostname_msg=}")
    # Build the header message
    HEADER_LENGTH = 10
    body_length = sum([len(msg) for msg in env_messages])
    extra_info_length = sum([len(msg) for msg in extra_messages])
    message_length = HEADER_LENGTH + body_length + extra_info_length
    num_variables = len(env_messages)
    header_message = b""
    header_message += struct.pack(">H", version)
    header_message += struct.pack(">H", ioc_type)
    header_message += struct.pack(">I", message_length)
    header_message += struct.pack(">H", num_variables)
    yield header_message
    yield from env_messages
    yield from extra_messages

def heartbeat_message(
    magic_number: int,
    incarnation: int | float,
    current_time: int | float,
    heartbeat_value: int,
    period: int | float,
    request_read: bool,
    suppress_environment: bool,
    return_port: int,
    user_message: int,
    ioc_name: str,
):
    """Create a UDP message that tells the server the IOC is alive.

    Convert the various parameters into a UDP message based on the
    EPICS alive record specification:

    https://epics-modules.github.io/alive/aliveRecord.html

    *incarnation* and *current_time* are expected to be in unix time
     and will be converted to epics time.

    """
    PROTOCOL_VERSION = 5
    # Build TCP trigger flags
    flags = 0
    if request_read:
        flags |= 0b1
    if suppress_environment:
        flags |= 0b10
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
    msg += ioc_name.encode("ascii")
    # Null terminator
    msg += b"\x00"
    return msg


def epics_time(unix_time):
    return unix_time - 631152000


class IOCType(enum.IntEnum):
    GENERIC = 0
    VX_WORKS = 1
    LINUX = 2
    DARWIN = 3
    WINDOWS = 4


class AliveGroup(PVGroup):
    _sock = None
    incarnation: int
    default_ioc_name: str
    default_remote_host: str
    default_remote_port: int
    _env: OrderedDict = None

    class HostReadStatus(enum.IntEnum):
        Idle = 0
        Queued = 1
        Due = 2
        Overdue = 3

    class InformationPortStatus(enum.IntEnum):
        Undetermined = 0
        Operable = 1
        Inoperable = 2

    def __init__(
        self,
        remote_host: str = "localhost",
        remote_port: int = 5678,
        ioc_name: str = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.default_remote_host = remote_host
        self.default_remote_port = remote_port
        self.default_ioc_name = ioc_name

    @contextmanager
    def socket(self):
        # Create the socket
        if self._sock is None:
            self._sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK
            )
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
            None,
            socket.gethostbyname,
            hostname,
        )
        log.debug(f"Resolved {hostname=} to {addr=}")
        return addr

    def server_address(self, use_aux: bool = False):
        """Determine which server to use for sending heartbeats.

        Checks the .RADDR and .AADDR fields to determine which to use.

        Parameters
        ==========
        use_aux
          If true, return the auxillary host instead of the regular
          remote host.

        Returns
        =======
        addr
          The IP address of the host.
        port
          The port for the heartbeat message.

        """
        invalid_addrs = ["", "invalid AHOST", "invalid RHOST"]
        # Get the PV's values for addr and port
        if use_aux:
            addr = self.aaddr.value
            port = self.aport.value
        else:
            addr = self.raddr.value
            port = self.rport.value
        # Check for a valid remote host
        addr_is_valid = addr not in invalid_addrs
        port_is_valid = port > 0
        if addr_is_valid and port_is_valid:
            return (addr, port)
        else:
            raise InvalidServerAddress((addr, port))
    
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
        # Prepare the UDP message
        next_heartbeat = self.val.value + 1
        make_message = partial(heartbeat_message, 
            magic_number=self.hmag.value,
            incarnation=self.incarnation,
            current_time=time.time(),
            heartbeat_value=next_heartbeat,
            period=self.hprd.value,
            suppress_environment=self.isup.value == "On",
            return_port=self.iport.value,
            user_message=max(0, self.msg.value),
            ioc_name=self.iocnm.value,
        )
        # Send the message
        sent_to_remote_host = False
        try:
            addr, port = self.server_address()
        except InvalidServerAddress:
            pass
        else:
            request_read = self.rrsts.value in ["Queued", "Due", "Overdue"]
            message = make_message(request_read=request_read)
            await self.send_udp_message(message=message, address=(addr, port))
            sent_to_remote_host = True
            # Update read status variable
            match self.rrsts.value:
                case "Queued":
                    await self.rrsts.write("Due")
                case "Due":
                    await self.rrsts.write("Overdue")
        # Send the message to the aux host
        sent_to_aux_host = False
        try:
            addr, port = self.server_address(use_aux=True)
        except InvalidServerAddress:
            pass
        else:
            request_read = (self.arsts.value=="Queued")
            message = make_message(request_read=request_read)
            await self.send_udp_message(message=message, address=(addr, port))
            sent_to_aux_host = True
            # Update read status variable
            match self.arsts.value:
                case "Queued":
                    await self.arsts.write("Due")
                case "Due":
                    await self.arsts.write("Overdue")
        # Update the read status PVs
        if sent_to_remote_host or sent_to_aux_host:
            # Update the heartbeat counter            
            await self.val.write(next_heartbeat)
        else:
            log.debug(f"Skipping heartbeat, no valid host set.")
            

    async def send_udp_message(self, message, address):
        """Open a socket and deliver the *message* via UDP to *address*."""
        log.debug(f"Sending UDP to {address}: {message}")
        with self.socket() as sock:
            sock.connect(address)
            loop = self.async_lib.get_running_loop()
            await loop.sock_sendall(sock=sock, data=message)

    async def handle_env_request(self, reader, writer):
        # Check for conditions that result in no data being sent
        remote_addr, remote_port = writer.get_extra_info("peername")
        bad_hostname = (remote_addr not in [self.raddr.value, self.aaddr.value])
        is_suppressed = self.isup.value not in ["Off", False, 0]
        if is_suppressed:
            log.debug(f"Suppressing environmental variable reply: {self.isup.value=}")
        if bad_hostname:
            log.debug(f"Refused env request from host {remote_addr}. Expected {self.raddr.value}")
        if is_suppressed or bad_hostname:
            # Invalid connection: close immediately
            writer.close()
            await writer.wait_closed()
            return
        # Send the env variables message
        messages = env_messages(
            ioc_type=self.ioc_type,
            env_variables=list(self.env_variables.keys()),
            
        )
        for msg in messages:
            log.debug(f"Sending environment message: {msg}")
            writer.write(msg)
            await writer.drain()
        writer.close()
        await writer.wait_closed()
        # Update read status PVs
        if remote_addr == self.raddr.value:
            await self.rrsts.write("Idle")
        if remote_addr == self.aaddr.value:
            await self.arsts.write("Idle")

    @property
    def env_variables(self) -> OrderedDict:
        """The dict of environmental variables that are to be returned to the
        daemon.

        """
        evars = OrderedDict()
        for i in range(1, 17):
            # Check custom values first
            key = getattr(self, f"ev{i}").value
            if len(key) <= 0:
                # No custom value, use default value instead
                key = getattr(self, f"evd{i}").value
            # Make sure there's a variable there
            if len(key) > 0:
                evars[key] = os.environ.get(key, "")
        return evars
    
    val = pvproperty(
        name=".VAL", value=0, dtype=int, doc="Heartbeat Value", read_only=True
    )

    async def check_env(self, instance, async_lib=None):
        """Update read status PVs if environmental variables have changed."""
        new_vars = self.env_variables
        old_vars = self._env
        if new_vars != old_vars:
            # Environment has changed, so queue read status updates
            await self.rrsts.write("Queued")
            await self.arsts.write("Queued")
            self._env = new_vars
            

    @property
    def ioc_type(self):

        """Determine the IOC type based on the current platform."""
        if sys.platform.startswith("linux"):
            return IOCType.LINUX
        elif sys.platform.startswith("darwin"):
            return IOCType.DARWIN
        elif sys.platform.startswith("win32"):
            return IOCType.WINDOWS
        else:
            return IOCType.GENERIC

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
        value=HostReadStatus.Queued,
        dtype=HostReadStatus,
        doc="Remote Host Read Status",
        read_only=True,
    )
    rrsts = rrsts.scan(1)(check_env)

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
        value=HostReadStatus.Queued,
        dtype=HostReadStatus,
        doc="Aux. Remote Host Read Status",
        read_only=True,
    )
    hrtbt = pvproperty(
        name=".HRTBT",
        value="On",
        dtype=bool,
        doc="Heartbeating State",
        read_only=False,
    )
    hprd = pvproperty(
        name=".HPRD",
        value=HEARTBEAT_PERIOD,
        dtype=int,
        doc="Heartbeat Period",
        read_only=True,
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
            ioc_name = os.environ["IOC"]
        elif self.parent is not None:
            # Default, use this group's parent's prefix
            ioc_name = self.parent.prefix.strip(" .:")
        else:
            # Could not determine the ioc name
            raise NoIOCName(
                "AliveGroup has no IOC name. "
                "Please provide *ioc_name* init parameter, "
                "or set *IOC* environment variable."
            )
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
    @iport.startup
    async def iport(self, instance, async_lib):
        """Start a TCP server for env request from the alive daemon."""
        try:
            # Start the server
            tcp_server = await async_lib.library.start_server(
                client_connected_cb=self.handle_env_request,
                port=instance.value,
            )            
        except Exception as exc:
            # Failed
            await self.ipsts.write(self.InformationPortStatus.Inoperable)
            log.error(f"Could not listen for TCP packets: {exc}")
        else:
            log.info(f"Listening for environmental variable requests: {tcp_server}")
            # Determine listening port
            ip4socket = [s for s in tcp_server.sockets if s.family == socket.AF_INET][0]
            listen_port = ip4socket.getsockname()[1]
            await instance.write(listen_port)
            await self.ipsts.write(self.InformationPortStatus.Operable)
        
    ipsts = pvproperty(
        name=".IPSTS",
        value=InformationPortStatus.Undetermined,
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
    @itrig.putter
    async def itrig(self, instance, value):
        await self.rrsts.write(self.HostReadStatus.Queued)
        await self.arsts.write(self.HostReadStatus.Queued)
        return "Off"
    
    isup = pvproperty(
        name=".ISUP",
        value="Off",
        dtype=bool,
        doc="Suppress Information Requests",
        read_only=False,
    )
    ver = pvproperty(
        name=".VER",
        value="1.4.1",
        dtype=ChannelType.STRING,
        doc="Record Version",
        read_only=True,
    )
    evd1 = envvar_default_property(1, "ENGINEER")
    evd2 = envvar_default_property(2, "LOCATION")
    evd3 = envvar_default_property(3, "GROUP")
    evd4 = envvar_default_property(4, "STY")
    evd5 = envvar_default_property(5, "PREFIX")
    evd6 = envvar_default_property(6)
    evd7 = envvar_default_property(7)
    evd8 = envvar_default_property(8)
    evd9 = envvar_default_property(9)
    evd10 = envvar_default_property(10)
    evd11 = envvar_default_property(11)
    evd12 = envvar_default_property(12)
    evd13 = envvar_default_property(13)
    evd14 = envvar_default_property(14)
    evd15 = envvar_default_property(15)
    evd16 = envvar_default_property(16)
    
    ev1 = envvar_property(1)
    ev2 = envvar_property(2)
    ev3 = envvar_property(3)
    ev4 = envvar_property(4)
    ev5 = envvar_property(5)
    ev6 = envvar_property(6)
    ev7 = envvar_property(7)
    ev8 = envvar_property(8)
    ev9 = envvar_property(9)
    ev10 = envvar_property(10)
    ev11 = envvar_property(11)
    ev12 = envvar_property(12)
    ev13 = envvar_property(13)
    ev14 = envvar_property(14)
    ev15 = envvar_property(15)
    ev16 = envvar_property(16)
