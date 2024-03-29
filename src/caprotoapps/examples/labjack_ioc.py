#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, SubGroup, ioc_arg_parser, pvproperty, run

from caprotoapps import LabJackT4

PREFIX = "LabJack:"


class LabJackIOC(PVGroup):
    """An IOC showing several labjack devices."""

    t4 = SubGroup(LabJackT4, prefix="T4:", identifier="labjack25idc01")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX, desc=dedent(LabJackIOC.__doc__)
    )
    ioc = LabJackIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
