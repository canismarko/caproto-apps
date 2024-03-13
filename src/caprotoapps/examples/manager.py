#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run, SubGroup
from caprotoapps import LocalStorageGroup, ApsBssGroup


PREFIX = "managers:"


class ManagerIOC(PVGroup):
    """An IOC showing several labjack devices."""

    bss = SubGroup(ApsBssGroup, prefix="bss:", dm_host="localhost")
    local_storage = SubGroup(LocalStorageGroup, prefix="local_storage:")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX, desc=dedent(ManagerIOC.__doc__)
    )
    ioc = ManagerIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
