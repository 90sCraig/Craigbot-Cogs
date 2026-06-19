"""
Community — a quiet, peer-driven recognition cog for Red.

Three signals of a healthy server, with the bot kept deliberately quiet:

  • The Fridge   — members ⭐ great messages; standout moments are saved.
  • High Fives   — members thank each other (by reaction, text, or command);
                   gratitude is counted, not announced.
  • Regulars     — quiet presence tracking (active days, never message-count XP).

Nothing shouts in chat. The bot adds a small reaction to acknowledge, then
celebrates everything together once a month in a single warm "Recap" post.

Designed to be the opposite of a grindy leveling system: no per-message XP,
no level-up spam, no public "you're inactive" signals, everything opt-out.
"""

import re
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import humanize_list, pagify

MEDALS = ("🥇", "🥈", "🥉")
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# A props/"high five" is credited when a message both mentions someone and
# carries a word of thanks. Kept conservative + paired with a mention and rate
# limits so ordinary chatter doesn't trip it.
PROPS_TRIGGERS = re.compile(
    r"\b(thanks|thank you|thank u|thx|ty|tysm|props|kudos|appreciate|"
    r"appreciated|high.?five|nice one|cheers)\b",
    re.IGNORECASE,
)


def _month_key(dt: datetime) -> str:
    """Calendar-month key like ``2026-06`` (sorts chronologically as a string)."""
    return f"{dt.year:04d}-{dt.month:02d}"


def _prev_month_key(dt: datetime) -> str:
    """The month-key for the month before ``dt``'s month."""
    if dt.month == 1:
        return f"{dt.year - 1:04d}-12"
    return f"{dt.year:04d}-{dt.month - 1:02d}"


def _months_back_key(dt: datetime, n: int) -> str:
    """Month-key for ``n`` whole months before ``dt`` (used for pruning)."""
    total = dt.year * 12 + (dt.month - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _month_label(key: str) -> str:
    """``2026-06`` → ``June 2026``."""
    try:
        year, month = key.split("-")
        return f"{MONTH_NAMES[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return key


def _parse_hhmm(value: str):
    """Parse ``HH:MM`` (24-hour) into ``(hour, minute)`` or ``None`` if invalid."""
    try:
        hour, minute = (int(p) for p in value.split(":"))
    except (ValueError, AttributeError):
        return None
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour, minute
    return None


class Community(commands.Cog):
    """Quiet, peer-driven recognition: The Fridge, High Fives, and a monthly Recap."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=20260619, force_registration=True
        )
        self.config.register_guild(
            enabled=True,

            # ── The Fridge (starboard) ──────────────────────────────────
            star_emoji="⭐",
            star_threshold=4,
            star_ack=True,            # add a tiny ✨ when a post first qualifies
            star_live_repost=False,   # whisper-quiet: hold highlights for the recap
            fridge_channel=None,      # only used when star_live_repost is on
            ignored_channels=[],      # channels excluded from stars + activity

            # ── High Fives (reputation) ─────────────────────────────────
            props_enabled=True,
            props_emoji="🙌",
            props_text_detect=True,   # credit "thanks @user" style messages
            props_ack=True,           # react with a small 🙏 to confirm
            props_daily_limit=5,      # how many a member can give per day
            props_cooldown_hours=12,  # before re-thanking the same person

            # ── Regulars (activity) ─────────────────────────────────────
            regulars_enabled=True,
            regular_min_days=5,       # active on ≥ N distinct days = a "regular"

            # ── Monthly Recap ───────────────────────────────────────────
            recap_enabled=True,
            recap_channel=None,
            recap_day=1,              # day of month to post (1–28)
            recap_time="10:00",       # HH:MM in UTC
            last_recap_month=None,    # month-key already recapped, e.g. "2026-06"

            # ── Stored data ─────────────────────────────────────────────
            # stars:  {message_id: {author, channel, month, acked, starrers:[uid]}}
            # props:  {uid: {"total": int, "months": {"2026-06": int}}}
            # givers: {uid: {"date": "2026-06-19", "count": int, "targets": {uid: iso}}}
            # activity: {uid: {"2026-06": [iso dates]}}
            stars={},
            props={},
            givers={},
            activity={},
        )
        # In-memory throttle so we touch config at most once per member per day
        # for activity (avoids a write on every single message).
        self._active_cache = {}
        self._scheduler.start()

    def cog_unload(self):
        self._scheduler.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Remove a user from all stored recognition data."""
        uid = str(user_id)
        for guild_id in await self.config.all_guilds():
            guild_conf = self.config.guild_from_id(guild_id)
            async with guild_conf.stars() as stars:
                for mid in [m for m, r in stars.items() if r.get("author") == user_id]:
                    del stars[mid]
                for rec in stars.values():
                    if user_id in rec.get("starrers", []):
                        rec["starrers"].remove(user_id)
            async with guild_conf.props() as props:
                props.pop(uid, None)
            async with guild_conf.givers() as givers:
                givers.pop(uid, None)
                for g in givers.values():
                    g.get("targets", {}).pop(uid, None)
            async with guild_conf.activity() as activity:
                activity.pop(uid, None)

    # ── Message tracking: activity + text-based high fives ───────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        uid = message.author.id

        # Cheap gate first: only touch config when it's this member's first
        # message today, or when the message could be a "thank you".
        new_day = self._active_cache.get(message.guild.id, {}).get(uid) != today
        maybe_props = bool(message.mentions) and bool(
            PROPS_TRIGGERS.search(message.content)
        )
        if not new_day and not maybe_props:
            return

        conf = await self.config.guild(message.guild).all()
        if not conf["enabled"]:
            return
        if message.channel.id in conf["ignored_channels"]:
            return

        if new_day and conf["regulars_enabled"]:
            await self._record_activity(message.guild, uid, now)

        if maybe_props and conf["props_enabled"] and conf["props_text_detect"]:
            await self._handle_text_props(message, conf)

    async def _record_activity(self, guild, user_id, now):
        """Mark today as an active day for this member (once per day)."""
        self._active_cache.setdefault(guild.id, {})[user_id] = now.date().isoformat()
        month, today = _month_key(now), now.date().isoformat()
        async with self.config.guild(guild).activity() as activity:
            days = activity.setdefault(str(user_id), {}).setdefault(month, [])
            if today not in days:
                days.append(today)

    async def _handle_text_props(self, message: discord.Message, conf: dict):
        """Credit a high five for a "thanks @user" style message."""
        # Don't double-credit when the message is actually a bot command.
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        credited = False
        for target in message.mentions:
            status = await self._register_props(
                message.guild, message.author, target.id, conf
            )
            credited = credited or status == "ok"
        if credited and conf["props_ack"]:
            try:
                await message.add_reaction(conf["props_emoji"] or "🙏")
            except discord.HTTPException:
                pass

    # ── Reaction tracking: stars + reaction high fives ───────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return
        emoji = str(payload.emoji)

        if emoji == conf["star_emoji"]:
            await self._handle_star_add(guild, payload, conf)
        elif conf["props_enabled"] and emoji == conf["props_emoji"]:
            await self._handle_reaction_props(guild, payload, conf)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        conf = await self.config.guild(guild).all()
        if not conf["enabled"] or str(payload.emoji) != conf["star_emoji"]:
            return
        async with self.config.guild(guild).stars() as stars:
            rec = stars.get(str(payload.message_id))
            if rec and payload.user_id in rec["starrers"]:
                rec["starrers"].remove(payload.user_id)

    async def _handle_star_add(self, guild, payload, conf):
        """Record a ⭐ and, when a post first qualifies, acknowledge it quietly."""
        channel = guild.get_channel(payload.channel_id)
        if channel is None or channel.id in conf["ignored_channels"]:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        # No credit for bots or for starring your own message.
        if message.author.bot or message.author.id == payload.user_id:
            return

        crossed = False
        async with self.config.guild(guild).stars() as stars:
            rec = stars.setdefault(
                str(message.id),
                {
                    "author": message.author.id,
                    "channel": channel.id,
                    "month": _month_key(message.created_at),
                    "acked": False,
                    "starrers": [],
                },
            )
            if payload.user_id not in rec["starrers"]:
                rec["starrers"].append(payload.user_id)
            if len(rec["starrers"]) >= conf["star_threshold"] and not rec["acked"]:
                rec["acked"] = True
                crossed = True

        if not crossed:
            return
        if conf["star_ack"]:
            try:
                await message.add_reaction("✨")
            except discord.HTTPException:
                pass
        # Whisper-quiet servers leave this off; if enabled, repost discreetly.
        if conf["star_live_repost"] and conf["fridge_channel"]:
            await self._repost_to_fridge(guild, message, conf)

    async def _repost_to_fridge(self, guild, message, conf):
        fridge = guild.get_channel(conf["fridge_channel"] or 0)
        if fridge is None or not fridge.permissions_for(guild.me).send_messages:
            return
        body = message.content or "*(no text)*"
        embed = discord.Embed(
            description=f"{body}\n\n[Jump to message]({message.jump_url})",
            color=discord.Color.gold(),
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        if message.attachments and message.attachments[0].content_type and \
                message.attachments[0].content_type.startswith("image"):
            embed.set_image(url=message.attachments[0].url)
        try:
            await fridge.send(f"{conf['star_emoji']} in {message.channel.mention}", embed=embed)
        except discord.HTTPException:
            pass

    async def _handle_reaction_props(self, guild, payload, conf):
        """Credit a high five when someone reacts with the props emoji."""
        channel = guild.get_channel(payload.channel_id)
        if channel is None or channel.id in conf["ignored_channels"]:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.author.bot:
            return
        giver = guild.get_member(payload.user_id)
        if giver is None:
            return
        # The act of reacting is its own acknowledgement — stay silent.
        await self._register_props(guild, giver, message.author.id, conf)

    # ── Props bookkeeping (shared by command / text / reaction paths) ────

    async def _register_props(self, guild, giver: discord.Member, target_id: int, conf):
        """Record one high five, enforcing self/bot/cooldown/daily-limit rules.

        Returns a status string: ``ok``, ``self``, ``bot``, ``cooldown`` or ``limit``.
        """
        if giver.bot or giver.id == target_id:
            return "self" if giver.id == target_id else "bot"
        target = guild.get_member(target_id)
        if target is None or target.bot:
            return "bot"

        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        async with self.config.guild(guild).givers() as givers:
            g = givers.setdefault(str(giver.id), {"date": today, "count": 0, "targets": {}})
            if g["date"] != today:  # reset the giver's daily allowance
                g.update(date=today, count=0, targets={})
            last = g["targets"].get(str(target_id))
            if last:
                elapsed = now - datetime.fromisoformat(last)
                if elapsed < timedelta(hours=conf["props_cooldown_hours"]):
                    return "cooldown"
            if g["count"] >= conf["props_daily_limit"]:
                return "limit"
            g["count"] += 1
            g["targets"][str(target_id)] = now.isoformat()

        month = _month_key(now)
        async with self.config.guild(guild).props() as props:
            p = props.setdefault(str(target_id), {"total": 0, "months": {}})
            p["total"] += 1
            p["months"][month] = p["months"].get(month, 0) + 1
        return "ok"

    # ── Scheduler: the monthly Recap ─────────────────────────────────────

    @tasks.loop(minutes=5)
    async def _scheduler(self):
        now = datetime.now(timezone.utc)
        for guild_id, conf in (await self.config.all_guilds()).items():
            if not conf.get("enabled") or not conf.get("recap_enabled"):
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(conf.get("recap_channel") or 0)
            if channel is None or not channel.permissions_for(guild.me).send_messages:
                continue
            await self._maybe_recap(guild, channel, conf, now)

    @_scheduler.before_loop
    async def _before_scheduler(self):
        await self.bot.wait_until_red_ready()

    async def _maybe_recap(self, guild, channel, conf, now):
        """Post the previous month's recap once, on/after the configured day+time."""
        recap_for = _prev_month_key(now)
        if conf.get("last_recap_month") == recap_for:
            return
        if now.day < max(1, min(28, conf.get("recap_day", 1))):
            return
        hhmm = _parse_hhmm(conf.get("recap_time", ""))
        if hhmm is None or (now.hour, now.minute) < hhmm:
            return

        # Mark handled first so a transient send failure can't double-post.
        await self.config.guild(guild).last_recap_month.set(recap_for)
        embed = self._build_recap_embed(guild, conf, recap_for, discord.Color.gold())
        if embed is None:  # nothing happened last month — stay quiet
            await self._prune(guild, now)
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass
        await self._prune(guild, now)

    async def _prune(self, guild, now):
        """Drop data older than ~6 months so storage stays small."""
        cutoff = _months_back_key(now, 6)
        async with self.config.guild(guild).stars() as stars:
            for mid in [m for m, r in stars.items() if r.get("month", "") < cutoff]:
                del stars[mid]
        async with self.config.guild(guild).props() as props:
            for uid in list(props):
                months = props[uid]["months"]
                for mk in [k for k in months if k < cutoff]:
                    del months[mk]
        async with self.config.guild(guild).activity() as activity:
            for uid in list(activity):
                for mk in [k for k in activity[uid] if k < cutoff]:
                    del activity[uid][mk]
                if not activity[uid]:
                    del activity[uid]

    # ── Recap rendering ──────────────────────────────────────────────────

    def _build_recap_embed(self, guild, conf, month_key, color):
        """Compose the recap embed for ``month_key`` (or ``None`` if empty)."""
        star_lines = self._recap_star_lines(guild, conf, month_key)
        props_lines = self._recap_props_lines(guild, conf, month_key)
        regular_line = self._recap_regulars_line(guild, conf, month_key)

        if not (star_lines or props_lines or regular_line):
            return None

        embed = discord.Embed(
            title=f"📰 The {_month_label(month_key)} Recap",
            color=color,
            description="A quiet look back at the month. Thanks for being here. 💛",
        )
        if star_lines:
            embed.add_field(
                name="⭐ Moments of the month",
                value="\n".join(star_lines),
                inline=False,
            )
        if props_lines:
            embed.add_field(
                name="🙌 Most appreciated",
                value="\n".join(props_lines),
                inline=False,
            )
        if regular_line:
            embed.add_field(
                name="👋 This month's regulars",
                value=regular_line,
                inline=False,
            )
        return embed

    def _recap_star_lines(self, guild, conf, month_key, limit=3):
        rows = []
        for mid, rec in conf.get("stars", {}).items():
            if rec.get("month") != month_key:
                continue
            count = len(rec.get("starrers", []))
            if count < conf["star_threshold"]:
                continue
            rows.append((count, rec, mid))
        rows.sort(key=lambda r: r[0], reverse=True)

        lines = []
        for i, (count, rec, mid) in enumerate(rows[:limit]):
            member = guild.get_member(rec["author"])
            name = member.display_name if member else "Someone"
            link = f"https://discord.com/channels/{guild.id}/{rec['channel']}/{mid}"
            prefix = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            lines.append(f"{prefix} **{name}** · {count} ⭐ — [jump]({link})")
        return lines

    def _recap_props_lines(self, guild, conf, month_key, limit=3):
        rows = []
        for uid, p in conf.get("props", {}).items():
            count = p.get("months", {}).get(month_key, 0)
            if count:
                rows.append((count, int(uid)))
        rows.sort(key=lambda r: r[0], reverse=True)

        lines = []
        for i, (count, uid) in enumerate(rows[:limit]):
            member = guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            prefix = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            plural = "high five" if count == 1 else "high fives"
            lines.append(f"{prefix} **{name}** · {count} {plural}")
        return lines

    def _recap_regulars_line(self, guild, conf, month_key, limit=15):
        rows = []
        for uid, months in conf.get("activity", {}).items():
            days = len(months.get(month_key, []))
            if days >= conf["regular_min_days"]:
                rows.append((days, int(uid)))
        rows.sort(key=lambda r: r[0], reverse=True)

        names = []
        for _days, uid in rows[:limit]:
            member = guild.get_member(uid)
            if member:
                names.append(member.display_name)
        if not names:
            return ""
        extra = len(rows) - len(names)
        line = humanize_list([f"**{n}**" for n in names])
        if extra > 0:
            line += f" and {extra} other{'s' if extra != 1 else ''}"
        return line

    # ── Member commands ──────────────────────────────────────────────────

    @commands.guild_only()
    @commands.group(name="community", aliases=["comm"], invoke_without_command=True)
    async def community(self, ctx: commands.Context):
        """Community recognition: high fives, highlights, and the monthly recap."""
        await ctx.send_help(ctx.command)

    @community.command(name="thank", aliases=["props", "kudos", "highfive", "hf"])
    async def community_thank(
        self, ctx: commands.Context, member: discord.Member, *, reason: str = ""
    ):
        """Give someone a high five.

        Example: `[p]community thank @Dave for the great advice`
        """
        if not await self.config.guild(ctx.guild).props_enabled():
            await ctx.send("High fives are turned off on this server.")
            return
        status = await self._register_props(
            ctx.guild, ctx.author, member.id, await self.config.guild(ctx.guild).all()
        )
        replies = {
            "ok": f"🙌 You gave **{member.display_name}** a high five!",
            "self": "You can't high-five yourself (nice try 😄).",
            "bot": "You can only high-five real members.",
            "cooldown": f"You've recently high-fived **{member.display_name}** — give it a little while.",
            "limit": "You've reached today's high-five limit. More tomorrow!",
        }
        await ctx.send(replies.get(status, "Something went wrong."))

    @community.command(name="standing", aliases=["myprops", "highfives"])
    async def community_standing(
        self, ctx: commands.Context, member: discord.Member = None
    ):
        """See how many high fives you (or another member) have received."""
        member = member or ctx.author
        p = (await self.config.guild(ctx.guild).props()).get(str(member.id))
        if not p or not p.get("total"):
            await ctx.send(f"**{member.display_name}** hasn't received any high fives yet.")
            return
        this_month = p.get("months", {}).get(_month_key(datetime.now(timezone.utc)), 0)
        await ctx.send(
            f"🙌 **{member.display_name}** — {this_month} high five"
            f"{'' if this_month == 1 else 's'} this month, {p['total']} all-time."
        )

    @community.command(name="highlights", aliases=["fridge", "moments"])
    async def community_highlights(self, ctx: commands.Context):
        """Show this month's standout (most-starred) moments so far."""
        conf = await self.config.guild(ctx.guild).all()
        month_key = _month_key(datetime.now(timezone.utc))
        lines = self._recap_star_lines(ctx.guild, conf, month_key, limit=5)
        if not lines:
            await ctx.send("No standout moments yet this month — keep the ⭐ coming!")
            return
        await self._send_embed(ctx, "⭐ Moments so far this month", lines)

    @community.command(name="regulars")
    async def community_regulars(self, ctx: commands.Context):
        """Show who's been a regular this month."""
        conf = await self.config.guild(ctx.guild).all()
        month_key = _month_key(datetime.now(timezone.utc))
        line = self._recap_regulars_line(ctx.guild, conf, month_key, limit=30)
        if not line:
            await ctx.send("No regulars to show yet this month.")
            return
        await self._send_embed(ctx, "👋 This month's regulars", [line])

    @community.command(name="recap")
    async def community_recap(self, ctx: commands.Context, which: str = "last"):
        """Preview the recap. Pass `this` for the current month, `last` for last month."""
        now = datetime.now(timezone.utc)
        month_key = _month_key(now) if which.lower() in ("this", "current") else _prev_month_key(now)
        conf = await self.config.guild(ctx.guild).all()
        embed = self._build_recap_embed(ctx.guild, conf, month_key, await ctx.embed_color())
        if embed is None:
            await ctx.send(f"Nothing to recap for **{_month_label(month_key)}** yet.")
            return
        await ctx.send(embed=embed)

    # ── Admin: settings ──────────────────────────────────────────────────

    @community.group(name="set", invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def community_set(self, ctx: commands.Context):
        """Configure the Community cog (admin / Manage Server only)."""
        await ctx.send_help(ctx.command)

    @community_set.command(name="enable")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_enable(self, ctx: commands.Context, on_off: bool):
        """Turn the whole cog on or off for this server."""
        await self.config.guild(ctx.guild).enabled.set(on_off)
        await ctx.send(f"Community is now {'enabled' if on_off else 'disabled'}.")

    @community_set.command(name="staremoji")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_staremoji(self, ctx: commands.Context, emoji: str):
        """Set the emoji members react with to nominate a moment (default ⭐)."""
        await self.config.guild(ctx.guild).star_emoji.set(emoji)
        await ctx.send(f"Star emoji set to {emoji}.")

    @community_set.command(name="starthreshold", aliases=["threshold"])
    @commands.admin_or_permissions(manage_guild=True)
    async def set_starthreshold(self, ctx: commands.Context, count: int):
        """Set how many reactions a message needs to count as a moment."""
        if count < 1:
            await ctx.send("Threshold must be at least 1.")
            return
        await self.config.guild(ctx.guild).star_threshold.set(count)
        await ctx.send(f"A message now needs **{count}** reactions to count.")

    @community_set.command(name="starack")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_starack(self, ctx: commands.Context, on_off: bool):
        """Toggle the small ✨ the bot adds when a moment first qualifies."""
        await self.config.guild(ctx.guild).star_ack.set(on_off)
        await ctx.send(f"Star acknowledgement {'on' if on_off else 'off'}.")

    @community_set.command(name="livefridge")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_livefridge(
        self, ctx: commands.Context, on_off: bool, channel: discord.TextChannel = None
    ):
        """Toggle live reposting of moments to a fridge channel (off by default).

        Whisper-quiet servers leave this off and let moments surface in the recap.
        Example: `[p]community set livefridge on #the-fridge`
        """
        await self.config.guild(ctx.guild).star_live_repost.set(on_off)
        if channel:
            await self.config.guild(ctx.guild).fridge_channel.set(channel.id)
        msg = f"Live fridge reposting {'on' if on_off else 'off'}."
        if on_off and not (channel or await self.config.guild(ctx.guild).fridge_channel()):
            msg += " Set a channel with `[p]community set livefridge on #channel`."
        await ctx.send(msg)

    @community_set.command(name="ignore")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_ignore(self, ctx: commands.Context, channel: discord.TextChannel):
        """Toggle a channel as ignored (excluded from stars + activity)."""
        async with self.config.guild(ctx.guild).ignored_channels() as ignored:
            if channel.id in ignored:
                ignored.remove(channel.id)
                await ctx.send(f"{channel.mention} is no longer ignored.")
            else:
                ignored.append(channel.id)
                await ctx.send(f"{channel.mention} will be ignored.")

    @community_set.command(name="props")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_props(self, ctx: commands.Context, on_off: bool):
        """Turn high fives on or off."""
        await self.config.guild(ctx.guild).props_enabled.set(on_off)
        await ctx.send(f"High fives {'enabled' if on_off else 'disabled'}.")

    @community_set.command(name="propsemoji")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_propsemoji(self, ctx: commands.Context, emoji: str):
        """Set the reaction emoji that gives a high five (default 🙌)."""
        await self.config.guild(ctx.guild).props_emoji.set(emoji)
        await ctx.send(f"High-five emoji set to {emoji}.")

    @community_set.command(name="propstext")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_propstext(self, ctx: commands.Context, on_off: bool):
        """Toggle crediting "thanks @user" style messages."""
        await self.config.guild(ctx.guild).props_text_detect.set(on_off)
        await ctx.send(f"Text-based high fives {'on' if on_off else 'off'}.")

    @community_set.command(name="propslimit")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_propslimit(self, ctx: commands.Context, per_day: int):
        """Set how many high fives a member can give per day."""
        if per_day < 1:
            await ctx.send("The limit must be at least 1.")
            return
        await self.config.guild(ctx.guild).props_daily_limit.set(per_day)
        await ctx.send(f"Members can now give **{per_day}** high fives per day.")

    @community_set.command(name="propscooldown")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_propscooldown(self, ctx: commands.Context, hours: int):
        """Set the cooldown before re-thanking the same person (hours)."""
        if hours < 0:
            await ctx.send("Cooldown can't be negative.")
            return
        await self.config.guild(ctx.guild).props_cooldown_hours.set(hours)
        await ctx.send(f"Cooldown set to **{hours}h** per person.")

    @community_set.command(name="regulars")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_regulars(self, ctx: commands.Context, on_off: bool):
        """Turn quiet activity (regulars) tracking on or off."""
        await self.config.guild(ctx.guild).regulars_enabled.set(on_off)
        await ctx.send(f"Regulars tracking {'enabled' if on_off else 'disabled'}.")

    @community_set.command(name="regularmindays")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_regularmindays(self, ctx: commands.Context, days: int):
        """Set how many active days in a month make someone a regular."""
        if days < 1:
            await ctx.send("Must be at least 1 day.")
            return
        await self.config.guild(ctx.guild).regular_min_days.set(days)
        await ctx.send(f"A regular is now someone active **{days}** days in a month.")

    @community_set.command(name="recap")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_recap(self, ctx: commands.Context, on_off: bool):
        """Turn the monthly recap on or off."""
        await self.config.guild(ctx.guild).recap_enabled.set(on_off)
        msg = f"Monthly recap {'enabled' if on_off else 'disabled'}."
        if on_off and not await self.config.guild(ctx.guild).recap_channel():
            msg += " Set a channel with `[p]community set recapchannel #channel`."
        await ctx.send(msg)

    @community_set.command(name="recapchannel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_recapchannel(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ):
        """Set the channel where the monthly recap is posted. Omit to clear."""
        await self.config.guild(ctx.guild).recap_channel.set(channel.id if channel else None)
        await ctx.send(
            f"Recap channel set to {channel.mention}." if channel else "Recap channel cleared."
        )

    @community_set.command(name="recapday")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_recapday(self, ctx: commands.Context, day: int):
        """Set the day of the month the recap posts (1–28)."""
        if not 1 <= day <= 28:
            await ctx.send("Pick a day between 1 and 28.")
            return
        await self.config.guild(ctx.guild).recap_day.set(day)
        await ctx.send(f"Recap will post on day **{day}** of each month.")

    @community_set.command(name="recaptime")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_recaptime(self, ctx: commands.Context, time: str):
        """Set the recap time as HH:MM in 24-hour UTC (e.g. `10:00`)."""
        hhmm = _parse_hhmm(time)
        if hhmm is None:
            await ctx.send("Please give a time as `HH:MM` in 24-hour UTC, e.g. `10:00`.")
            return
        await self.config.guild(ctx.guild).recap_time.set(f"{hhmm[0]:02d}:{hhmm[1]:02d}")
        await ctx.send(f"Recap time set to {hhmm[0]:02d}:{hhmm[1]:02d} UTC.")

    @community_set.command(name="postrecap")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_postrecap(self, ctx: commands.Context, which: str = "last"):
        """Post a recap right now (for testing). `this` or `last` month."""
        now = datetime.now(timezone.utc)
        month_key = _month_key(now) if which.lower() in ("this", "current") else _prev_month_key(now)
        conf = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(conf["recap_channel"] or 0) or ctx.channel
        embed = self._build_recap_embed(ctx.guild, conf, month_key, discord.Color.gold())
        if embed is None:
            await ctx.send(f"Nothing to recap for **{_month_label(month_key)}**.")
            return
        await channel.send(embed=embed)
        if channel != ctx.channel:
            await ctx.send(f"Recap posted in {channel.mention}.")

    @community_set.command(name="show", aliases=["settings"])
    @commands.admin_or_permissions(manage_guild=True)
    async def set_show(self, ctx: commands.Context):
        """Show the current Community settings."""
        c = await self.config.guild(ctx.guild).all()
        recap_channel = ctx.guild.get_channel(c["recap_channel"]) if c["recap_channel"] else None
        fridge = ctx.guild.get_channel(c["fridge_channel"]) if c["fridge_channel"] else None
        ignored = ", ".join(
            f"<#{cid}>" for cid in c["ignored_channels"]
        ) or "none"
        lines = [
            f"**Enabled:** {'on' if c['enabled'] else 'off'}",
            "",
            "__The Fridge__",
            f"**Star emoji / threshold:** {c['star_emoji']} · {c['star_threshold']}",
            f"**Star ✨ ack:** {'on' if c['star_ack'] else 'off'}",
            f"**Live fridge reposts:** {'on' if c['star_live_repost'] else 'off'}"
            f"{f' → {fridge.mention}' if fridge else ''}",
            f"**Ignored channels:** {ignored}",
            "",
            "__High Fives__",
            f"**Enabled:** {'on' if c['props_enabled'] else 'off'} · emoji {c['props_emoji']}",
            f"**Text detection:** {'on' if c['props_text_detect'] else 'off'} · "
            f"ack {'on' if c['props_ack'] else 'off'}",
            f"**Limits:** {c['props_daily_limit']}/day · {c['props_cooldown_hours']}h cooldown",
            "",
            "__Regulars__",
            f"**Enabled:** {'on' if c['regulars_enabled'] else 'off'} · "
            f"≥ {c['regular_min_days']} active days/month",
            "",
            "__Monthly Recap__",
            f"**Enabled:** {'on' if c['recap_enabled'] else 'off'}",
            f"**Channel:** {recap_channel.mention if recap_channel else 'not set'}",
            f"**Posts:** day {c['recap_day']} at {c['recap_time']} UTC",
        ]
        await self._send_embed(ctx, "🏘️ Community Settings", lines)

    # ── Output helper (embed with text fallback + pagination) ────────────

    async def _send_embed(self, ctx, title: str, lines: list, footer: str = ""):
        body = "\n".join(lines) if lines else "Nothing to show yet."
        use_embed = await ctx.embed_requested()
        page_len = 3900 if use_embed else 1800
        pages = list(pagify(body, delims=["\n"], page_length=page_len)) or [""]
        total = len(pages)
        for i, page in enumerate(pages):
            heading = title if total == 1 else f"{title} ({i + 1}/{total})"
            is_last = i == total - 1
            if use_embed:
                embed = discord.Embed(
                    title=heading, description=page, color=await ctx.embed_color()
                )
                if footer and is_last:
                    embed.set_footer(text=footer)
                await ctx.send(embed=embed)
            else:
                text = f"**{heading}**\n{page}"
                if footer and is_last:
                    text += f"\n{footer}"
                await ctx.send(text)
