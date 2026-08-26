"""Permission checks for moderation commands.

CAVEAT: Fluxer's own permission-bit reference isn't fully published
yet. Fluxer is modeled closely on Discord's guild/role/permission
shape (roles carry a `permissions` bitfield string, members carry a
`roles` list, guilds carry an `owner_id`), so this uses Discord's
well-known bit values as a best-effort default. If your instance's
`/guilds/{id}` or `/guilds/{id}/roles` response uses different bit
positions, update PERM_* below to match — everything else in the bot
just calls `is_moderator()` / `has_permission()`.
"""
from __future__ import annotations

from typing import Any, Optional

PERM_CREATE_INSTANT_INVITE = 1 << 0
PERM_KICK_MEMBERS = 1 << 1
PERM_BAN_MEMBERS = 1 << 2
PERM_ADMINISTRATOR = 1 << 3
PERM_MANAGE_CHANNELS = 1 << 4
PERM_MANAGE_GUILD = 1 << 5
PERM_ADD_REACTIONS = 1 << 6
PERM_VIEW_AUDIT_LOG = 1 << 7
PERM_VIEW_CHANNEL = 1 << 10
PERM_SEND_MESSAGES = 1 << 11
PERM_MANAGE_MESSAGES = 1 << 13
PERM_EMBED_LINKS = 1 << 14
PERM_ATTACH_FILES = 1 << 15
PERM_MENTION_EVERYONE = 1 << 17
PERM_CONNECT = 1 << 20
PERM_SPEAK = 1 << 21
PERM_MUTE_MEMBERS = 1 << 22
PERM_DEAFEN_MEMBERS = 1 << 23
PERM_MOVE_MEMBERS = 1 << 24
PERM_CHANGE_NICKNAME = 1 << 26
PERM_MANAGE_NICKNAMES = 1 << 27
PERM_MANAGE_ROLES = 1 << 28
PERM_MANAGE_WEBHOOKS = 1 << 29
PERM_MANAGE_EXPRESSIONS = 1 << 30
PERM_MANAGE_EVENTS = 1 << 33
PERM_MANAGE_THREADS = 1 << 34
PERM_MODERATE_MEMBERS = 1 << 40  # timeout

# Any of these on a role make it unsafe to hand out via autorole (granted
# silently to every new member on join) or reaction roles (granted to
# anyone who clicks), regardless of the truthfully-scoped permission a mod
# used to set that mapping up in the first place. Manage Guild is what
# gates !autorole/!reactionrole themselves, so without this check, anyone
# who can configure either feature could point it at a role carrying
# Administrator (or any of the others below) and self-promote, or hand
# that out to the whole server passively.
PRIVILEGED_PERMISSION_BITS = (
    PERM_ADMINISTRATOR | PERM_MANAGE_GUILD | PERM_KICK_MEMBERS
    | PERM_BAN_MEMBERS | PERM_MODERATE_MEMBERS | PERM_MANAGE_MESSAGES
    | PERM_MANAGE_ROLES | PERM_MANAGE_CHANNELS | PERM_MANAGE_WEBHOOKS
)

# For DISPLAY (activity log role-create/update entries showing "what
# permissions"), a fuller list than PRIVILEGED_PERMISSION_BITS needs,
# still not Discord's entire permission set (some are quite obscure),
# but the ones a mod actually cares about seeing in a log entry.
PERMISSION_NAMES = {
    PERM_CREATE_INSTANT_INVITE: "Create Invite",
    PERM_KICK_MEMBERS: "Kick Members",
    PERM_BAN_MEMBERS: "Ban Members",
    PERM_ADMINISTRATOR: "Administrator",
    PERM_MANAGE_CHANNELS: "Manage Channels",
    PERM_MANAGE_GUILD: "Manage Guild",
    PERM_ADD_REACTIONS: "Add Reactions",
    PERM_VIEW_AUDIT_LOG: "View Audit Log",
    PERM_VIEW_CHANNEL: "View Channel",
    PERM_SEND_MESSAGES: "Send Messages",
    PERM_MANAGE_MESSAGES: "Manage Messages",
    PERM_EMBED_LINKS: "Embed Links",
    PERM_ATTACH_FILES: "Attach Files",
    PERM_MENTION_EVERYONE: "Mention Everyone",
    PERM_CONNECT: "Connect",
    PERM_SPEAK: "Speak",
    PERM_MUTE_MEMBERS: "Mute Members",
    PERM_DEAFEN_MEMBERS: "Deafen Members",
    PERM_MOVE_MEMBERS: "Move Members",
    PERM_CHANGE_NICKNAME: "Change Nickname",
    PERM_MANAGE_NICKNAMES: "Manage Nicknames",
    PERM_MANAGE_ROLES: "Manage Roles",
    PERM_MANAGE_WEBHOOKS: "Manage Webhooks",
    PERM_MANAGE_EXPRESSIONS: "Manage Expressions",
    PERM_MANAGE_EVENTS: "Manage Events",
    PERM_MANAGE_THREADS: "Manage Threads",
    PERM_MODERATE_MEMBERS: "Moderate Members",
}


def decode_permissions(bitfield: int) -> list[str]:
    """Every permission name whose bit is set, in a stable, readable order.
    Unrecognized bits (present in the field but not in PERMISSION_NAMES,
    either a permission not worth surfacing in a log or one that postdates
    this list) are silently omitted rather than shown as a raw number,
    since a log entry full of unlabeled bit values isn't actually useful
    to anyone reading it."""
    return [name for bit, name in PERMISSION_NAMES.items() if bitfield & bit]


def permission_name(bit: Optional[int]) -> str:
    if bit is None:
        return "Everyone"
    return PERMISSION_NAMES.get(bit, f"Permission bit {bit}")


def compute_permissions(guild: dict, member: dict) -> int:
    """Combine base @everyone role + the member's roles into one bitfield."""
    role_map = {str(r["id"]): r for r in guild.get("roles", [])}
    total = 0
    everyone = role_map.get(str(guild.get("id")))  # @everyone role id == guild id, Discord convention
    if everyone:
        total |= int(everyone.get("permissions", 0))
    for role_id in member.get("roles", []):
        role = role_map.get(str(role_id))
        if role:
            total |= int(role.get("permissions", 0))
    return total


def has_permission(perms: int, bit: int) -> bool:
    return bool(perms & PERM_ADMINISTRATOR) or bool(perms & bit)


def is_moderator(guild: dict, member: dict, required_bit: int = PERM_KICK_MEMBERS) -> bool:
    if str(guild.get("owner_id")) == str(member.get("user", {}).get("id", member.get("user_id", ""))):
        return True
    return has_permission(compute_permissions(guild, member), required_bit)


def highest_role_position(guild: dict, member: dict) -> int:
    """Position of the member's highest role. -1 if they hold no roles that
    resolve against the guild's role list at all (Discord convention: a
    higher `position` value means a more senior role)."""
    role_map = {str(r["id"]): r for r in guild.get("roles", [])}
    positions = [
        int(role_map[str(rid)].get("position", 0))
        for rid in member.get("roles", [])
        if str(rid) in role_map
    ]
    return max(positions) if positions else -1


def hierarchy_violation(guild: dict, moderator_id: str, moderator_member: dict,
                         target_id: str, target_member: dict) -> Optional[str]:
    """Returns a human-readable reason the action should be blocked, or None
    if it's allowed. Checked independently of (and in addition to) the raw
    permission-bit check in is_moderator(): having Kick Members doesn't by
    itself mean you should be able to act on the server owner, yourself, or
    someone whose highest role outranks (or ties) yours."""
    moderator_id, target_id = str(moderator_id), str(target_id)
    if moderator_id == target_id:
        return "You can't do that to yourself."
    if str(guild.get("owner_id")) == target_id:
        return "You can't do that to the server owner."
    if str(guild.get("owner_id")) == moderator_id:
        return None  # the owner outranks every role, nothing further to check
    if highest_role_position(guild, target_member) >= highest_role_position(guild, moderator_member):
        return "You can't do that to someone with an equal or higher role than you."
    return None


def role_is_privileged(guild: dict, role_id: str) -> bool:
    """True if the given role carries a permission serious enough that
    handing it out automatically (autorole) or to anyone who reacts
    (reaction roles) would itself be a privilege-escalation path, rather
    than a cosmetic/access role. Unknown role IDs (e.g. already deleted)
    return False, nothing to protect against there."""
    role_map = {str(r["id"]): r for r in guild.get("roles", [])}
    role = role_map.get(str(role_id))
    if not role:
        return False
    return bool(int(role.get("permissions", 0)) & PRIVILEGED_PERMISSION_BITS)
