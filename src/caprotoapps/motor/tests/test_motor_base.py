from unittest.mock import MagicMock
from pprint import pprint

import pytest
from caproto.server import pvproperty, PVGroup, SubGroup

from caprotoapps import MotorFieldsBase


class MockIOC(PVGroup):
    m1 = pvproperty(name="m1", value=0.0, record="motor_base")


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
    await test_ioc.m1.field_inst.handle_new_user_desired_value(pv=None, response=response)
    # Check the dial value is correct
    assert test_ioc.m1.fields["DVAL"].value == 5885.0
    
