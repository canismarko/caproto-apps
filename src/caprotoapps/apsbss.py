from datetime import datetime
import asyncio
import yaml
from zoneinfo import ZoneInfo

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, SubGroup

from .apsbss_api import BSSApi


class User(PVGroup):
    badge_number = pvproperty(name="badgeNumber", record="stringout")
    email = pvproperty(name="email", record="stringout")
    first_name = pvproperty(name="firstName", record="stringout")
    last_name = pvproperty(name="lastName", record="stringout")


class ProposalUser(User):
    pi_flag = pvproperty(
        name="piFlag", record="bo", enum_strings=["Y", "N"], dtype=ChannelType.ENUM
    )
    institution = pvproperty(record="stringout")


class Proposal(PVGroup):
    beamline = pvproperty(record="stringout")
    end_date = pvproperty(name="endDate", record="stringout")
    end_timestamp = pvproperty(name="endTimestamp", record="longout")
    mail_in_flag = pvproperty(
        name="mailInFLag", record="bo", enum_strings=["Y", "N"], dtype=ChannelType.ENUM
    )
    id = pvproperty(record="stringout")
    proprietary_flag = pvproperty(
        name="propietaryFlag",
        record="bo",
        enum_strings=["Y", "N"],
        dtype=ChannelType.ENUM,
    )
    raw = pvproperty(record="waveform")
    start_date = pvproperty(name="startDate", record="stringout")
    start_timestamp = pvproperty(name="startTimestamp", record="longout")
    submitted_date = pvproperty(name="submittedDate", record="stringout")
    submitted_timestamp = pvproperty(name="submittedTimestamp", record="longout")
    title = pvproperty(record="waveform")
    user_badges = pvproperty(name="userBadges", record="waveform")
    users = pvproperty(record="waveform")
    users_in_pvs = pvproperty(record="longout")
    users_total = pvproperty(record="longout")

    user1 = SubGroup(ProposalUser, prefix="user1:")
    user2 = SubGroup(ProposalUser, prefix="user2:")
    user3 = SubGroup(ProposalUser, prefix="user3:")
    user4 = SubGroup(ProposalUser, prefix="user4:")
    user5 = SubGroup(ProposalUser, prefix="user5:")
    user6 = SubGroup(ProposalUser, prefix="user6:")
    user7 = SubGroup(ProposalUser, prefix="user7:")
    user8 = SubGroup(ProposalUser, prefix="user8:")
    user9 = SubGroup(ProposalUser, prefix="user9:")

    @id.putter
    async def id(self, instance, value):
        """Handler for when the ESAF ID changes.

        Retrieves updated ESAF data from the BSS system.

        """
        # Get proposal info from BSS system
        group = instance.group
        api = self.parent._api
        cycle = group.parent.esaf.cycle.value
        beamline = group.beamline.value
        proposal = await api.proposal_data(value, cycle=cycle, beamline=beamline)
        # Update the relevant ESAF data PVs
        coros = [
            group.title.write(proposal["title"]),
            group.mail_in_flag.write(proposal["mailInFlag"]),
            group.proprietary_flag.write(proposal["proprietaryFlag"]),
            group.raw.write(yaml.dump(proposal)),
            # Start and end dates/times
            group.submitted_date.write(proposal["submittedDate"]),
            group.submitted_timestamp.write(
                self.parent.convert_datestring(proposal["submittedDate"])
            ),
            group.start_date.write(proposal["startTime"]),
            group.start_timestamp.write(
                self.parent.convert_datestring(proposal["startTime"])
            ),
            group.end_date.write(proposal["endTime"]),
            group.end_timestamp.write(
                self.parent.convert_datestring(proposal["endTime"])
            ),
        ]
        # # Set values for aggregate user metadata
        users = proposal["experimenters"]
        max_users = 9
        coros.extend(
            [
                group.user_badges.write(", ".join([u["badge"] for u in users])),
                group.users.write(", ".join([u["lastName"] for u in users])),
                group.users_in_pvs.write(min(len(users), max_users)),
                group.users_total.write(len(users)),
            ]
        )
        # Set values for individual user metadata
        for idx, user in enumerate(users[:max_users]):
            user_group = getattr(group, f"user{idx+1}")
            coros.extend(
                [
                    user_group.badge_number.write(user["badge"]),
                    user_group.email.write(user["email"]),
                    user_group.first_name.write(user["firstName"]),
                    user_group.last_name.write(user["lastName"]),
                    user_group.pi_flag.write(user.get("piFlag", "N")),
                    user_group.institution.write(user["institution"]),
                ]
            )
        # Clear unused user metadata fields
        for num in range(len(users), max_users):
            print(num)
            user_group = getattr(group, f"user{num+1}")
            coros.extend(
                [
                    user_group.badge_number.write(""),
                    user_group.email.write(""),
                    user_group.first_name.write(""),
                    user_group.last_name.write(""),
                    user_group.pi_flag.write("N"),
                    user_group.institution.write(""),
                ]
            )
        # Write all the PV values concurrently
        await asyncio.gather(*coros)


class Esaf(PVGroup):
    cycle = pvproperty(record="stringout")
    description = pvproperty(record="waveform")
    end_date = pvproperty(name="endDate", record="stringout")
    end_timestamp = pvproperty(name="endTimestamp", record="longout")
    id = pvproperty(record="stringout")
    raw = pvproperty(record="waveform")
    status = pvproperty(record="stringout")
    sector = pvproperty(record="stringout")
    start_date = pvproperty(name="startDate", record="stringout")
    start_timestamp = pvproperty(name="startTimestamp", record="longout")
    title = pvproperty(record="waveform")
    user_badges = pvproperty(name="userBadges", record="waveform")
    users = pvproperty(record="waveform")
    users_in_pvs = pvproperty(record="longout")
    users_total = pvproperty(record="longout")

    user1 = SubGroup(User, prefix="user1:")
    user2 = SubGroup(User, prefix="user2:")
    user3 = SubGroup(User, prefix="user3:")
    user4 = SubGroup(User, prefix="user4:")
    user5 = SubGroup(User, prefix="user5:")
    user6 = SubGroup(User, prefix="user6:")
    user7 = SubGroup(User, prefix="user7:")
    user8 = SubGroup(User, prefix="user8:")
    user9 = SubGroup(User, prefix="user9:")

    @id.putter
    async def id(self, instance, value):
        """Handler for when the ESAF ID changes.

        Retrieves updated ESAF data from the BSS system.

        """
        api = self.parent._api
        esaf = await api.esaf_data(value)
        # Update the relevant ESAF data PVs
        group = instance.group
        coros = [
            group.title.write(esaf["esafTitle"]),
            group.description.write(esaf["description"]),
            group.status.write(esaf["esafStatus"]),
            group.sector.write(esaf["sector"]),
            group.raw.write(yaml.dump(esaf)),
            # Start and end dates/times
            group.start_date.write(esaf["experimentStartDate"]),
            group.start_timestamp.write(
                self.parent.convert_datestring(esaf["experimentStartDate"])
            ),
            group.end_date.write(esaf["experimentEndDate"]),
            group.end_timestamp.write(
                self.parent.convert_datestring(esaf["experimentEndDate"])
            ),
        ]
        # Set values for aggregate user metadata
        users = esaf["experimentUsers"]
        max_users = 9
        coros.extend(
            [
                group.user_badges.write(", ".join([u["badge"] for u in users])),
                group.users.write(", ".join([u["lastName"] for u in users])),
                group.users_in_pvs.write(min(len(users), max_users)),
                group.users_total.write(len(users)),
            ]
        )
        # Set values for individual user metadata
        for idx, user in enumerate(users[:max_users]):
            user_group = getattr(group, f"user{idx+1}")
            coros.extend(
                [
                    user_group.badge_number.write(user["badgeNumber"]),
                    user_group.email.write(user["email"]),
                    user_group.first_name.write(user["firstName"]),
                    user_group.last_name.write(user["lastName"]),
                ]
            )
        # Clear unused user metadata fields
        for num in range(len(users), max_users):
            print(num)
            user_group = getattr(group, f"user{num+1}")
            coros.extend(
                [
                    user_group.badge_number.write(""),
                    user_group.email.write(""),
                    user_group.first_name.write(""),
                    user_group.last_name.write(""),
                ]
            )
        # Write all the PV values concurrently
        await asyncio.gather(*coros)


class ApsBssGroup(PVGroup):
    proposal = SubGroup(Proposal, prefix="proposal:")
    esaf = SubGroup(Esaf, prefix="esaf:")
    status = pvproperty(record="stringout")
    ioc_host = pvproperty(record="stringout")
    ioc_user = pvproperty(record="stringout")

    def __init__(self, dm_host: str, *args, timezone="America/Chicago", api=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tzinfo = ZoneInfo(timezone)
        if api is None:
            api = BSSApi(dm_host)
        self._api = api

    def convert_datestring(self, datestring):
        """Convert a datestring to unix time."""
        # Convert to a datetime object
        try:
            # Timezone aware
            dt = datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S%z")
        except ValueError:
            # Time unaware, so convert to local time
            dt = datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=self.tzinfo)
        # Convert datetime object to unix timestamp
        return int(dt.timestamp())
