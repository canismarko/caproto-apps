#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run, SubGroup
from caprotoapps import MotorFieldsBase


PREFIX = "motors:"


class MotorIOC(PVGroup):
    """An IOC showing motor devices."""
    m1 = pvproperty(name="m1", record=MotorFieldsBase, value=0.0)


if __name__ == "__main__":
    # Prepare the command line arguments
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX, desc=dedent(MotorIOC.__doc__)
    )
    # Create the IOC
    ioc = MotorIOC(**ioc_options)
    # Run the IOC
    run(ioc.pvdb, **run_options)
