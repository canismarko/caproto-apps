#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run, SubGroup
from caprotoapps import ApsBssGroup


class LabJackIOC(PVGroup):
    """An IOC showing several labjack devices."""

    bss = SubGroup(ApsBssGroup, prefix="bss:")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="", desc=dedent(LabJackIOC.__doc__)
    )
    ioc = LabJackIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
