import asyncio
from unittest.mock import MagicMock
from pprint import pprint

import pytest
from caproto.server import pvproperty, PVGroup, SubGroup

from caprotoapps import MotorFieldsBase


class MockIOC(PVGroup):
    m1 = pvproperty(name="m1", value=0.0, record="motor_base", precision=4)


@pytest.fixture
def test_ioc():
    ioc = MockIOC(prefix="test_ioc:")
    yield ioc


@pytest.mark.asyncio
async def test_user_value_conversion(test_ioc):
    # Set some known offset
    await test_ioc.m1.fields["DIR"].write("Pos")
    await test_ioc.m1.fields["OFF"].write(1615.0)
    await test_ioc.m1.fields["DVAL"].write(5885.0)
    # Check that calibration value
    assert test_ioc.m1.value == 7500.0
    # Different calibration offset
    await test_ioc.m1.fields["OFF"].write(1715.0)
    assert test_ioc.m1.value == 7600.0
    # Reverse the offset
    await test_ioc.m1.fields["OFF"].write(12385.0)
    await test_ioc.m1.fields["DIR"].write("Neg")
    assert test_ioc.m1.value == 6500.0


@pytest.mark.asyncio
async def test_user_limits_conversion(test_ioc):
    # Set some known offset
    await test_ioc.m1.fields["DIR"].write("Pos")
    await test_ioc.m1.fields["OFF"].write(1615.0)
    await test_ioc.m1.fields["HLM"].write(10000)
    await test_ioc.m1.fields["LLM"].write(-5000)
    # Check that dial limits were updated
    assert test_ioc.m1.fields["DHLM"].value == 8385.0
    assert test_ioc.m1.fields["DLLM"].value == -6615.0


@pytest.mark.asyncio
async def test_user_readback_conversion(test_ioc):
    # Set some known offset
    await test_ioc.m1.fields["DIR"].write("Pos")
    await test_ioc.m1.fields["OFF"].write(1615.0)
    await test_ioc.m1.fields["DRBV"].write(5885.0)
    # Check that calibration value
    assert test_ioc.m1.fields["RBV"].value == 7500.0
    # Different calibration offset
    await test_ioc.m1.fields["OFF"].write(1715.0)
    assert test_ioc.m1.fields["RBV"].value == 7600.0
    # Reverse the offset
    await test_ioc.m1.fields["OFF"].write(12385.0)
    await test_ioc.m1.fields["DIR"].write("Neg")
    assert test_ioc.m1.fields["RBV"].value == 6500.0


@pytest.mark.asyncio
async def test_dial_value_conversion(test_ioc):
    # Set some known offset
    await test_ioc.m1.fields["DIR"].write("Pos")
    await test_ioc.m1.fields["OFF"].write(1615.0)
    # Set a new user setpoint value
    response = MagicMock()
    response.data = [7500.0]
    await test_ioc.m1.field_inst.handle_new_user_desired_value(
        pv=None, response=response
    )
    # Check the dial value is correct
    assert test_ioc.m1.fields["DVAL"].value == 5885.0


@pytest.mark.asyncio
async def test_vof_fof(test_ioc):
    """The fields VOF and FOF are intended for use in backup/restore
    operations; any write to them will drive the FOFF field to
    "Variable" (VOF) or "Frozen" (FOF).

    """
    assert test_ioc.m1.fields["FOFF"].value == 0
    # Set it to frozen
    await test_ioc.m1.fields["FOF"].write(1)
    assert test_ioc.m1.fields["FOFF"].value == "Frozen"
    # Set it back to variable
    await test_ioc.m1.fields["VOF"].write(1)
    assert test_ioc.m1.fields["FOFF"].value == "Variable"


@pytest.mark.asyncio
async def test_sset_suse(test_ioc):
    """Simlar to the fields VOF and FOF, tests SSET and SUSE for setting
    SET to specific values.

    """
    assert test_ioc.m1.fields["SET"].value == 0
    # Set it to frozen
    await test_ioc.m1.fields["SSET"].write(5)
    assert test_ioc.m1.fields["SET"].value == "Set"
    # Set it back to variable
    await test_ioc.m1.fields["SUSE"].write(3)
    assert test_ioc.m1.fields["SET"].value == "Use"


@pytest.mark.asyncio
async def test_set_calibration(test_ioc):
    """Test the .SET field in variable offset mode (.FOFF).

    When SET = 1 ("Set"), writes to the dial-coordinate drive field
    (DVAL) and to the raw drive field (RVAL) cause a new raw motor
    position to be loaded into the hardware without any change to the
    user-coordinate drive field (VAL). Writes to other fields that
    would normally move the motor, change the user-coordinate drive
    field (VAL), and the offset between user and dial coordinates (the
    OFF field), with corresponding changes in the user-coordinate
    limit fields (HLM and LLM).

    """
    await test_ioc.m1.fields["IGSET"].write(0)
    await test_ioc.m1.fields["SET"].write(1)
    await test_ioc.m1.fields["DVAL"].write(5885.0)
    await test_ioc.m1.fields["HLM"].write(1000.0)
    await test_ioc.m1.fields["LLM"].write(-1000.0)
    response = MagicMock()
    response.data = [7500.0]
    await test_ioc.m1.field_inst.handle_new_user_desired_value(
        pv=None, response=response
    )
    # Check that calibration value changed
    assert test_ioc.m1.fields["OFF"].value == 1615.0
    # Check that user limits changed
    assert test_ioc.m1.fields["HLM"].value == 2615.0
    assert test_ioc.m1.fields["LLM"].value == 615.0


@pytest.mark.asyncio
async def test_load_precision(test_ioc):
    """Does the motor record handle precision properly?"""
    # pprint([f for f in dir(test_ioc.m1.field_inst) if "prec" in f])
    await test_ioc.m1.field_inst.display_precision.startup(
        test_ioc.m1.fields["PREC"], asyncio
    )
    # Check that the parent property's precision is used
    assert test_ioc.m1.fields["PREC"].value == 4
    # Check that relevant fields also share the precision
    fields = [
        "DHLM",
        "HLM",
        "DLLM",
        "LLM",
        "DVAL",
        "RBV",
        "DRBV",
        "RLV",
        "TWV",
        "OFF",
        "VMAX",
        "VELO",
        "BVEL",
        "JVEL",
        "VBAS",
        "ACCL",
        "BACC",
        "JAR",
        "BDST",
        "FRAC",
        "PCOF",
        "ICOF",
        "DCOF",
        "MRES",
        "ERES",
        "RRES",
        "RDBD",
        "DLY",
        "DIFF",
        "UREV",
        "S",
        "SBAK",
        "SMAX",
        "SBAS",
        "HVEL",
    ]
    for fld in fields:
        assert test_ioc.m1.fields[fld].precision == 4, fld


@pytest.mark.asyncio
async def test_change_precision(test_ioc):
    """Does the motor record handle precision properly?"""
    # Change the precision PV
    await test_ioc.m1.fields["PREC"].write(5)
    # Check that the parent property's precision was updated
    assert test_ioc.m1.precision == 5
    # Check that relevant fields also share the precision
    fields = [
        "DHLM",
        "HLM",
        "DLLM",
        "LLM",
        "DVAL",
        "RBV",
        "DRBV",
        "RLV",
        "TWV",
        "OFF",
        "VMAX",
        "VELO",
        "BVEL",
        "JVEL",
        "VBAS",
        "ACCL",
        "BACC",
        "JAR",
        "BDST",
        "FRAC",
        "PCOF",
        "ICOF",
        "DCOF",
        "MRES",
        "ERES",
        "RRES",
        "RDBD",
        "DLY",
        "DIFF",
        "UREV",
        "S",
        "SBAK",
        "SMAX",
        "SBAS",
        "HVEL",
    ]
    for fld in fields:
        assert test_ioc.m1.fields[fld].precision == 5, fld
