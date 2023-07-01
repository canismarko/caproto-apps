from pathlib import Path
from unittest import mock
import asyncio

import pytest
from caproto.server import PVGroup, SubGroup
from caproto.asyncio.server import AsyncioAsyncLayer

from caprotoapps import manager

class MockIOC(PVGroup):
    manager = SubGroup(manager.ManagerGroup,
                       prefix="25idc",
                       script="myuser@myhost:/path/to/script")


@pytest.fixture
def mock_ioc():
    ioc = MockIOC(prefix="test_ioc:")
    ioc.manager.runner = mock.MagicMock()
    ioc.manager.async_lib = asyncio
    # ioc.alive.send_udp_message = mock.AsyncMock()
    # ioc.alive
    yield ioc


@pytest.fixture
def mock_manager(mock_ioc):
    yield mock_ioc.manager


def test_parse_remote_script_location():
    result = manager.parse_script_location(
        "my_user@myhost:/path/to/script"
    )
    user, host, path = result
    assert user == "my_user"
    assert host == "myhost"
    assert path == Path("/path/to/script")


def test_parse_local_script_location():
    result = manager.parse_script_location(
        "/path/to/script"
    )
    user, host, path = result
    assert user == None
    assert host == None
    assert path == Path("/path/to/script")


def test_bcda_runner():
    runner = manager.BCDARunner(script_path=Path("/path/to/script"))
    runner.execute_script = mock.MagicMock()
    # Check that the start method executes commands
    runner.start_ioc()
    # Was the script executed?
    assert runner.execute_script.called
    assert runner.execute_script.call_args.kwargs['args'] == ['/path/to/script', 'start']
    # Check that the stop method executes commands
    runner.execute_script.reset_mock()
    runner.stop_ioc()
    # Was the script executed?
    assert runner.execute_script.called
    assert runner.execute_script.call_args.kwargs['args'] == ['/path/to/script', 'stop']
    # Check that the restart method executes commands
    runner.execute_script.reset_mock()
    runner.restart_ioc()
    # Was the script executed?
    assert runner.execute_script.called
    assert runner.execute_script.call_args.kwargs['args'] == ['/path/to/script', 'restart']
    # Check the status method returns the IOC status if on
    runner.execute_script.return_value = "25idc is running (pid=717809) in a screen session (pid=717808)"
    assert runner.ioc_status() == manager.IOCStatus.Running
    # Check the status method returns the IOC status if off
    runner.execute_script.return_value = "25idc is not running"
    assert runner.ioc_status() == manager.IOCStatus.Stopped


def test_manager_loads_runner():
    # First a local script
    local_manager = manager.ManagerGroup(prefix="manager", script="/path/to/script")
    assert isinstance(local_manager.runner, manager.BCDARunner)
    assert local_manager.runner.script_path == Path("/path/to/script")
    # Now a remote script via SSH
    ssh_manager = manager.ManagerGroup(prefix="manager", script="myuser@myhost:/path/to/script")
    assert isinstance(ssh_manager.runner, manager.BCDASSHRunner)
    assert ssh_manager.runner.user == "myuser"
    assert ssh_manager.runner.host == "myhost"
    assert ssh_manager.runner.script_path == Path("/path/to/script")
    

@pytest.mark.asyncio
async def test_start_ioc(mock_manager):
    await mock_manager.start.write(1)
    assert mock_manager.start.value == "Off"
    assert mock_manager.runner.start_ioc.called


@pytest.mark.asyncio
async def test_stop_ioc(mock_manager):
    await mock_manager.stop.write(1)
    assert mock_manager.stop.value == "Off"
    assert mock_manager.runner.stop_ioc.called


@pytest.mark.asyncio
async def test_restart_ioc(mock_manager):
    await mock_manager.restart.write(1)
    assert mock_manager.restart.value == "Off"
    assert mock_manager.runner.restart_ioc.called


@pytest.mark.asyncio
async def test_ioc_status(mock_manager):
    assert mock_manager.status.value == "Unknown"


@pytest.mark.asyncio
async def test_ioc_console(mock_manager):
    assert mock_manager.console_command.value == ""    

    
