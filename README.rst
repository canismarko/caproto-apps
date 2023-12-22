============
Caproto Apps
============

.. image:: https://github.com/canismarko/caproto-apps/actions/workflows/ci.yml/badge.svg?branch=main
   :alt: Tests
   :target: https://github.com/canismarko/caproto-apps/actions/workflows/ci.yml

Implementations of select EPICS-compatible records in caproto.


Installation
============

.. code:: bash

    pip install caproto-apps

Components
==========

Alive
-----

The AliveGroup provides equivalent functionality to the
`EPICS alive record <http://epics-modules.github.io/alive/aliveRecord.html>`_
and is compatible with existing
`alive daemons <https://epics-alive-server.github.io/alive-overview.html>`_.

It is intended to be added to an existing ``PVGroup`` using caproto's
``SubGroup`` wrapper:

.. code:: python

    from caprotoapps import AliveGroup
    
    class MyIOC(PVGroup):
        alive = SubGroup(
            AliveGroup,
            prefix="alive",
            remote_host="xapps2.xray.aps.anl.gov",
            remote_port=5678,  # Optional, 5678 is the default port
            ioc_name="my_ioc", # If omitted, will use the parent IOC prefix
        )
    
    if __name__ == "__main__":
        # Start the IOC as normal for caproto
        ...

An alive daemon can request **environmental variables** from the alive
group. Many of the default environmental variables in the EPICS alive
record are specific to EPICS (e.g. ``EPICS_BASE``) and so are not
included as default environmental variables in this ``AliveGroup``.

Presently, the default environmental variables are:

1. ENGINEER
2. LOCATION
3. GROUP
4. STY
5. PREFIX

Neither caproto nor caproto-apps sets the value of these environmental
variables, so it is left up to the launcher for the parent IOC
(e.g. in a systemd unit). **Additional default environmental variables
can be added** (or replaced) by subclassing the AliveGroup:

.. code:: python
    	  
    from caprotoapps.alive import AliveGroup, envvar_default_property
    
    class MyAliveGroup(AliveGroup):
        # Replace ``ENGINEER`` with ``SCIENTIST``
        evd1 = envvar_default_property(1, "SCIENTIST")
        # Add a new variable, "STATUS"
        evd6 = envvar_default_property(1, "STATUS")

LabJack
-------

There are a set of ``PVGroup`` objects for the T-series data
acquisition devices from the LabJack company. They are designed to
mimic the `LabJack EPICS module
<https://epics-modules.github.io/LabJack/>`_, and operate in a similar
manner.

.. note::

   Caproto has labjack-ljm as a dependency, which supports LabJack
   T-series devices. **However, labjack-ljm requires that LJM be
   installed** separately from the python support. Without this
   library installed, the LabJack IOC will not function. See the `LJM
   user's guide
   <https://labjack.com/pages/support?doc=/software-driver/ljm-users-guide/>`_
   for more information.

There is a group for each supported device, which is currently:

- LabJackT4

though there are plans to support more in the future.

To add support for a LabJack device, include the following in an IOC:

.. code:: python

    from caprotoapps import LabJackT4
    
    class MyIOC(PVGroup):
        t4_1 = SubGroup(LabJackT4, prefix="T4_1:", identifier="labjack01")
	t4_2 = SubGroup(LabJackT4, prefix="T4_2:", identifier="labjack02")
	t4_sim = SubGroup(LabJackT4, prefix="T4_3:", identifier="-2")

    if __name__ == "__main__":
        # Start your IOC as usual
        ...

For a complete example, see ``examples/labjack_ioc.py``.

*identifier* can be any `valid LJM identifier
<https://labjack.com/pages/support?doc=/software-driver/ljm-users-guide/identifier-parameter/>`_
to distinguish a device:

- The hostname of a network-connected device (see note)
- The IP address of a network-connected device
- The USB port of a USB-connected device
- The serial number of a connected device
- The name of a connected device
- "-2" to use the simulated device
- "ANY" to use the first device found (not recommended)

.. note:: 
   
   Hostnames are not supported by LJM, so caprotoapps will first try to
   resolve the identifier as a hostname, and if that fails will use the
   identifier as provided.
    
Manager
-------

The ``ManagerGroup`` allows for remote management of other
IOCs. Currently the only supported style is that of APS beamline
controls group. To allow control of an IOC, specify the path to the
startup script using the *script* parameter.

.. code:: python
    
    from caproto.server import SubGroup
    from caprotoapps import ManagerGroup
    
    class MyIOC(PVGroup):
        ioc_manager = SubGroup(ManagerGroup,
                               script="/path/to/script.sh")

If the script can be reached on another machine via SSH, then the
following pattern can also be used, provided that passwordless login
is set up (i.e. using ``ssh-keygen``):

.. code:: python
    
    class MyIOC(PVGroup):
        ioc_manager = SubGroup(ManagerGroup,
        		           script="myuser@myhost:/path/to/script.sh")
    ```
    
    **Note:** The *console* PV is currently not implemented.
    
It is possible to **limit which IOCs can be started or stopped** via
an IOC ManagerGroup using the *allow_start* and *allow_stop*
parameters during initialization:
   
.. code:: python
    
    class MyIOC(PVGroup):
        mission_critical_manager = SubGroup(ManagerGroup,
    					allow_start=True,
    					allow_stop=False)

The status PVs *startable* and *stoppable* are read-only indicators of
whether the IOC can be controlled via this ManagerGroup. Re-starting
an IOC requires both *allow_start* and *allow_stop* to be true.

Development
===========

To install caproto-apps for development, first clone the github repository:

.. code:: bash

    git clone https://github.com/canismarko/caproto-apps.git

Then run tests with pytest

.. code:: bash
    
    pytest

Building the Project for PyPI
=============================

.. code:: bash
    
    (venv) $ python -m build
    (venv) $ twine check dist/*
    (venv) $ twine upload -r testpypi dist/*
    (venv) $ twine upload dist/*
