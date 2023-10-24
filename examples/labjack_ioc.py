#!/usr/bin/env python3
from textwrap import dedent

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run
from caprotoapps import LabJackIOC


PREFIX = 'LabJackT7_1:'


if __name__ == '__main__':
    ioc_options, run_options = ioc_arg_parser(
        default_prefix=PREFIX,
        desc=dedent(LabJackIOC.__doc__))
    ioc = LabJackIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
