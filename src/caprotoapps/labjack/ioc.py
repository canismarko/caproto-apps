"""PV groups for interacting with a LabJack data acquisition unit.

Currently the T4 is supported.

Example usage:

.. code-block:: python

    class BeamlineIOC(PVGroup):
        labjack_0 = SubGroup(LabJackT4, prefix="LabJack_T4_0:")

"""


#!/usr/bin/env python3
from contextlib import contextmanager
from importlib.metadata import version
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
import numpy as np

from .driver import LabJackDriver

log = logging.getLogger(__name__)


model_names = {
    0: "T4",
    1: "T7",
    2: "T7-Pro",
    3: "T8",
}


def ai_subgroup(num):
    """Create a caproto SubGroup for the given number of analog inputs."""
    subgroups = {}
    # Create pvproperties for each analog input
    for N in range(num):

        class AiGroup(PVGroup):
            ai_num: int = N
            
            value = pvproperty(
                name=f"Ai{N}",
                record="ai",
                read_only=True,
                doc="Analog input value. This is polled in the driver, so either period or I/O Intr scanning can be used.",
            )
            enable = pvproperty(
                name=f"AiEnable{N}",
                record="bo",
                doc="Enable flag for this analog input channel. Disabled inputs are not read by the poller. Unconnected inputs should be disabled to improve accuracy on active channels and to reduce the polling time.",
            )
            mode = pvproperty(
                name=f"AiMode{N}",
                record="mbbo",
                doc="Input mode for this analog input channel. Choices are Volts and 9 different thermocouple types.",
            )
            temp_units = pvproperty(
                name=f"AiTempUnits{N}",
                record="mbbo",
                doc="Temperature units for this analog input channel if a thermocouple mode is selected. Choices are “K”, “C”, and “F”.",
            )
            diff = pvproperty(
                name=f"AiDiff{N}",
                record="mbbo",
                doc="Selects 'Single-Ended' or 'Differential' input mode on the T7 and T7-PRO. The T4 is always single-ended and the T8 is always differential. The driver constructs the strings and values based on the model.",
            )
            range = pvproperty(
                name=f"AiRange{N}",
                record="mbbo",
                doc="Selects the input range for this analog input channel.\n\nOn the T4 the range is fixed at +-10V on channels 0-3 and 0-2.5 on channels 4-11.\n\nOn the T7 the range choices are +-10V, +-1V, +-0.1V, and +-0.01V.\n\nOn the T8 there are 11 ranges from +-11V to +-0.15V.\n\nThe driver constructs the strings and values based on the model.",
            )
            resolution = pvproperty(
                name=f"AiResolution{N}",
                record="mbbo",
                doc="Selects the input resolution for this analog input channel. High values of resolution result in lower noise and longer ADC conversion time.\n\nResolution 0 is the default resolution for that model.\n\nThe T4 supports resolutions 1-5.\n\nThe T7 supports resolutions 1-8.\n\nThe T7-PRO supports resolutions 1-12. 1-8 use the 16-bit ADC and 9-12 use the 24-bit ADC\n\nThe T8 supports resolutions 1-16. However, these are automatically selected by the Range, and this record has no effect?",
            )

            @value.scan(period=0.1, use_scan_field=True)
            async def value(self, instance, asynclib):
                await self.update_value(instance)

            async def update_value(self, instance):
                """Set the value PV from the cached value of the parent IOC."""
                # Get the cached value
                try:
                    cached_val = self.parent.parent._ai_cache[f"AIN{self.ai_num}"]
                except KeyError:
                    return
                # Set the PV value
                if cached_val != instance.value:
                    await instance.write(cached_val)

        subgroups[f"ai{N}"] = SubGroup(AiGroup, prefix="")
    # Create the PVGroup subclass with all the analog inputs
    return type("AnalogInputs", (PVGroup,), subgroups)


def ao_subgroup(num):
    """Create a caproto SubGroup for the given number of analog outputs."""
    subgroups = {}
    # Create pvproperties for each analog input
    for N in range(num):

        class AoGroup(PVGroup):
            value = pvproperty(name=f"Ao{N}", record="ao", doc="Analog output value.")
            tweak_value = pvproperty(
                name=f"Ao{N}TweakVal",
                record="ao",
                doc="The amount by which to tweak the out when the Tweak record is processed.",
            )
            tweak_up = pvproperty(
                name=f"Ao{N}TweakUp",
                record="calcout",
                doc="Tweaks the output up by TweakVal.",
            )
            tweak_down = pvproperty(
                name=f"Ao{N}TweakDown",
                record="calcout",
                doc="Tweaks the output down by TweakVal.",
            )

            @value.putter
            async def value(self, instance, value):
                """Write the new analog output value to the labjack."""
                old_val = instance.value
                # Send the new value to the device
                if value != old_val:
                    driver = self.parent.parent.driver
                    return await driver.write_analog_output(value=value, ao_num=N)

        subgroups[f"ao{N}"] = SubGroup(AoGroup, prefix="")
    # Create the PVGroup subclass with all the analog inputs
    return type("AnalogInputs", (PVGroup,), subgroups)


def dio_subgroup(num):
    """Create a caproto SubGroup for the given number of digial inputs/outputs."""
    subgroups = {}
    # Create pvproperties for each analog input
    for N in range(num):

        class DIOGroup(PVGroup):
            enum_values = {
                "Off": 0,
                "On": 1,
            }
            enum_directions = {
                "Input": 0,
                "Output": 1,
            }
            input = pvproperty(
                name=f"Bi{N}",
                value=False,
                record="bi",
                read_only=True,
                enum_strings=["Low", "High"],
                doc="",
            )
            output = pvproperty(
                name=f"Bo{N}",
                value=0,
                dtype=bool,
                record="bo",
                enum_strings=["Low", "High"],
                doc="",
            )
            direction = pvproperty(
                name=f"Bd{N}",
                value=False,
                record="bo",
                enum_strings=["In", "Out"],
                doc="",
            )

            @output.putter
            async def output(self, instance, value):
                """Write the new digital output value to the labjack."""
                # Convert from enum strings to 1's and 0's
                new_val = self.enum_values.get(value, value)
                old_val = self.enum_values.get(instance.value, instance.value)
                # Send the new value to the device driver
                if new_val != old_val:
                    driver = self.parent.parent.driver
                    return await driver.write_digital_output(value=new_val, dio_num=N)

            @direction.putter
            async def direction(self, instance, value):
                """Write the new digital output direction to the labjack."""
                # Convert from enum strings to 1's and 0's
                new_dir = self.enum_directions.get(value, value)
                old_dir = self.enum_directions.get(instance.value, instance.value)
                # Send the new value to the device driver
                if new_dir != old_dir:
                    driver = self.parent.parent.driver
                    return await driver.write_digital_direction(
                        dio_num=N, direction=new_dir
                    )

        subgroups[f"dio{N}"] = SubGroup(DIOGroup, prefix="")
    # Create the PVGroup subclass with all the analog inputs
    return type("DigitalIOs", (PVGroup,), subgroups)


class LabJackBase(PVGroup):
    """An IOC with PVs common to all Labjack devices.

    Does not include analog or digial I/O, since these differ from
    device-to-device.

    Most likely you want to use one of the subclasses that impelement
    a specific labjack T-series device.

    """
    _ai_cache: dict

    # Device functions
    firmware_version = pvproperty(
        name="FirmwareVersion",
        value="",
        record="stringin",
        read_only=True,
        doc="Device firmware version.",
    )
    serial_number = pvproperty(
        name="SerialNumber",
        record="stringin",
        read_only=True,
        value="",
        dtype=ChannelType.STRING,
        doc="Device serial number.",
    )
    device_temperature = pvproperty(
        name="DeviceTemperature",
        record="ai",
        read_only=True,
        doc="Device temperature. This is used as the cold junction reference temperature for thermocouple measurements. It has SCAN='5 second' which is fast enough for this slowly varying value.",
    )
    ljm_version = pvproperty(
        name="LJMVersion",
        record="stringin",
        read_only=True,
        value="",
        dtype=ChannelType.STRING,
        doc="Version of the LabJack LJM library.",
    )
    driver_version = pvproperty(
        name="DriverVersion",
        record="stringin",
        value="3.0.0",
        read_only=True,
        doc="Version of the equivalent EPICS driver.",
    )
    last_error_message = pvproperty(
        name="LastErrorMessage",
        record="waveform",
        # record="stringin",
        read_only=True,
        value="",
        dtype=ChannelType.STRING,
        doc="The last error message from the driver. This includes a timestamp.",
    )
    poll_sleep_ms = pvproperty(
        name="PollSleepMS",
        record="ao",
        value=50.0,
        doc="The number of milliseconds to sleep at the end of each poll cycle.",
    )
    poll_time_ms = pvproperty(
        name="PollTimeMS",
        record="ai",
        dtype=ChannelType.FLOAT,
        doc="The actual number of milliseconds to execute the poll cycle, including the sleep. Averaged over the last 10 reads.",
    )
    ai_all_settling_us = pvproperty(
        name="AiAllSettlingUS",
        record="ao",
        doc="Selects the settling time for all analog input channels.",
    )
    ai_all_resolution = pvproperty(
        name="AiAllResolution",
        record="mbbo",
        doc="High values of resolution result in lower noise and longer ADC conversion time. Resolution 0 is the default resolution for that model.\n\nThe T4 supports resolutions 1-5.\n\nThe T7 supports resolutions 1-8.\n\nThe T7-PRO supports resolutions 1-12. 1-8 use the 16-bit ADC and 9-12 use the 24-bit ADC. When running the waveform generator on the T7-PRO this must be set to values between 1-8, i.e. 16-bit ADC. The driver will set this automatically when starting the waveform generator if it is outside the allowed range.\n\nThe T8 supports resolutions 1-16. However, it is recommended to use the default resolution and change the SamplingRate to control the resolution vs speed tradeoff.",
    )
    ai_sampling_rate = pvproperty(
        name="AiSamplingRate",
        record="ao",
        doc="This sets the sampling rate of the ADC in Hz.\n\nIt applies to the T8 only.\n\nRecommended range is 100 to 10000 Hz.\n\nLower rates do more filtering in the ADC, reducing noise at the expense of speed.\n\nIncreasing the sampling rate will increase the noise in each reading.\n\nHowever, since the analog input records use the devAsynFloat64Average device support, increasing the rate can increase the number of samples averaged in the EPICS device support in a fixed period of time, provided it is not limited by PollSleepMS.\n\nBecause of this averaing in device support, increasing the sampling time from 100 Hz to 1000 Hz can actually result in a small decrease in noise.\n\nThe maximum rate that the values can be read from the device with PollSleepMS=0 is about 2000/s, so increasing the SamplingRate beyond 2000 will not result more averaging in EPICS device support.",
    )
    device_reset = pvproperty(
        name="DeviceReset",
        record="bo",
        doc="Processing this record sets the device watchdog time to 10 s, and the watchdog timer function to device reset. This will reset the device after 10 seconds of communications inactivity. Processing this record, exiting the IOC application, and waiting at least 10 seconds will cause the device to reset. This can be used to remotely recover from a device malfunction that requires a reset. Note that the device will continue to reset every 10 seconds until the IOC successfully starts again. The IOC may occasionally fail to start after a DeviceReset because the device is currently resetting. Trying again will eventually succeed.",
    )

    # Analog outputs
    analog_outputs = SubGroup(ao_subgroup(2), prefix="")

    # Digital I/O
    dio_word = pvproperty(
        name="DIOIn",
        record="longin",
        doc="Digital input value as a word, rather than individual bits. The ADDR parameter in the INP link defines which word is read. 0=DIO (bits 0-23), 1=FIO (bits 0-7), 2=EIO (bits 8-15), 3=CIO (bits 16-19), and 4=MIO (bits 20-22). The binary inputs are polled by the driver poller thread, so these records should have SCAN=”I/O Intr”.",
    )
    eio_word = pvproperty(
        name="EIOIn",
        record="longin",
        doc="Digital input value as a word, rather than individual bits. The ADDR parameter in the INP link defines which word is read. 0=DIO (bits 0-23), 1=FIO (bits 0-7), 2=EIO (bits 8-15), 3=CIO (bits 16-19), and 4=MIO (bits 20-22). The binary inputs are polled by the driver poller thread, so these records should have SCAN=”I/O Intr”.",
    )
    fio_word = pvproperty(
        name="FIOIn",
        record="longin",
        doc="Digital input value as a word, rather than individual bits. The ADDR parameter in the INP link defines which word is read. 0=DIO (bits 0-23), 1=FIO (bits 0-7), 2=EIO (bits 8-15), 3=CIO (bits 16-19), and 4=MIO (bits 20-22). The binary inputs are polled by the driver poller thread, so these records should have SCAN=”I/O Intr”.",
    )
    cio_word = pvproperty(
        name="CIOIn",
        record="longin",
        doc="Digital input value as a word, rather than individual bits. The ADDR parameter in the INP link defines which word is read. 0=DIO (bits 0-23), 1=FIO (bits 0-7), 2=EIO (bits 8-15), 3=CIO (bits 16-19), and 4=MIO (bits 20-22). The binary inputs are polled by the driver poller thread, so these records should have SCAN=”I/O Intr”.",
    )
    mio_word = pvproperty(
        name="MIOIn",
        record="longin",
        doc="Digital input value as a word, rather than individual bits. The ADDR parameter in the INP link defines which word is read. 0=DIO (bits 0-23), 1=FIO (bits 0-7), 2=EIO (bits 8-15), 3=CIO (bits 16-19), and 4=MIO (bits 20-22). The binary inputs are polled by the driver poller thread, so these records should have SCAN=”I/O Intr”.",
    )

    # Waveform digitizer
    wavedig_num_points = pvproperty(
        name="WaveDigNumPoints",
        record="longout",
        doc="Number of points to digitize. This cannot be more than the value of maxInputPoints that was specified in LabJackConfig.",
    )
    wavedig_first_chan = pvproperty(
        name="WaveDigFirstChan", record="mbbo", doc="First channel to digitize, 0-13."
    )
    wavedig_num_chans = pvproperty(
        name="WaveDigNumChans",
        record="mbbo",
        doc="Number of channels to digitize. 1-14. The maximum valid number is 13-FirstChan+1.",
    )
    wavedig_time_wf = pvproperty(
        name="WaveDigTimeWF",
        record="waveform",
        read_only=True,
        doc="Timebase waveform. These values are calculated when Dwell or NumPoints are changed. It is typically used as the X-axis in plots.",
    )
    wavedig_current_point = pvproperty(
        name="WaveDigCurrentPoint",
        record="longin",
        doc="The current point being collected. This does not always increment by 1 because the device can transfer data in blocks.",
    )
    wavedig_dwell = pvproperty(
        name="WaveDigDwell",
        record="ao",
        doc="The time per point in seconds. The minimum time depends on the device type and NumChans.",
    )
    wavedig_dwell_actual = pvproperty(
        name="WaveDigDwellActual",
        record="ai",
        read_only=True,
        doc="The actual time per point in seconds. This may differ from the requested Dwell because of clock granularity in the device.",
    )
    wavedig_total_time = pvproperty(
        name="WaveDigTotalTime",
        record="ai",
        read_only=True,
        doc="The total time to digitize NumChans*NumPoints.",
    )
    wavedig_resolution = pvproperty(
        name="WaveDigResolution",
        record="mbbo",
        doc="The ADC resolution to use for all channels during the scan. The choices are model-dependent and are set by the driver.",
    )
    wavedig_settling_time = pvproperty(
        name="WaveDigSettlingTime",
        record="ao",
        doc="The ADC settling time in microseconds to use for all channels during the scan. 0 selects the device default.",
    )
    wavedig_ext_trigger = pvproperty(
        name="WaveDigExtTrigger",
        record="bo",
        doc="The trigger source, “Internal” (0) or “External” (1). NOTE: NOT YET IMPLEMENTED.",
    )
    wavedig_ext_clock = pvproperty(
        name="WaveDigExtClock",
        record="bo",
        doc="The clock source, “Internal” (0) or “External” (1). If External is used then the Dwell record does not control the digitization rate, it is controlled by the external clock. However Dwell should be set to approximately the correct value if possible, because that builds the time axis for plotting. NOTE: NOT YET IMPLEMENTED.",
    )
    wavedig_auto_restart = pvproperty(
        name="WaveDigAutoRestart",
        record="bo",
        doc="Values are “Disable” (0) and “Enable” (1). This controls whether the driver automatically starts another acquire when the previous one completes.",
    )
    wavedig_run = pvproperty(
        name="WaveDigRun",
        doc="Values are “Stop” (0) and “Run” (1). This starts and stops the waveform digitizer. It will automatically stop when the requested number of samples have been acquired.",
    )
    wavedig_read_wf = pvproperty(
        name="WaveDigReadWF",
        doc="Values are “Done” (0) and “Read” (1). This reads the waveform data from the device buffers into the waveform records. Note that the driver always reads device when acquisition stops, so for quick acquisitions this record can be Passive. To see partial data during long acquisitions this record can be periodically processed.",
    )

    # Waveform digitizer output arrays
    wavedig_volt_wf0 = pvproperty(
        name="WaveDigVoltWF0",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 0. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf1 = pvproperty(
        name="WaveDigVoltWF1",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 1. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf2 = pvproperty(
        name="WaveDigVoltWF2",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 2. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf3 = pvproperty(
        name="WaveDigVoltWF3",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 3. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf4 = pvproperty(
        name="WaveDigVoltWF4",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 4. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf5 = pvproperty(
        name="WaveDigVoltWF5",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 5. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf6 = pvproperty(
        name="WaveDigVoltWF6",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 6. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf7 = pvproperty(
        name="WaveDigVoltWF7",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 7. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf8 = pvproperty(
        name="WaveDigVoltWF8",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 8. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf9 = pvproperty(
        name="WaveDigVoltWF9",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 9. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf10 = pvproperty(
        name="WaveDigVoltWF10",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 10. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf11 = pvproperty(
        name="WaveDigVoltWF11",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 11. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf12 = pvproperty(
        name="WaveDigVoltWF12",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 12. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )
    wavedig_volt_wf13 = pvproperty(
        name="WaveDigVoltWF13",
        record="waveform",
        doc="This waveform record contains the digitizer waveform data for channel 13. This record has scan=I/O Intr, and it will process whenever acquisition completes, or whenever the ReadWF record above processes. The data are in volts or temperature units.",
    )

    # Waveform generator
    wavegen_num_points = pvproperty(
        name="WaveGenNumPoints",
        record="longin",
        doc="Values are “Done” (0) and “Read” (1). This reads the waveform data from the device buffers into the waveform records. Note that the driver always reads device when acquisition stops, so for quick acquisitions this record can be Passive. To see partial data during long acquisitions this record can be periodically processed.",
    )
    wavegen_user_num_points = pvproperty(
        name="WaveGenUserNumPoints",
        record="longout",
        doc="Number of points in user-defined output waveforms. This cannot be more than the value of maxOutputPoints that was specified in LabJackConfig.",
    )
    wavegen_int_num_points = pvproperty(
        name="WaveGenIntNumPoints",
        record="longout",
        doc="Number of points in internal predefined output waveforms. This cannot be more than the value of maxOutputPoints that was specified in LabJackConfig.",
    )
    wavegen_user_time_wf = pvproperty(
        name="WaveGenUserTimeWF",
        record="waveform",
        doc="Timebase waveform for user-defined waveforms. These values are calculated when UserDwell or UserNumPoints are changed. It is typically used as the X-axis in plots.",
    )
    wavegen_int_time_wf = pvproperty(
        name="WaveGenIntTimeWF",
        record="waveform",
        doc="Timebase waveform for internal predefined waveforms. These values are calculated when IntDwell or IntNumPoints are changed. It is typically used as the X-axis in plots.",
    )
    wavegen_current_point = pvproperty(
        name="WaveGenCurrentPoint",
        record="longin",
        doc="The current point being output. This does not always increment by 1 because the device can transfer data in blocks.",
    )
    wavegen_frequency = pvproperty(
        name="WaveGenFrequency",
        record="ai",
        doc="The output frequency (waveforms/second). The value of this record is equal to UserFrequency if user-defined waveforms are selected, or IntFrequency if internal predefined waveforms are selected.",
    )
    wavegen_dwell = pvproperty(
        name="WaveGenDwell",
        record="ai",
        doc="The output dwell time or period (seconds/sample). The value of this record is equal to UserDwell if user-defined waveforms are selected, or IntDwell if internal predefined waveforms are selected.",
    )
    wavegen_dwell_actual = pvproperty(
        name="WaveGenDwellActual",
        record="ai",
        doc="The actual dwell time. This can be different from the requested dwell time (WaveGenDwell) because of the granularity of the device clock.",
    )
    wavegen_user_dwell = pvproperty(
        name="WaveGenUserDwell",
        record="ao",
        doc="The output dwell time or period (seconds/sample) for user-defined waveforms. This record is automatically changed if UserFrequency is modified.",
    )
    wavegen_int_dwell = pvproperty(
        name="WaveGenIntDwell",
        record="ao",
        doc="The output dwell time or period (seconds/sample) for internal predefined waveforms. This record is automatically changed if IntFrequency is modified.",
    )
    wavegen_user_frequency = pvproperty(
        name="WaveGenUserFrequency",
        record="ao",
        doc="The output frequency (waveforms/second) for user-defined waveforms. This record computes UserDwell and writes to that record. This record is automatically changed if UserDwell is modified.",
    )
    wavegen_int_frequency = pvproperty(
        name="WaveGenIntFrequency",
        record="ao",
        doc="The output frequency (waveforms/second) for internal predefined waveforms. This record computes IntDwell and writes to that record. This record is automatically changed if IntDwell is modified.",
    )
    wavegen_total_time = pvproperty(
        name="WaveGenTotalTime",
        record="ai",
        doc="The total time to output the waveforms. This is WaveGenDwellActual*NumPoints.",
    )
    wavegen_ext_trigger = pvproperty(
        name="WaveGenExtTrigger",
        record="bo",
        doc="The trigger source, “Internal” (0) or “External” (1). NOTE: NOT YET IMPLEMENTED,",
    )
    wavegen_ext_clock = pvproperty(
        name="WaveGenExtClock",
        record="bo",
        doc="The clock source, “Internal” (0) or “External” (1). If External is used then the Dwell record does not control the output rate, it is controlled by the external clock. However Dwell should be set to approximately the correct value if possible, because that controls the time axis on the plots. NOTE: NOT YET IMPLEMENTED.",
    )
    wavegen_continuous = pvproperty(
        name="WaveGenContinuous",
        record="bo",
        doc="Values are “One-shot” (0) or “Continuous” (1). This controls whether the device stops when the output waveform is complete, or immediately begins again at the start of the waveform.",
    )
    wavegen_run = pvproperty(
        name="WaveGenRun",
        doc="Values are “Stop” (0) and “Run” (1). This starts and stops the waveform generator. In one-shot mode the waveform generator stops automatically when all of the samples have been output.",
    )
    wavegen_user_wf_0 = pvproperty(
        name="WaveGenUserWF0",
        record="waveform",
        doc="This waveform record contains the user-defined waveform generator data for channel 0. The data are in volts. These data are typically generated by an EPICS Channel Access client.",
    )
    wavegen_user_wf_1 = pvproperty(
        name="WaveGenUserWF1",
        record="waveform",
        doc="This waveform record contains the user-defined waveform generator data for channel 1. The data are in volts. These data are typically generated by an EPICS Channel Access client.",
    )
    wavegen_internal_wf_0 = pvproperty(
        name="WaveGenInternalWF0",
        record="waveform",
        doc="This waveform record contains the internal predefined waveform generator data for channel 0. The data are in volts.",
    )
    wavegen_internal_wf_1 = pvproperty(
        name="WaveGenInternalWF1",
        record="waveform",
        doc="This waveform record contains the internal predefined waveform generator data for channel 1. The data are in volts.",
    )
    wavegen_enable_0 = pvproperty(
        name="WaveGenEnable0",
        record="bo",
        doc="Values are “Disable” and “Enable”. Controls whether channel 0 output is enabled.",
    )
    wavegen_enable_1 = pvproperty(
        name="WaveGenEnable1",
        record="bo",
        doc="Values are “Disable” and “Enable”. Controls whether channel 1 output is enabled.",
    )
    wavegen_type_0 = pvproperty(
        name="WaveGenType0",
        record="mbbo",
        doc="Controls the waveform type on channel 0. Values are\n\n- “User-defined”\n- “Sin wave”,\n- “Square wave”\n- “Sawtooth”\n- “Pulse”\n- “Random”.\n\nNote that if any channel is “User-defined” then all channels must be. Note that all internally predefined waveforms are symmetric about 0 volts. To output unipolar signals the Offset should be set to +-Amplitude/2.",
    )
    wavegen_type_1 = pvproperty(
        name="WaveGenType1",
        record="mbbo",
        doc="Controls the waveform type on channel 1. Values are\n\n- “User-defined”\n\n- “Sin wave”,\n\n- “Square wave”\n\n- “Sawtooth”\n\n- “Pulse”\n\n- “Random”.\n\nNote that if any channel is “User-defined” then all channels must be. Note that all internally predefined waveforms are symmetric about 0 volts. To output unipolar signals the Offset should be set to +-Amplitude/2.",
    )
    wavegen_pulse_width_0 = pvproperty(
        name="WaveGenPulseWidth0",
        record="ao",
        doc="Controls the pulse width in seconds if Type is “Pulse”.",
    )
    wavegen_pulse_width_1 = pvproperty(
        name="WaveGenPulseWidth1",
        record="ao",
        doc="Controls the pulse width in seconds if Type is “Pulse”.",
    )
    wavegen_amplitude_0 = pvproperty(
        name="WaveGenAmplitude0",
        record="ao",
        doc="Controls the amplitude of the waveform. For internally predefined waveforms this directly controls the peak-to-peak amplitude in volts. For user-defined waveforms this is a scale factor that multiplies the values in the waveform, i.e. 1.0 outputs the user-defined waveform unchanged, 2.0 increases the amplitide by 2, etc. For both internal and used-defined waveforms changing the sign of the Amplitude controls the polarity of the signal.",
    )
    wavegen_amplitude_1 = pvproperty(
        name="WaveGenAmplitude1",
        record="ao",
        doc="Controls the amplitude of the waveform. For internally predefined waveforms this directly controls the peak-to-peak amplitude in volts. For user-defined waveforms this is a scale factor that multiplies the values in the waveform, i.e. 1.0 outputs the user-defined waveform unchanged, 2.0 increases the amplitide by 2, etc. For both internal and used-defined waveforms changing the sign of the Amplitude controls the polarity of the signal.",
    )
    wavegen_offset_0 = pvproperty(
        name="WaveGenOffset0",
        record="ao",
        doc="Controls the offset of the waveform in volts. For user-defined waveforms, this value is added to the waveform, i.e. 0.0 outputs the user-defined waveform unchanged, 1.0 adds 1 volt, etc.",
    )
    wavegen_offset_1 = pvproperty(
        name="WaveGenOffset1",
        record="ao",
        doc="Controls the offset of the waveform in volts. For user-defined waveforms, this value is added to the waveform, i.e. 0.0 outputs the user-defined waveform unchanged, 1.0 adds 1 volt, etc.",
    )

    def __init__(self, *args, identifier, **kwargs):
        super().__init__(*args, **kwargs)
        self._ai_cache = {}
        self._poll_times = np.asarray([], dtype=float)
        # Determine how many I/O channels this device has
        num_ai = len(self.analog_inputs.groups)
        # Create a driver to do the communication
        self.driver = LabJackDriver(identifier=identifier, num_ai=num_ai)

    async def update_poll_time(self, new_timestamp: float = None):
        """Update PV *poll_time_ms* with an average of the most recent poll
        time intervals.

        If *new_timestamp* is provided, it will be added to the list,
        and only the most recent 10 poll time intervals will be kept.

        Parameters
        ==========
        new_timestamp
          A new timestamp from ``time.monotonic()`` or equivalent.

        """
        # Save the new timestamp
        if new_timestamp is not None:
            self._poll_times = np.append(self._poll_times[-10:], [new_timestamp])
        # Update the poll_time_ms PV
        intervals = np.diff(self._poll_times)
        if len(intervals) > 0:
            poll_time_s = np.mean(intervals)
            poll_time_ms = poll_time_s * 1000
            await self.poll_time_ms.write(poll_time_ms)

    async def read_inputs(self):
        """Read the analog/digital inputs from the device, and write the
        associated PVs.

        Also updates the PV *poll_time_ms* with actual polling times.

        """
        inputs = await self.driver.read_inputs()
        await self.update_poll_time(time.monotonic())
        # Set the analog inputs
        self._ai_cache = {k: v for k, v in inputs.items() if k[:3] == "AIN"}
        # Set individual digital inputs
        dio_word = inputs["DIO_STATE"]
        mask = 0b1  # select which digital IO we're reading
        for pv in self.digital_ios.groups.values():
            val = bool(mask & dio_word)
            await pv.input.write(val)
            # Move the mask on to the next digital I/O
            mask <<= 1
        # Set digital input words
        await self.dio_word.write(dio_word)
        # FIO0:7 == DIO0:7
        fio_word = 0b00000000000011111111 & dio_word
        await self.fio_word.write(fio_word)
        # EIO0:7 == DIO8:15
        eio_word = 0b00001111111100000000 & dio_word
        eio_word >>= 8
        await self.eio_word.write(eio_word)
        # CIO0:3 == DIO16:19
        cio_word = 0b11110000000000000000 & dio_word
        cio_word >>= 16
        await self.cio_word.write(cio_word)

    async def load_device_info(self):
        """Read the device information from the driver and set the corresponding PVs."""
        # Get device info from the driver
        info = await self.driver.device_info()
        # Set PVs with the updated device info
        await self.firmware_version.write(info['firmware_version'])
        await self.serial_number.write(info['serial_number'])
        await self.ljm_version.write(version("labjack.ljm"))
        await self.last_error_message.write("No error")
        return info
        
    @poll_sleep_ms.startup
    async def poll_sleep_ms(self, instance, async_lib):
        """Startup for the labjack device.

        Tasks:

        1. Connect to the labjack device
        2. Read basic device infomation
        3. Start polling loop

        Will load basic device information PVs (e.g. firmware
        version), and then start a polling loop to retrieve digital
        and analog I/O states. The analog inputs will not necessarily
        update at this rate, but will just be cached for updating when
        the AI polling interval elapses.

        """
        # Connect the device
        await self.driver.connect()
        # Load device info
        await self.load_device_info()
        # Start polling loop
        while True:
            sleep_time_ms = instance.value
            await self.read_inputs()
            await async_lib.sleep(sleep_time_ms / 1000)


class LabJackT4(LabJackBase):
    """A labjack T4 DAQ.

    Equipped with:

    - 4 analog inputs
    """
    model_name = pvproperty(
        name="ModelName",
        record="mbbi",
        value="T4",
        read_only=True,
        enum_strings=model_names.values(),
        dtype=ChannelType.ENUM,
        doc="Device model name. mbbi values and strings are 0='T4', 1='T7', 2='T7-Pro', 3='T8'",
    )
    # Analog inputs
    analog_inputs = SubGroup(ai_subgroup(4), prefix="")
    digital_ios = SubGroup(dio_subgroup(16), prefix="")
