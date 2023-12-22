import asyncio
import socket
import logging
import warnings

from labjack import ljm

log = logging.getLogger(__name__)


DRIVER_VERSION = "3.0.0"  # Which EPICS driver version does this mimic?


DEVICE_TYPES = {
    -4: "SIM",
    4: "T4",
    7: "T7",
    8: "T8",
}


class LabJackDisconnected(IOError):
    """The device is not connected."""

    pass


class LabJackDriver:
    """A driver supporting a labjack IOC.

    A wrapper around the relevant backend library, by default
    Labjack's ljm library.

    """

    _handle = None
    identifier: str
    num_ai: int

    def __init__(self, identifier: str, num_ai: int = 16, *, api=ljm):
        """Parameters
        ==========
        identifier
          Which labjack should be controlled. Can either be an
          internet address, a USB device, or "-2" for simulated
          labjack.
        api
          The API library to use. By default will use Labjack's LJM
          library. This is intended for writing tests.
        num_ai
        """
        self.api = api
        self.identifier = identifier
        self.num_ai = num_ai

    @property
    def handle(self):
        if self._handle is None:
            raise LabJackDisconnected(self.identifier)
        return self._handle

    async def connect(self):
        """Connect the driver to the actual labjack device."""
        # Resolve the hostname if possible
        try:
            self.identifier = socket.gethostbyname(self.identifier)
        except socket.gaierror:
            msg = "Could not resolve labjack hostname '{self.identifier}'"
            log.info(msg)
        # Create the device connection
        loop = asyncio.get_running_loop()
        self._handle = await loop.run_in_executor(
            None, self.api.openS, "ANY", "ANY", self.identifier
        )
        print(self._handle)

    @property
    def ljm_version(self):
        return ljm.__version__

    async def device_info(self) -> dict:
        """Get basic information about the device.

        This is only meant for info that will not change while the
        device is connected, like device type and serial number.

        Returns
        =======
        dict
          The device info as a dictionary.

        """
        loop = asyncio.get_running_loop()
        # Get handle info (model number and connection details
        handle_info = await loop.run_in_executor(
            None, self.api.getHandleInfo, self.handle
        )
        device_type, conn_type, serial, ip, port, packet_size = handle_info
        # Get the firmware version
        firmware = await loop.run_in_executor(
            None, self.api.eReadName, self.handle, "FIRMWARE_VERSION"
        )
        # Build the device info dictionary
        info = {
            "driver_version": DRIVER_VERSION,
            "model_name": DEVICE_TYPES[device_type],
            "serial_number": str(serial),
            "firmware_version": str(firmware),
        }
        return info

    async def read_registers(self, names):
        """Read the requested register names from the device."""
        loop = asyncio.get_running_loop()
        values = await loop.run_in_executor(
            None, self.api.eReadNames, self.handle, len(names), names
        )
        result = {name: val for name, val in zip(names, values)}
        return result

    async def read_register(self, name):
        """Read the single register from the device by name."""
        loop = asyncio.get_running_loop()
        value = await loop.run_in_executor(None, self.api.eReadName, self.handle, name)
        return value

    async def write_register(self, name, value):
        """Write a value to the given register."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.api.eWriteName, self.handle, name, value
        )

    async def read_inputs(self):
        registers = ["DIO_STATE", "DIO_DIRECTION"]
        registers.extend([f"AIN{N}" for N in range(self.num_ai)])
        values = await self.read_registers(registers)
        # Do some type conversion since everything is a float in LJM
        for key in ["DIO_STATE", "DIO_DIRECTION"]:
            values[key] = int(values[key])
        return values

    async def write_digital_output(self, dio_num, value):
        """Write a new *value* to a digital output register *dio_num*.

        To set DIO3 to HIGH, use

        .. code:: python

            await driver.write_digital_output(dio_num=3, value=1)

        """
        name = f"DIO{dio_num}"
        await self.write_register(name, value)

    async def write_analog_output(self, ao_num, value):
        """Write a new *value* to a analog output register *ao_num*.

        To set DAC1 to 2.2, use

        .. code:: python

            await driver.write_analog_output(ao_num=1, value=2.2)

        """
        name = f"DAC{ao_num}"
        await self.write_register(name, value)

    async def write_digital_direction(self, dio_num: int, direction: int):
        """Set the given digital I/O pin to be either input or output.

        The ping is determined by *dio_num*, and the direction is
        determine by *direction* (0 = input, 1 = output).

        """
        # Get the current directions from the device
        register = "DIO_DIRECTION"
        dir_ = await self.read_register(register)
        # Determine the new direction by bitwise manipulation
        if direction == 0:
            dir_ &= ~(1 << dio_num)
        elif direction == 1:
            dir_ |= 1 << dio_num
        # Send the new directions to the device
        return await self.write_register(register, dir_)
