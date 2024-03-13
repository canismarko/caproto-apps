"""A PV group that can create and manage local file storage.

Example usage:

.. code-block:: python

    class LocalStorageIOC(PVGroup):
        manager = SubGroup(LocalStorageGroup,
                           prefix="25idc")

"""

from caproto.server import PVGroup, pvproperty


class LocalStorageGroup(PVGroup):
    """A caproto PV group for managing local file storage folders.

    The group will respond to changes in the beamline scheduling
    metadata, and keep track of local file storage to match.

    Assuming the following:
      - the current cycle is 2024-1
      - the PI's for the current proposal are "Wolfman, Kelly"
      - the *base_dir* PV is "/net/s25data/export/25-ID-C/"

    then the *sub_directory* will be "2024-1/Wolfman_Kelly/", and the
    *final_directory* will be
    "/net/s25data/export/25-ID-C/2024-1/Wolfman_Kelly/".

    The intended use is to set the *base_directory* property
    once. Then when the BSS metadata changes, the *sub_directory*
    property will change to reflect the metadata. *final_directory* is
    a combination of both other PVs and can be used to store data.

    """
    base_directory = pvproperty(doc="The static portion of the directory path. Does not change with BSS metadata.")
    sub_directory = pvproperty(doc="The variable portion of the directory path. Based on BSS metadata.")
    final_directory = pvproperty(read_only=True, doc="The combined directory path based on the base and sub directories.")
    exists = pvproperty(read_only=True, value=False, doc="Whether or not the value of *final_directory* exists on the target filesystem.")
    create = pvproperty(dtype=bool, doc="Put to this PV to create the *final_directory* on the target filesystem.")
