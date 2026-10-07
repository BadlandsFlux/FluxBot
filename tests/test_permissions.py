from bot.permissions import (
    PERM_ADMINISTRATOR,
    PERM_BAN_MEMBERS,
    PERM_KICK_MEMBERS,
    PERM_MANAGE_GUILD,
    compute_permissions,
    has_permission,
    hierarchy_violation,
    is_moderator,
    permission_name,
    role_is_privileged,
)

EVERYONE_ROLE = {"id": "guild1", "permissions": "0"}


def make_guild(owner_id="owner1", roles=None):
    return {"id": "guild1", "owner_id": owner_id, "roles": [EVERYONE_ROLE, *(roles or [])]}


def make_member(user_id, role_ids=None):
    return {"user": {"id": user_id}, "roles": list(role_ids or [])}


def test_compute_permissions_combines_everyone_and_role_bits():
    mod_role = {"id": "r1", "permissions": str(PERM_KICK_MEMBERS)}
    guild = make_guild(roles=[mod_role])
    member = make_member("u1", ["r1"])
    assert compute_permissions(guild, member) & PERM_KICK_MEMBERS


def test_has_permission_administrator_implies_everything():
    assert has_permission(PERM_ADMINISTRATOR, PERM_BAN_MEMBERS) is True


def test_has_permission_without_the_bit_is_false():
    assert has_permission(PERM_KICK_MEMBERS, PERM_BAN_MEMBERS) is False


def test_is_moderator_owner_always_passes():
    guild = make_guild(owner_id="owner1")
    member = make_member("owner1")
    assert is_moderator(guild, member, PERM_BAN_MEMBERS) is True


def test_is_moderator_requires_the_right_bit():
    guild = make_guild()
    member = make_member("u1")
    assert is_moderator(guild, member, PERM_KICK_MEMBERS) is False


def test_is_moderator_true_with_matching_role():
    mod_role = {"id": "r1", "permissions": str(PERM_KICK_MEMBERS)}
    guild = make_guild(roles=[mod_role])
    member = make_member("u1", ["r1"])
    assert is_moderator(guild, member, PERM_KICK_MEMBERS) is True


def test_permission_name_everyone_for_none():
    assert permission_name(None) == "Everyone"


def test_permission_name_known_bit():
    assert permission_name(PERM_MANAGE_GUILD) == "Manage Guild"


def test_role_is_privileged_true_for_admin_bit():
    guild = make_guild(roles=[{"id": "r1", "permissions": str(PERM_ADMINISTRATOR)}])
    assert role_is_privileged(guild, "r1") is True


def test_role_is_privileged_false_for_cosmetic_role():
    guild = make_guild(roles=[{"id": "r1", "permissions": "0"}])
    assert role_is_privileged(guild, "r1") is False


def test_role_is_privileged_false_for_unknown_role():
    guild = make_guild()
    assert role_is_privileged(guild, "does-not-exist") is False


def test_hierarchy_violation_blocks_acting_on_yourself():
    guild = make_guild()
    member = make_member("u1")
    assert hierarchy_violation(guild, "u1", member, "u1", member) is not None


def test_hierarchy_violation_blocks_acting_on_the_owner():
    guild = make_guild(owner_id="owner1")
    mod = make_member("mod1", ["r1"])
    owner_member = make_member("owner1")
    assert hierarchy_violation(guild, "mod1", mod, "owner1", owner_member) is not None


def test_hierarchy_violation_owner_can_act_on_anyone():
    guild = make_guild(owner_id="owner1", roles=[{"id": "r1", "permissions": "0", "position": 5}])
    owner_member = make_member("owner1")
    target = make_member("u2", ["r1"])
    assert hierarchy_violation(guild, "owner1", owner_member, "u2", target) is None


def test_hierarchy_violation_blocks_equal_or_higher_role():
    role = {"id": "r1", "permissions": "0", "position": 5}
    guild = make_guild(roles=[role])
    mod = make_member("mod1", ["r1"])
    target = make_member("u2", ["r1"])
    assert hierarchy_violation(guild, "mod1", mod, "u2", target) is not None


def test_hierarchy_violation_allows_acting_down_the_hierarchy():
    high_role = {"id": "r1", "permissions": "0", "position": 10}
    low_role = {"id": "r2", "permissions": "0", "position": 1}
    guild = make_guild(roles=[high_role, low_role])
    mod = make_member("mod1", ["r1"])
    target = make_member("u2", ["r2"])
    assert hierarchy_violation(guild, "mod1", mod, "u2", target) is None
