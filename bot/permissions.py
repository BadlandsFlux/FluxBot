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

PERM_KICK_MEMBERS = 1 << 1
PERM_BAN_MEMBERS = 1 << 2
PERM_ADMINISTRATOR = 1 << 3
PERM_MANAGE_GUILD = 1 << 5
PERM_MANAGE_MESSAGES = 1 << 13
PERM_MODERATE_MEMBERS = 1 << 40  # timeout

PERMISSION_NAMES = {
    PERM_KICK_MEMBERS: "Kick Members",
    PERM_BAN_MEMBERS: "Ban Members",
    PERM_ADMINISTRATOR: "Administrator",
    PERM_MANAGE_GUILD: "Manage Guild",
    PERM_MANAGE_MESSAGES: "Manage Messages",
    PERM_MODERATE_MEMBERS: "Moderate Members",
}


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
