#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run, SubGroup, PvpropertyDouble
from caprotoapps import MotorFieldsBase


PREFIX = "motors:"


class CustomMotor(PvpropertyDouble):
    axis: int
    
    def __init__(self, axis: int, *args, **kwargs):
        self.axis = axis
        super().__init__(*args, **kwargs)
    
    async def do_move(self, value: float, speed: float):
        print(f"Moving {self.axis=} at {value=} at {speed=} steps/sec.")
    

class MotorIOC(PVGroup):
    """An IOC showing motor devices."""

    m1 = pvproperty(name="m1", axis=1, record="motor_base", value=0.0, dtype=CustomMotor, precision=4)
    m2 = pvproperty(name="m2", axis=2, record="motor_base", value=0.0, dtype=CustomMotor, precision=4)


if __name__ == "__main__":
    # Prepare the command line arguments
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX, desc=dedent(MotorIOC.__doc__)
    )
    # Create the IOC
    ioc = MotorIOC(**ioc_options)
    # Run the IOC
    run(ioc.pvdb, **run_options)
