from caproto.server import PVGroup, pvproperty, SubGroup


class User(PVGroup):
    badge_number = pvproperty(name="badgeNumber", record="stringout")
    email = pvproperty(name="email", record="stringout")
    first_name = pvproperty(name="firstName", record="stringout")
    last_name = pvproperty(name="lastName", record="stringout")


class Proposal(PVGroup):

    beamline = pvproperty(record="stringout")
    endDate = pvproperty(record="stringout")
    mailInFlag = pvproperty(record="bo")
    id = pvproperty(record="stringout")
    proprietaryFlag = pvproperty(record="bo")
    raw = pvproperty(record="waveform")
    startDate = pvproperty(record="stringout")
    submittedDate = pvproperty(record="stringout")
    title = pvproperty(record="waveform")
    userBadges = pvproperty(record="waveform")
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


class Esaf(PVGroup):
    cycle = pvproperty(record="stringout")
    description = pvproperty(record="waveform")
    endDate = pvproperty(record="stringout")
    id = pvproperty(record="stringout")
    raw = pvproperty(record="waveform")
    status = pvproperty(record="stringout")
    sector = pvproperty(record="stringout")
    startDate = pvproperty(record="stringout")
    title = pvproperty(record="waveform")
    userBadges = pvproperty(name="userBadges", record="waveform")
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


class ApsBssGroup(PVGroup):
    proposal = SubGroup(Proposal, prefix="proposal:")
    esaf = SubGroup(Esaf, prefix="esaf:")
    status = pvproperty(record="stringout")
    ioc_host = pvproperty(record="stringout")
    ioc_user = pvproperty(record="stringout")
