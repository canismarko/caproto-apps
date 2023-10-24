import pytest

from caprotoapps import LabJackIOC

@pytest.fixture
def ioc():
    ioc = LabJackIOC(prefix="test_ioc:")
    yield ioc


def test_pvs(ioc):
    from pprint import pprint
    pprint(ioc.pvdb)
    # analog inputs
    assert "test_ioc:Ai0" in ioc.pvdb
    assert "test_ioc:AiEnable0" in ioc.pvdb
    assert "test_ioc:AiMode0" in ioc.pvdb
    assert "test_ioc:AiTempUnits0" in ioc.pvdb
    assert "test_ioc:AiDiff0" in ioc.pvdb
    assert "test_ioc:AiRange0" in ioc.pvdb
    assert "test_ioc:AiResolution0" in ioc.pvdb
    # analog outputs
    assert "test_ioc:Ao0" in ioc.pvdb
    assert "test_ioc:Ao0TweakVal" in ioc.pvdb
    assert "test_ioc:Ao0TweakUp" in ioc.pvdb
    assert "test_ioc:Ao0TweakDown" in ioc.pvdb
    # digital I/O
    assert "test_ioc:Bi0" in ioc.pvdb
    assert "test_ioc:Bo0" in ioc.pvdb
    assert "test_ioc:Bd0" in ioc.pvdb
    assert "test_ioc:DIOIn" in ioc.pvdb
    assert "test_ioc:EIOIn" in ioc.pvdb
    assert "test_ioc:FIOIn" in ioc.pvdb
    assert "test_ioc:CIOIn" in ioc.pvdb
    assert "test_ioc:MIOIn" in ioc.pvdb

