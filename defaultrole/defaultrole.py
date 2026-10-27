"""Conservative default roles for human members."""

import asyncio
import logging
from collections import Counter

import discord
from redbot.core import Config, commands

log = logging.getLogger("red.craigbot.defaultrole")


def skip_reason(member, settings):
    if member.bot:
        return "bots"
    if member.pending:
        return "screening"
    roles = {role.id for role in member.roles}
    if settings["blocked_role"] in roles:
        return "unverified"
    if settings["role"] in roles:
        return "already assigned"
    return None


class DefaultRole(commands.Cog):
    """Assign a default role after screening and verification."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2026102701, force_registration=True)
        self.config.register_guild(enabled=False, role=None, blocked_role=None)
        self.jobs = {}
        self.backfills = set()

    def cog_unload(self):
        for task in self.jobs.values():
            task.cancel()

    async def red_delete_data_for_user(self, **kwargs):
        pass  # No user data is persisted.

    def problem(self, guild, settings):
        role = guild.get_role(settings["role"]) if settings["role"] else None
        if role is None or role.is_default() or role.managed:
            return "Set a normal, assignable default role first."
        if settings["blocked_role"] == role.id:
            return "The default and blocked roles must be different."
        if not settings["blocked_role"] or guild.get_role(settings["blocked_role"]) is None:
            return "Set an existing blocked role (such as Unverified) first."
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles or role >= me.top_role:
            return "Craigbot needs Manage Roles and a role above the default role."
        return None

    async def assign(self, member):
        settings = await self.config.guild(member.guild).all()
        if not settings["enabled"] or await self.bot.cog_disabled_in_guild(self, member.guild):
            return "disabled"
        problem = self.problem(member.guild, settings)
        if problem:
            log.warning("DefaultRole guild %s: %s", member.guild.id, problem)
            return "configuration error"
        # Refresh immediately before writing: preview/cache may be stale.
        try:
            member = await member.guild.fetch_member(member.id)
            reason = skip_reason(member, settings)
            if reason:
                return reason
            await member.add_roles(member.guild.get_role(settings["role"]),
                                   reason="Craigbot default human-member role")
        except discord.NotFound:
            return "left server"
        except discord.HTTPException:
            log.exception("DefaultRole assignment failed in guild %s", member.guild.id)
            return "failed"
        return "assigned"

    def schedule(self, member):
        key = (member.guild.id, member.id)
        if member.bot or key in self.jobs:
            return

        async def run():
            try:
                # Let verification bots attach their blocking roles first.
                await asyncio.sleep(30)
                await self.assign(member)
            except Exception:
                log.exception("DefaultRole join handler failed in guild %s", member.guild.id)
            finally:
                self.jobs.pop(key, None)

        self.jobs[key] = asyncio.create_task(run())

    @commands.Cog.listener()
    async def on_member_join(self, member):
        self.schedule(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        settings = await self.config.guild(after.guild).all()
        blocked = settings["blocked_role"]
        removed_block = (blocked in {r.id for r in before.roles}
                         and blocked not in {r.id for r in after.roles})
        if (before.pending and not after.pending) or removed_block:
            self.schedule(after)

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def defaultrole(self, ctx):
        """Configure automatic roles; use preview before backfill."""

    @defaultrole.command(name="role")
    async def set_role(self, ctx, *, role: discord.Role):
        """Set the default role (for example VHS Detectives)."""
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.send("Choose a normal role below Craigbot's highest role.")
        if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            return await ctx.send("Choose a role below your highest role.")
        await self.config.guild(ctx.guild).role.set(role.id)
        await ctx.send("Default role saved.")

    @defaultrole.command(name="blocked")
    async def set_blocked(self, ctx, *, role: discord.Role):
        """Skip members with this role, typically Unverified."""
        await self.config.guild(ctx.guild).blocked_role.set(role.id)
        await ctx.send("Blocked role saved. Members become eligible when it is removed.")

    @defaultrole.command(name="enable")
    async def enable(self, ctx):
        """Enable automatic assignment after validating configuration."""
        problem = self.problem(ctx.guild, await self.config.guild(ctx.guild).all())
        if problem:
            return await ctx.send(problem)
        if not self.bot.intents.members:
            return await ctx.send("Enable the Server Members Intent for Craigbot first.")
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Enabled. New eligible humans receive the role after 30 seconds.")

    @defaultrole.command(name="disable")
    async def disable(self, ctx):
        """Stop future assignments, including an ongoing backfill."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Disabled. Roles already assigned are kept.")

    @defaultrole.command(name="status")
    async def status(self, ctx):
        """Show settings and configuration problems."""
        settings = await self.config.guild(ctx.guild).all()
        await ctx.send(f"Enabled: {settings['enabled']}\nDefault role ID: {settings['role']}\n"
                       f"Blocked role ID: {settings['blocked_role']}\n"
                       f"Check: {self.problem(ctx.guild, settings) or 'OK'}")

    async def members(self, ctx):
        # Fetch the full member list, not just the potentially partial cache.
        return [member async for member in ctx.guild.fetch_members(limit=None)]

    @defaultrole.command(name="preview")
    async def preview(self, ctx):
        """Count eligible humans and exclusions without changing roles."""
        settings = await self.config.guild(ctx.guild).all()
        problem = self.problem(ctx.guild, settings)
        if problem:
            return await ctx.send(problem)
        try:
            counts = Counter(skip_reason(m, settings) or "eligible" for m in await self.members(ctx))
        except (discord.HTTPException, discord.ClientException):
            return await ctx.send("Could not fetch members. Check Server Members Intent and try again.")
        await ctx.send("Preview: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    @defaultrole.command(name="backfill")
    async def backfill(self, ctx, confirmation: str = ""):
        """Run with `confirm` to assign missing roles. Safe to repeat."""
        if confirmation.lower() != "confirm":
            return await ctx.send("Run defaultrole preview, then defaultrole backfill confirm to apply.")
        if ctx.guild.id in self.backfills:
            return await ctx.send("A backfill is already running here.")
        settings = await self.config.guild(ctx.guild).all()
        problem = self.problem(ctx.guild, settings)
        if problem or not settings["enabled"]:
            return await ctx.send(problem or "Enable defaultrole first.")
        self.backfills.add(ctx.guild.id)
        counts = Counter()
        try:
            members = await self.members(ctx)
            await ctx.send("Backfill started. Each member will be checked again before assignment.")
            for member in members:
                result = await self.assign(member)
                counts[result] += 1
                if result in {"disabled", "configuration error"}:
                    break
                await asyncio.sleep(0.5)
            await ctx.send("Backfill results: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        except (discord.HTTPException, discord.ClientException):
            log.exception("DefaultRole backfill failed in guild %s", ctx.guild.id)
            await ctx.send("Backfill interrupted; check the bot log and member intent. It is safe to rerun.")
        finally:
            self.backfills.discard(ctx.guild.id)
