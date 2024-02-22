from unittest import mock
import pytest
import yaml

from caproto.server import PVGroup, SubGroup

from caprotoapps import apsbss
from caprotoapps.apsbss_api import BSSApi


esaf = {
    "description": (
        "Electrochemical battery cells will be assembled in an "
        "argon-filled glovebox from pre-made cathodes, electrolyte and "
        "lithium metal. The sealed cells will then be removed from the "
        "glovebox and charged using a battery tester ether in the "
        "laboratory or at the beamline. (Beamline work covered under "
        "separate ESAF). After cycling, cells will be returned to the "
        "glovebox and disassembled. Lithium metal will be stored in "
        "dedicated waste container. Separators and cathodes will be "
        "disposed as hazardous waste. Cells components will then be "
        "removed from the glovebox and transferred to a fume hood for "
        "cleaning. A mixture of 30% iso-propanol and 70% water will be "
        "used to clean the cell. The water content will remove "
        "residual lithium, which presents a possible flammability "
        "hazard. A class D fire extinguisher (or LithX powder) shall "
        "be made available in case of fire and all cleaning shall be "
        "done in a fume hood. The wash will be disposed as hazardous "
        "waste."
    ),
    "esafId": 187973,
    "esafStatus": "Approved",
    "esafTitle": "Electrochemical Cell Preparation and Testing",
    "experimentEndDate": "2018-07-11 23:00:00",
    "experimentStartDate": "2018-06-11 08:00:00",
    "experimentUsers": [
        {
            "badge": "268176",
            "badgeNumber": "268176",
            "email": "mwolf22@uic.edu",
            "firstName": "Mark",
            "lastName": "Wolfman",
            "piFlag": "Yes",
        },
        {
            "badge": "239241",
            "badgeNumber": "239241",
            "email": "vdeandrade@aps.anl.gov",
            "firstName": "Vincent",
            "lastName": "De Andrade",
            "piFlag": "No",
        },
        {
            "badge": "288878",
            "badgeNumber": "288878",
            "email": "cli203@uic.edu",
            "firstName": "Chao",
            "lastName": "Li",
            "piFlag": "No",
        },
        {
            "badge": "298130",
            "badgeNumber": "298130",
            "email": "wjudge2@uic.edu",
            "firstName": "William",
            "lastName": "Judge",
            "piFlag": "No",
        },
    ],
    "sector": "11",
}


proposal = {
    "activities": [
        {
            "duration": 86400,
            "endTime": "2022-03-04 08:00:00-06:00",
            "startTime": "2022-03-03 08:00:00-06:00",
        }
    ],
    "duration": 86400,
    "endTime": "2022-03-13 23:00:00-06:00",
    "experimenters": [
        {
            "badge": "85202",
            "email": "michael.toney@colorado.edu",
            "firstName": "Michael",
            "id": 488782,
            "instId": 3590,
            "institution": "University of Colorado at Boulder",
            "lastName": "Toney",
        },
        {
            "badge": "64944",
            "email": "cjsun@aps.anl.gov",
            "firstName": "Chengjun",
            "id": 488742,
            "instId": 3927,
            "institution": "Argonne National Laboratory",
            "lastName": "Sun",
        },
        {
            "badge": "287279",
            "email": "gangwan@stanford.edu",
            "firstName": "Gang",
            "id": 488804,
            "instId": 3434,
            "institution": "Stanford University",
            "lastName": "Wan",
            "piFlag": "Y",
        },
    ],
    "id": 74204,
    "mailInFlag": "Y",
    "proprietaryFlag": "N",
    "startTime": "2022-03-03 08:00:00-06:00",
    "submittedDate": "2021-03-04 17:28:28-06:00",
    "title": "Operando X-ray Spectroscopy Studies of Model Oxide Thin-films: A "
    "Look into Surface Transformations in High-voltage Cathodes",
    "totalShiftsRequested": 22,
}


class MockIOC(PVGroup):
    prop_api = mock.MagicMock()
    prop_api.getProposal.return_value = proposal
    esaf_api = mock.MagicMock()
    esaf_api.getEsaf.return_value = esaf
    api = BSSApi(proposal_api=prop_api, esaf_api=esaf_api)
    bss = SubGroup(
        apsbss.ApsBssGroup,
        prefix="bss:",
        api=api,
    )


@pytest.fixture
def mock_ioc():
    ioc = MockIOC(prefix="255idc:")
    yield ioc


@pytest.mark.asyncio
async def test_update_esaf(mock_ioc):
    """Does the IOC retrieve the ESAF data when ID is changed?"""
    ioc = mock_ioc
    # Set a value so we can test if the unused user fields are cleared
    await ioc.bss.esaf.user5.last_name.write("Statler")
    await ioc.bss.esaf.user9.last_name.write("Gonzo")
    # Load a new ESAF
    await ioc.bss.esaf.id.write("187973")
    # Check that the metadata was updated
    assert ioc.bss.esaf.title.value == esaf["esafTitle"]
    assert ioc.bss.esaf.description.value == esaf["description"]
    assert ioc.bss.esaf.end_date.value == "2018-07-11 23:00:00"
    assert ioc.bss.esaf.end_timestamp.value == 1531368000
    assert ioc.bss.esaf.status.value == esaf["esafStatus"]
    assert ioc.bss.esaf.sector.value == esaf["sector"]
    assert ioc.bss.esaf.start_date.value == "2018-06-11 08:00:00"
    assert ioc.bss.esaf.start_timestamp.value == 1528722000
    assert ioc.bss.esaf.raw.value == yaml.dump(esaf)
    assert ioc.bss.esaf.user_badges.value == "268176, 239241, 288878, 298130"
    assert ioc.bss.esaf.users.value == "Wolfman, De Andrade, Li, Judge"
    assert ioc.bss.esaf.users_in_pvs.value == 4
    assert ioc.bss.esaf.users_total.value == 4
    assert ioc.bss.esaf.user1.badge_number.value == "268176"
    assert ioc.bss.esaf.user1.email.value == "mwolf22@uic.edu"
    assert ioc.bss.esaf.user1.first_name.value == "Mark"
    assert ioc.bss.esaf.user1.last_name.value == "Wolfman"
    assert ioc.bss.esaf.user4.badge_number.value == "298130"
    assert ioc.bss.esaf.user4.email.value == "wjudge2@uic.edu"
    assert ioc.bss.esaf.user4.first_name.value == "William"
    assert ioc.bss.esaf.user4.last_name.value == "Judge"
    # Check that unused user fields are cleared
    assert ioc.bss.esaf.user5.last_name.value == ""
    assert ioc.bss.esaf.user9.last_name.value == ""


@pytest.mark.asyncio
async def test_update_proposal(mock_ioc):
    """Does the IOC retrieve the proposal data when ID is changed?"""
    ioc = mock_ioc
    # Load a new ESAF
    await ioc.bss.proposal.beamline.write("20-BM-B")
    await ioc.bss.esaf.cycle.write("2022-2")
    await ioc.bss.proposal.id.write("74204")
    # Check that the arguments were passed to the API propoerly
    ioc.bss._api._prop_api.getProposal.assert_called_with(
        "74204", cycle="2022-2", beamline="20-BM-B"
    )
    # Check that the metadata was updated
    assert ioc.bss.proposal.title.value == proposal["title"]
    assert ioc.bss.proposal.submitted_date.value == "2021-03-04 17:28:28-06:00"
    assert ioc.bss.proposal.submitted_timestamp.value == 1614900508
    assert ioc.bss.proposal.start_date.value == "2022-03-03 08:00:00-06:00"
    assert ioc.bss.proposal.start_timestamp.value == 1646316000
    assert ioc.bss.proposal.end_date.value == "2022-03-13 23:00:00-06:00"
    assert ioc.bss.proposal.end_timestamp.value == 1647230400
    assert ioc.bss.proposal.mail_in_flag.value == "Y"
    assert ioc.bss.proposal.proprietary_flag.value == "N"
    assert ioc.bss.proposal.user_badges.value == "85202, 64944, 287279"
    assert ioc.bss.proposal.users.value == "Toney, Sun, Wan"
    assert ioc.bss.proposal.users_in_pvs.value == 3
    assert ioc.bss.proposal.users_total.value == 3
    assert ioc.bss.proposal.user1.badge_number.value == "85202"
    assert ioc.bss.proposal.user1.email.value == "michael.toney@colorado.edu"
    assert ioc.bss.proposal.user1.first_name.value == "Michael"
    assert ioc.bss.proposal.user1.last_name.value == "Toney"
    assert ioc.bss.proposal.user1.pi_flag.value == "N"
    assert (
        ioc.bss.proposal.user1.institution.value == "University of Colorado at Boulder"
    )
    assert ioc.bss.proposal.user3.badge_number.value == "287279"
    assert ioc.bss.proposal.user3.email.value == "gangwan@stanford.edu"
    assert ioc.bss.proposal.user3.first_name.value == "Gang"
    assert ioc.bss.proposal.user3.last_name.value == "Wan"
    assert ioc.bss.proposal.user3.pi_flag.value == "Y"
    assert ioc.bss.proposal.user3.institution.value == "Stanford University"
    assert ioc.bss.proposal.raw.value == yaml.dump(proposal)
    # Check that unused user fields are cleared
    assert ioc.bss.proposal.user4.last_name.value == ""
    assert ioc.bss.proposal.user4.pi_flag.value == "N"
    assert ioc.bss.proposal.user4.institution.value == ""
    assert ioc.bss.proposal.user9.last_name.value == ""
