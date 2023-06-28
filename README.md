# caproto-apps

[![Tests](https://github.com/canismarko/caproto-apps/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/canismarko/caproto-apps/actions/workflows/ci.yml)

Implementations of select EPICS-compatible records in caproto.

Currently the only app available is the **Alive** app.

## Alive

The AliveGroup provides equivalent functionality to the
[EPICS alive record](http://epics-modules.github.io/alive/aliveRecord.html)
and is compatible with existing
[alive daemons](https://epics-alive-server.github.io/alive-overview.html).

It is intended to be added to an existing ``PVGroup`` using caproto's
``SubGroup`` wrapper:

```
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
```

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

```
from caprotoapps.alive import AliveGroup, envvar_default_property

class MyAliveGroup(AliveGroup):
    # Replace ``ENGINEER`` with ``SCIENTIST``
    evd1 = envvar_default_property(1, "SCIENTIST")
    # Add a new variable, "STATUS"
    evd6 = envvar_default_property(1, "STATUS")

```

## Building the Project for PyPI

```
(venv) $ python -m build
(venv) $ twine check dist/*
(venv) $ twine upload -r testpypi dist/*
(venv) $ twine upload dist/*
```