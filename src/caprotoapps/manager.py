"""A PV group that can start, stop, restart, etc another IOC.

Example usage:

.. code-block:: python

    class RobotIOC(PVGroup):
        manager = SubGroup(ManagerGroup,
                           prefix="25idc",
                           script="myuser@myhost:/path/to/script")

"""


#!/usr/bin/env python3
from contextlib import contextmanager
from collections import OrderedDict
from pathlib import Path
import logging
import sys
import time
import asyncio
from functools import partial
from threading import Lock
import subprocess
from subprocess import PIPE, STDOUT
import re
import os
import getpass
import grp
import enum
import struct
import socket
from enum import IntEnum
from typing import Sequence, Mapping, Optional

from fabric import Connection
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

from . import exceptions

log = logging.getLogger(__name__)


script_re = re.compile(
    "^(?:(?P<user>.+)@)?"  # Username (optional)
    "(?:(?P<host>.+):)?"  # Host (optional)
    "(?P<path>/.+)$"  # Script location
)


def parse_script_location(
    script: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract key parameters from a script path.

    Accepts a script specifier in the form:

      [[user@]host:]/path/to/script

    Returns
    =======
    user
      The remote username for the IOC. May be None.
    host
      The remote host for the IOC. May be None.
    script
      The location of the script for starting/stopping the IOC
    """
    match = script_re.match(script)
    # Extract matched groups
    user = match.group("user")
    host = match.group("host")
    path = Path(match.group("path"))
    return (user, host, path)


class IOCStatus(IntEnum):
    """Whether the IOC is running or not."""

    Unknown = 0
    Stopped = 1
    Running = 2


class BaseRunner:
    def __init__(self, script_path: Path):
        self.script_path = script_path

    def start_ioc(self):
        """Start the managed IOC."""
        raise NotImplementedError

    def stop_ioc(self):
        """Stop the managed."""
        raise NotImplementedError

    def restart_ioc(self):
        """Restart the managed IOC."""
        raise NotImplementedError

    def ioc_status(self) -> int:
        """Determine whether the IOC is running.

        Returns
        =======
        status
          The running status of the IOC, based on ``IOCStatus`` enum.

        """
        raise NotImplementedError

    def execute_script(self, args):
        """Execute *args* on target machine."""
        raise NotImplementedError


class BCDARunner(BaseRunner):
    def __init__(self, script_path: Path):
        self.script_path = script_path

    def execute_script(self, args):
        """Execute *args* on local machine."""
        result = subprocess.run(args, stdout=PIPE, stderr=STDOUT)
        response = result.stdout.decode("utf-8").strip()
        return response

    def start_ioc(self):
        """Start the managed IOC."""
        run_args = [str(self.script_path), "start"]
        self.execute_script(args=run_args)

    def stop_ioc(self):
        """Stop the managed."""
        run_args = [str(self.script_path), "stop"]
        self.execute_script(args=run_args)

    def restart_ioc(self):
        """Restart the managed IOC."""
        run_args = [str(self.script_path), "restart"]
        self.execute_script(args=run_args)

    def ioc_status(self) -> int:
        """Determine whether the IOC is running.

        Returns
        =======
        status
          The running status of the IOC, based on ``IOCStatus`` enum.

        """
        run_args = [str(self.script_path), "status"]
        response = self.execute_script(run_args)
        # Parse the status response
        match = re.match(r"^\S+ is (not)? ?running", response)
        if match is None:
            # Garbled response
            log.warning(f"Could not parse IOC status response: {response}")
            return IOCStatus.Unknown
        # Determine the status from the response
        is_stopped = match.group(1) == "not"
        if is_stopped:
            return IOCStatus.Stopped
        else:
            return IOCStatus.Running


class BCDASSHRunner(BCDARunner):
    ssh_connection: Connection = None

    def __init__(self, user: str, host: str, script_path: Path):
        self.user = user
        self.host = host
        super().__init__(script_path=script_path)

    def execute_script(self, args):
        """Execute *args* on local machine."""
        # Establish connection
        if self.ssh_connection is None:
            self.ssh_connection = Connection(host=self.host, user=self.user)
        # Send command to the remote host
        cmd = " ".join(args)
        result = self.ssh_connection.run(cmd, hide="out")
        # Parse the response
        response = result.stdout.strip()
        return response


def guess_runner(script: str):
    """Determine which IOC runner to use based on the script type."""
    user, host, path = parse_script_location(script)
    # Check for SSH connections (BCDA style)
    use_ssh = (user is not None) and (host is not None)
    if use_ssh:
        return BCDASSHRunner(user=user, host=host, script_path=path)
    # Last option, use local script
    return BCDARunner(script_path=path)


class ManagerGroup(PVGroup):
    """A caproto PV group for managing a separate IOC.

    Parameters
    ==========
    script
      The location of the script used to control the target IOC.
    runner
      An instance of ``BaseRunner`` or one of its subclasses. If
      omitted, a default runner will be used based on *script*.
    allow_start
      Whether or not it is permitted to start the IOC through this
      manager
    allow_stop
      Whether or not it is permitted to stop the IOC through this
      manager

    """

    def __init__(
        self,
        *args,
        script: str,
        runner: BaseRunner = None,
        allow_start: bool = True,
        allow_stop: bool = True,
        **kwargs,
    ):
        self._script = script
        self.allow_start = allow_start
        self.allow_stop = allow_stop
        # Set up a runner if one does not exist
        if runner is None:
            self.runner = guess_runner(script)
        else:
            self.runner = runner
        super().__init__(*args, **kwargs)

    # PVs for changing the IOC state
    startable = pvproperty(
        name="startable",
        value="On",
        dtype=bool,
        read_only=True,
        doc="Can the remote IOC be started.",
    )

    @startable.startup
    async def startable(self, instance, async_lib):
        is_startable = "On" if self.allow_start else "Off"
        await instance.write(is_startable)

    start = pvproperty(
        name="start", value="Off", dtype=bool, doc="Start the remote IOC."
    )

    @start.putter
    async def start(self, instance, value):
        """Trigger a remote IOC to start."""
        # Confirm we are allow to start the IOC
        if self.startable.value != "On":
            msg = "Cannot start IOC. Provide *allow_start=True* to enable remote starting."
            raise exceptions.NotPermitted(msg)
        # Execute the runner's control function
        loop = self.async_lib.get_running_loop()
        await loop.run_in_executor(None, self.runner.start_ioc)
        # Return the trigger to its default value
        return "Off"

    @start.startup
    async def start(self, instance, async_lib):
        # Just here to get the async lib on startup
        self.async_lib = async_lib.library

    # PVs for changing the IOC state
    stoppable = pvproperty(
        name="stoppable",
        value="On",
        dtype=bool,
        read_only=True,
        doc="Can the remote IOC be stopped.",
    )

    @stoppable.startup
    async def stoppable(self, instance, async_lib):
        is_stoppable = "On" if self.allow_stop else "Off"
        await instance.write(is_stoppable)

    stop = pvproperty(name="stop", value="Off", dtype=bool, doc="Stop the remote IOC.")

    @stop.putter
    async def stop(self, instance, value):
        # Confirm we are allow to start the IOC
        if self.stoppable.value != "On":
            msg = (
                "Cannot stop IOC. Provide *allow_stop=True* to enable remote stopping."
            )
            raise exceptions.NotPermitted(msg)
        # Execute the runner's control function
        loop = self.async_lib.get_running_loop()
        await loop.run_in_executor(None, self.runner.stop_ioc)
        # Return the trigger to its default value
        return "Off"

    restart = pvproperty(
        name="restart", value="Off", dtype=bool, doc="Restart the remote IOC."
    )

    @restart.putter
    async def restart(self, instance, value):
        # Confirm we are allowed to restart the IOC
        if (self.startable.value != "On") or (self.stoppable.value != "On"):
            msg = (
                "Cannot stop IOC. Provide *allow_stop=True* to enable remote stopping."
            )
            raise exceptions.NotPermitted(msg)
        # Execute the runner's control function
        loop = self.async_lib.get_running_loop()
        await loop.run_in_executor(None, self.runner.restart_ioc)
        # Return the trigger to its default value
        return "Off"

    # PVs for monitoring the IOC state
    status = pvproperty(
        name="status",
        value="Unknown",
        enum_strings=["Unknown", "Stopped", "Running"],
        record="mbbi",
        dtype=ChannelType.ENUM,
        doc="The current status of the IOC.",
    )

    @status.scan(1, use_scan_field=True)
    async def status(self, instance, async_lib):
        loop = self.async_lib.get_running_loop()
        new_status = await loop.run_in_executor(None, self.runner.ioc_status)
        old_status = getattr(IOCStatus, instance.value)
        if new_status != old_status:
            await instance.write(new_status)

    console_command = pvproperty(
        name="console",
        value="",
        dtype=ChannelType.STRING,
        doc="The command needed to connect to the remote console.",
    )
