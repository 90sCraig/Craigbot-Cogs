"""Dependency-isolated tests for eligibility and assignment safety."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


def decorator(*args, **kwargs):
    def wrap(fn):
        fn.command = decorator
        return fn
    return wrap


discord = types.ModuleType("discord")
discord.Role = object
discord.HTTPException = type("HTTPException", (Exception,), {})
discord.NotFound = type("NotFound", (discord.HTTPException,), {})
discord.ClientException = type("ClientException", (Exception,), {})
commands = types.SimpleNamespace(
    Cog=type("Cog", (), {"listener": staticmethod(decorator)}),
    group=decorator, guild_only=decorator, admin_or_permissions=decorator,
)
core = types.ModuleType("redbot.core")
core.commands = commands
core.Config = object
sys.modules.update({"discord": discord, "redbot": types.ModuleType("redbot"), "redbot.core": core})
spec = importlib.util.spec_from_file_location(
    "defaultrole_under_test", Path(__file__).parents[1] / "defaultrole" / "defaultrole.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Role:
    def __init__(self, id, position):
        self.id, self.position, self.managed = id, position, False

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= other.position


class AssignmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = {"enabled": True, "role": 1, "blocked_role": 2}
        self.role, self.blocked = Role(1, 1), Role(2, 2)
        self.guild = types.SimpleNamespace(
            id=10, get_role=lambda id: {1: self.role, 2: self.blocked}.get(id),
            me=types.SimpleNamespace(top_role=Role(3, 3),
                guild_permissions=types.SimpleNamespace(manage_roles=True)))
        self.member = types.SimpleNamespace(id=20, guild=self.guild, bot=False,
            pending=False, roles=[], add_roles=AsyncMock())
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.cog = object.__new__(module.DefaultRole)
        self.cog.config = types.SimpleNamespace(guild=lambda guild:
            types.SimpleNamespace(all=AsyncMock(return_value=self.settings)))
        self.cog.bot = types.SimpleNamespace(cog_disabled_in_guild=AsyncMock(return_value=False))

    async def test_human_assigned_after_fresh_fetch(self):
        self.assertEqual(await self.cog.assign(self.member), "assigned")
        self.guild.fetch_member.assert_awaited_once_with(20)
        self.member.add_roles.assert_awaited_once()

    async def test_exclusions_do_not_write(self):
        for field, value, expected in [("bot", True, "bots"),
                ("pending", True, "screening"), ("roles", [self.blocked], "unverified"),
                ("roles", [self.role], "already assigned")]:
            original = getattr(self.member, field)
            setattr(self.member, field, value)
            self.assertEqual(await self.cog.assign(self.member), expected)
            setattr(self.member, field, original)
        self.member.add_roles.assert_not_awaited()

    async def test_fresh_member_overrides_stale_preview(self):
        fresh = types.SimpleNamespace(**vars(self.member))
        fresh.pending = True
        self.guild.fetch_member.return_value = fresh
        self.assertEqual(await self.cog.assign(self.member), "screening")
        self.member.add_roles.assert_not_awaited()

    async def test_disable_stops_writes(self):
        self.settings["enabled"] = False
        self.assertEqual(await self.cog.assign(self.member), "disabled")
        self.guild.fetch_member.assert_not_awaited()

    async def test_missing_blocked_role_fails_closed(self):
        self.settings["blocked_role"] = 999
        self.assertEqual(await self.cog.assign(self.member), "configuration error")
        self.member.add_roles.assert_not_awaited()

    async def test_hierarchy_and_permission_fail_closed(self):
        self.guild.me.top_role = self.role
        self.assertEqual(await self.cog.assign(self.member), "configuration error")
        self.guild.me.top_role = Role(3, 3)
        self.guild.me.guild_permissions.manage_roles = False
        self.assertEqual(await self.cog.assign(self.member), "configuration error")
        self.member.add_roles.assert_not_awaited()

    async def test_departed_member_is_skipped(self):
        self.guild.fetch_member.side_effect = discord.NotFound()
        self.assertEqual(await self.cog.assign(self.member), "left server")

    async def test_write_failure_is_counted(self):
        self.member.add_roles.side_effect = discord.HTTPException()
        self.assertEqual(await self.cog.assign(self.member), "failed")

    async def test_block_removal_and_screening_trigger_retry(self):
        self.cog.schedule = unittest.mock.Mock()
        before = types.SimpleNamespace(pending=False, roles=[self.blocked])
        await self.cog.on_member_update(before, self.member)
        self.cog.schedule.assert_called_once_with(self.member)
        self.cog.schedule.reset_mock()
        before.roles, before.pending = [], True
        await self.cog.on_member_update(before, self.member)
        self.cog.schedule.assert_called_once_with(self.member)


if __name__ == "__main__":
    unittest.main()
