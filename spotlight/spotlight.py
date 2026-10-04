"""Spotlight — keep time-limited announcements visible without flooding chat."""

import logging
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import tasks
from redbot.core import Config, commands

log = logging.getLogger("red.craigbot.spotlight")

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", re.IGNORECASE)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _utcnow():
    return datetime.now(timezone.utc)


def _safe_zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return timezone.utc


def _parse_hhmm(value):
    try:
        parsed = datetime.strptime(value, "%H:%M")
        return time(parsed.hour, parsed.minute)
    except (TypeError, ValueError):
        return None


def _parse_bool(value, default):
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in {"yes", "y", "on", "true", "1"}:
        return True
    if value in {"no", "n", "off", "false", "0"}:
        return False
    raise ValueError("Use yes or no.")


def _parse_end(value, timezone_name):
    """Parse a duration (7d, 48h) or local date/time into a UTC datetime."""
    value = value.strip()
    match = _DURATION_RE.fullmatch(value)
    if match:
        amount = int(match.group(1))
        if amount < 1:
            raise ValueError("The duration must be greater than zero.")
        unit = match.group(2).lower()
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
        }[unit]
        return _utcnow() + delta

    local_zone = _safe_zone(timezone_name)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(hour=23, minute=59)
            return parsed.replace(tzinfo=local_zone).astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError("Use a duration like `7d` or a date like `2026-10-11 21:00`.")


class AddSpotlightModal(discord.ui.Modal):
    def __init__(self, cog, message, defaults):
        super().__init__(title="Add to Spotlight", timeout=300)
        self.cog = cog
        self.message = message

        self.ends = discord.ui.TextInput(
            label="Ends in / at",
            placeholder="7d or 2026-10-11 21:00",
            required=True,
            max_length=32,
        )
        self.reminder_days = discord.ui.TextInput(
            label="Reminder interval in days (optional)",
            placeholder=f"Default: {defaults['reminder_days']}",
            required=False,
            max_length=3,
        )
        self.mention = discord.ui.TextInput(
            label="Mention configured role? (optional)",
            placeholder=f"Default: {'yes' if defaults['mention_default'] else 'no'}",
            required=False,
            max_length=5,
        )
        self.end_notice = discord.ui.TextInput(
            label="Post an ended notice? (optional)",
            placeholder=f"Default: {'yes' if defaults['end_announce'] else 'no'}",
            required=False,
            max_length=5,
        )
        self.add_item(self.ends)
        self.add_item(self.reminder_days)
        self.add_item(self.mention)
        self.add_item(self.end_notice)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            days = None
            if str(self.reminder_days).strip():
                days = int(str(self.reminder_days).strip())
                if not 1 <= days <= 365:
                    raise ValueError("Reminder days must be between 1 and 365.")
            item_id = await self.cog.create_spotlight(
                self.message,
                ends_text=str(self.ends),
                reminder_days=days,
                mention_text=str(self.mention),
                end_notice_text=str(self.end_notice),
            )
        except (ValueError, discord.HTTPException) as exc:
            await interaction.followup.send(f"I couldn't add that Spotlight: {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            f"Added **{item_id}** to Spotlight. Use `/spotlight` or your prefix command "
            "to view active announcements.",
            ephemeral=True,
        )


class Spotlight(commands.Cog):
    """Keep important announcements visible until they expire."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=20261004, force_registration=True)
        self.config.register_guild(
            destination_channel=None,
            timezone="UTC",
            reminder_days=1,
            reminder_time="12:00",
            mention_role=None,
            mention_default=False,
            end_announce=True,
            counter=0,
            items={},
        )
        self.message_action = app_commands.ContextMenu(
            name="Add to Spotlight",
            callback=self._context_add,
        )
        self.scheduler.start()

    async def cog_load(self):
        self.bot.tree.add_command(self.message_action)

    def cog_unload(self):
        self.scheduler.cancel()
        self.bot.tree.remove_command(self.message_action.name, type=self.message_action.type)

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        for guild_id in await self.config.all_guilds():
            async with self.config.guild_from_id(guild_id).items() as items:
                for item_id in [
                    key for key, item in items.items() if item.get("author_id") == user_id
                ]:
                    del items[item_id]

    @app_commands.default_permissions(administrator=True)
    async def _context_add(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Spotlight can only be used in a server.", ephemeral=True
            )
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Only server administrators can add Spotlights.", ephemeral=True
            )
            return
        defaults = await self.config.guild(interaction.guild).all()
        await interaction.response.send_modal(AddSpotlightModal(self, message, defaults))

    @staticmethod
    def _snapshot(message):
        attachments = [
            {
                "filename": attachment.filename,
                "url": str(attachment.url),
                "content_type": attachment.content_type,
            }
            for attachment in message.attachments
        ]
        first_embed = message.embeds[0].to_dict() if message.embeds else None
        return {
            "source_channel_id": message.channel.id,
            "source_message_id": message.id,
            "source_url": message.jump_url,
            "content": message.content,
            "author_id": message.author.id,
            "author_name": message.author.display_name,
            "author_avatar": str(message.author.display_avatar.url),
            "attachments": attachments,
            "source_embed": first_embed,
        }

    def _next_reminder(self, after, conf, days):
        zone = _safe_zone(conf.get("timezone"))
        local = after.astimezone(zone)
        reminder_time = _parse_hhmm(conf.get("reminder_time")) or time(12, 0)
        target_date = local.date() + timedelta(days=days)
        target = datetime.combine(target_date, reminder_time, tzinfo=zone)
        return target.astimezone(timezone.utc)

    async def create_spotlight(
        self,
        message,
        *,
        ends_text,
        reminder_days=None,
        mention_text="",
        end_notice_text="",
    ):
        guild = message.guild
        conf = await self.config.guild(guild).all()
        ends_at = _parse_end(ends_text, conf["timezone"])
        if ends_at <= _utcnow():
            raise ValueError("The ending time must be in the future.")

        days = reminder_days or conf["reminder_days"]
        mention = _parse_bool(mention_text, conf["mention_default"])
        end_notice = _parse_bool(end_notice_text, conf["end_announce"])

        counter = conf["counter"] + 1
        item_id = f"SPOT-{counter:03d}"
        created = _utcnow()
        item = {
            **self._snapshot(message),
            "id": item_id,
            "created_at": created.timestamp(),
            "ends_at": ends_at.timestamp(),
            "reminder_days": days,
            "mention": mention,
            "end_announce": end_notice,
            "next_reminder_at": self._next_reminder(created, conf, days).timestamp(),
            "last_reminder_message_id": None,
        }
        await self.config.guild(guild).counter.set(counter)
        async with self.config.guild(guild).items() as items:
            items[item_id] = item
        return item_id

    @staticmethod
    def _image_url(item):
        for attachment in item.get("attachments", []):
            content_type = attachment.get("content_type") or ""
            filename = (attachment.get("filename") or "").lower()
            if content_type.startswith("image/") or filename.endswith(_IMAGE_EXTS):
                return attachment.get("url")
        source_embed = item.get("source_embed") or {}
        return (source_embed.get("image") or {}).get("url") or (
            source_embed.get("thumbnail") or {}
        ).get("url")

    def _build_embed(self, item, *, ended=False):
        timestamp = int(item["ends_at"])
        content = item.get("content", "").strip()
        source_embed = item.get("source_embed") or {}
        if not content:
            parts = [source_embed.get("title", ""), source_embed.get("description", "")]
            content = "\n\n".join(part for part in parts if part)
        if not content:
            content = "*This announcement has no text.*"
        if len(content) > 3800:
            content = content[:3799] + "…"

        title = "Spotlight ended" if ended else "Spotlight"
        color = discord.Color.dark_grey() if ended else discord.Color.gold()
        embed = discord.Embed(title=title, description=content, color=color)
        embed.set_author(
            name=item.get("author_name") or "Original author",
            icon_url=item.get("author_avatar") or None,
        )
        embed.add_field(
            name="Ended" if ended else "Ends",
            value=f"<t:{timestamp}:F>\n<t:{timestamp}:R>",
            inline=True,
        )
        embed.add_field(
            name="Original announcement",
            value=f"[View message]({item['source_url']})",
            inline=True,
        )
        image = self._image_url(item)
        if image:
            embed.set_image(url=image)

        other_files = [
            f"[{attachment['filename']}]({attachment['url']})"
            for attachment in item.get("attachments", [])
            if attachment.get("url") != image
        ]
        if other_files:
            embed.add_field(name="Attachments", value="\n".join(other_files)[:1024], inline=False)
        embed.set_footer(text=item["id"])
        return embed

    async def _destination(self, guild, conf, item):
        channel_id = conf.get("destination_channel") or item["source_channel_id"]
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel

    async def _send_item(self, guild, conf, item, *, ended=False):
        channel = await self._destination(guild, conf, item)
        if channel is None:
            raise ValueError("The Spotlight destination channel is unavailable.")

        # Fetch the source when possible so edits and expiring attachment URLs
        # are reflected. The stored snapshot remains a fallback if the source
        # message is later unavailable.
        live_item = item
        source_channel = guild.get_channel(item["source_channel_id"])
        if source_channel is not None:
            try:
                source_message = await source_channel.fetch_message(item["source_message_id"])
                live_item = {**item, **self._snapshot(source_message)}
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        content = None
        allowed = discord.AllowedMentions.none()
        if not ended and item.get("mention") and conf.get("mention_role"):
            role = guild.get_role(conf["mention_role"])
            if role:
                content = role.mention
                allowed = discord.AllowedMentions(roles=[role])
        return await channel.send(
            content=content,
            embed=self._build_embed(live_item, ended=ended),
            allowed_mentions=allowed,
        )

    async def _end_item(self, guild, item_id, item, conf, *, announce=None):
        should_announce = item.get("end_announce", conf["end_announce"])
        if announce is not None:
            should_announce = announce
        if should_announce:
            try:
                await self._send_item(guild, conf, item, ended=True)
            except (ValueError, discord.HTTPException):
                log.exception("Failed to announce the end of %s in guild %s", item_id, guild.id)
        async with self.config.guild(guild).items() as items:
            items.pop(item_id, None)

    @tasks.loop(minutes=1)
    async def scheduler(self):
        now = _utcnow()
        for guild_id, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            previous_reminders = {
                item.get("last_reminder_message_id")
                for item in conf.get("items", {}).values()
                if item.get("last_reminder_message_id")
            }
            for item_id, item in list(conf.get("items", {}).items()):
                if now.timestamp() >= item["ends_at"]:
                    await self._end_item(guild, item_id, item, conf)
                    continue
                if now.timestamp() < item.get("next_reminder_at", float("inf")):
                    continue
                channel = await self._destination(guild, conf, item)
                if channel is None:
                    continue
                # Treat any active Spotlight reminder as a quiet-channel guard.
                # This matters when several Spotlights share one destination:
                # their reminder posts should not make one another look like
                # fresh conversation and trigger another batch the next day.
                if channel.last_message_id in previous_reminders:
                    continue
                try:
                    reminder = await self._send_item(guild, conf, item)
                except (ValueError, discord.HTTPException):
                    log.exception("Failed to remind Spotlight %s in guild %s", item_id, guild.id)
                    continue
                item["last_reminder_message_id"] = reminder.id
                item["next_reminder_at"] = self._next_reminder(
                    now, conf, item.get("reminder_days", conf["reminder_days"])
                ).timestamp()
                async with self.config.guild(guild).items() as items:
                    if item_id in items:
                        items[item_id] = item

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_red_ready()

    async def _show_active(self, ctx):
        conf = await self.config.guild(ctx.guild).all()
        items = sorted(conf["items"].values(), key=lambda item: item["ends_at"])
        if not items:
            prefix = ctx.clean_prefix
            embed = discord.Embed(
                title="Spotlight quick start",
                description=(
                    "There are no active Spotlights yet. Spotlight keeps important, "
                    "time-limited announcements visible without repeatedly pinning them."
                ),
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="Add an announcement (admins)",
                value=(
                    "**Easiest:** Right-click or long-press the announcement, then choose "
                    "**Apps → Add to Spotlight**.\n"
                    f"**Command:** Reply to the announcement with `{prefix}spotlight add 7d` "
                    "(durations such as `48h` and `2w` also work)."
                ),
                inline=False,
            )
            embed.add_field(
                name="View active Spotlights",
                value=(
                    f"Run `{prefix}spotlight` or `{prefix}spotlight list`. Each entry shows "
                    "its time remaining and a link to the original announcement."
                ),
                inline=False,
            )
            embed.add_field(
                name="Configuration and help (admins)",
                value=(
                    f"Run `{prefix}spotlightset show` to see this server's settings, or "
                    f"`{prefix}help spotlight` for all Spotlight commands."
                ),
                inline=False,
            )
            await ctx.send(embed=embed)
            return
        for item in items:
            await ctx.send(embed=self._build_embed(item))

    @commands.guild_only()
    @commands.hybrid_group(name="spotlight", invoke_without_command=True)
    async def spotlight(self, ctx):
        """Show and manage active announcements."""
        await self._show_active(ctx)

    @spotlight.command(name="list", aliases=["active"])
    async def spotlight_list(self, ctx):
        """Show every active Spotlight."""
        await self._show_active(ctx)

    @spotlight.command(name="add")
    @commands.admin()
    async def spotlight_add(self, ctx, ends: str):
        """Add the replied-to message for a duration such as `7d` or `48h`."""
        reference = ctx.message.reference
        if reference is None or reference.message_id is None:
            await ctx.send("Reply to the announcement you want to add, then run this command.")
            return
        try:
            message = reference.resolved
            if not isinstance(message, discord.Message):
                message = await ctx.channel.fetch_message(reference.message_id)
            item_id = await self.create_spotlight(message, ends_text=ends)
        except (ValueError, discord.HTTPException) as exc:
            await ctx.send(f"I couldn't add that Spotlight: {exc}")
            return
        await ctx.send(f"Added **{item_id}** to Spotlight.")

    @spotlight.command(name="end")
    @commands.admin()
    async def spotlight_end(self, ctx, item_id: str = None):
        """End a Spotlight by ID, or by replying to its source/reminder."""
        conf = await self.config.guild(ctx.guild).all()
        if item_id:
            item_id = item_id.upper()
        elif ctx.message.reference and ctx.message.reference.message_id:
            replied = ctx.message.reference.message_id
            item_id = next(
                (
                    key
                    for key, item in conf["items"].items()
                    if replied
                    in {item.get("source_message_id"), item.get("last_reminder_message_id")}
                ),
                None,
            )
        if not item_id or item_id not in conf["items"]:
            await ctx.send(
                f"I couldn't find that active Spotlight. Use `{ctx.clean_prefix}spotlight` "
                "to see its ID."
            )
            return
        await self._end_item(ctx.guild, item_id, conf["items"][item_id], conf)
        await ctx.send(f"Ended **{item_id}**.")

    @commands.guild_only()
    @commands.group(name="spotlightset")
    @commands.admin()
    async def spotlightset(self, ctx):
        """Configure Spotlight for this server."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @spotlightset.command(name="show")
    async def spotlightset_show(self, ctx):
        """Show this server's Spotlight settings."""
        conf = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(conf["destination_channel"] or 0)
        role = ctx.guild.get_role(conf["mention_role"] or 0)
        await ctx.send(
            "**Spotlight settings**\n"
            f"Destination: {channel.mention if channel else 'original message channel'}\n"
            f"Timezone: `{conf['timezone']}`\n"
            f"Reminder: every **{conf['reminder_days']} day(s)** at "
            f"**{conf['reminder_time']}**\n"
            f"Mention role: {role.mention if role else 'none'}\n"
            f"Mention by default: **{'on' if conf['mention_default'] else 'off'}**\n"
            f"Ended announcement: **{'on' if conf['end_announce'] else 'off'}**\n"
            f"Active Spotlights: **{len(conf['items'])}**"
        )

    @spotlightset.command(name="channel")
    async def spotlightset_channel(self, ctx, channel: discord.TextChannel = None):
        """Set one reminder channel; omit it to use each original channel."""
        await self.config.guild(ctx.guild).destination_channel.set(channel.id if channel else None)
        await ctx.send(
            f"Spotlight reminders will go to {channel.mention}."
            if channel
            else "Spotlights will be reposted in their original channels."
        )

    @spotlightset.command(name="timezone")
    async def spotlightset_timezone(self, ctx, timezone_name: str):
        """Set an IANA timezone, such as `America/New_York`."""
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await ctx.send("That timezone wasn't recognized. Try `America/New_York`.")
            return
        await self.config.guild(ctx.guild).timezone.set(timezone_name)
        await ctx.send(f"Spotlight timezone set to **{timezone_name}**.")

    @spotlightset.command(name="interval")
    async def spotlightset_interval(self, ctx, days: int):
        """Set the default number of days between reminders."""
        if not 1 <= days <= 365:
            await ctx.send("Choose a reminder interval between 1 and 365 days.")
            return
        await self.config.guild(ctx.guild).reminder_days.set(days)
        await ctx.send(f"Default reminders will repeat every **{days} day(s)**.")

    @spotlightset.command(name="time")
    async def spotlightset_time(self, ctx, hhmm: str):
        """Set the reminder time as `HH:MM` in the configured timezone."""
        if _parse_hhmm(hhmm) is None:
            await ctx.send("Use 24-hour `HH:MM` format, such as `12:00`.")
            return
        await self.config.guild(ctx.guild).reminder_time.set(hhmm)
        await ctx.send(f"Default reminder time set to **{hhmm}**.")

    @spotlightset.command(name="mentionrole")
    async def spotlightset_mentionrole(self, ctx, role: discord.Role = None):
        """Set the optional role reminders may mention; omit it to clear."""
        await self.config.guild(ctx.guild).mention_role.set(role.id if role else None)
        await ctx.send(
            f"Spotlights may mention {role.mention}."
            if role
            else "The Spotlight mention role has been cleared."
        )

    @spotlightset.command(name="mentiondefault")
    async def spotlightset_mentiondefault(self, ctx, enabled: bool):
        """Set whether new Spotlights mention the configured role by default."""
        await self.config.guild(ctx.guild).mention_default.set(enabled)
        await ctx.send(f"Mentions are now **{'on' if enabled else 'off'}** by default.")

    @spotlightset.command(name="endannounce")
    async def spotlightset_endannounce(self, ctx, enabled: bool):
        """Set whether new Spotlights announce when they end by default."""
        await self.config.guild(ctx.guild).end_announce.set(enabled)
        await ctx.send(f"Ended announcements are now **{'on' if enabled else 'off'}** by default.")
