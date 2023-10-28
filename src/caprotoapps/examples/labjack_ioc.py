#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run, SubGroup
from caprotoapps import LabJackT4


PREFIX = "LabJack:"


class LabJackIOC(PVGroup):
    """An IOC showing several labjack devices."""

    t4 = SubGroup(LabJackT4, prefix="T4:", identifier="-2")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX, desc=dedent(LabJackIOC.__doc__)
    )
    ioc = LabJackIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
