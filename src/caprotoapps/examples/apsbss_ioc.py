#!/usr/bin/env python3

"""An example IOC for interacting with the APS beamline scheduling
system (BSS).

Usage:
  $ ./apsbss_ioc.py --list-pvs

"""

from textwrap import dedent

from caproto.server import PVGroup, SubGroup, ioc_arg_parser, pvproperty, run

from caprotoapps import ApsBssGroup


class BSSIOC(PVGroup):
    """An IOC connecting to the APS beamline scheduling system."""

    bss = SubGroup(ApsBssGroup, prefix="bss:", dm_host="https://example.org:11236")


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="", desc=dedent(BSSIOC.__doc__)
    )
    ioc = BSSIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
