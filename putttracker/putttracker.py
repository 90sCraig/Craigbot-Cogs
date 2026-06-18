"""
PuttTracker — Discord Red cog for tracking putt.day scores.
Parses score posts, maintains weekly and overall leaderboards.

Score format: putt.day #36 ⛳ 20/6 +14
  - Day #: 36
  - Strokes / Par: 20/6
  - Relative to par: +14

Install:
  [p]loadlocalcog putttracker
  Or drop putttracker/ into your Red cogs directory and [p]load putttracker
"""

import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import discord
from discord.ext import tasks
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.views import ConfirmView

SCORE_PATTERN = re.compile(
    r"putt\.day\s+#(\d+)\s+⛳\s+(\d+)/(\d+)\s+([+-]?\d+)",
    re.IGNORECASE,
)

MEDALS = ("🥇", "🥈", "🥉")


def _week_key(dt: datetime) -> str:
    """ISO week key like ``2026-W25``.

    Uses ISO year/week (``isocalendar``) so 53-week years and the days at
    the start/end of a calendar year are bucketed correctly.
    """
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _fmt_rel(value: int) -> str:
    """Format a relative-to-par value with an explicit sign (e.g. ``+14``)."""
    return f"{value:+d}"


class PuttTracker(commands.Cog):
    """Track putt.day scores with weekly and overall leaderboards."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=20260617, force_registration=True
        )
        # Scores are scoped per guild so each server has its own leaderboard
        # (member names can only be resolved within the guild they belong to).
        self.config.register_guild(
            weeks={},
            auto_board=True,              # reply with the day board on a new score
            announce_channel=None,        # channel id for reminders/announcements
            daily_reminder=False,         # post a "play today" reminder
            reminder_time="12:00",        # HH:MM in UTC
            reminder_message="🏌️ A new putt.day is live — post your score!",
            weekly_announce=False,        # announce last week's winner
            last_reminder_date=None,      # ISO date string of last reminder sent
            last_weekly_week=None,        # ISO week key already announced
        )
        # weeks = {
        #   "2026-W25": {
        #     "user_id_str": {
        #       "scores": {"36": {"strokes": 20, "par": 6, "relative": 14, "timestamp": "..."}},
        #       "total_strokes": 20, "total_par": 6, "rounds": 1
        #     }
        #   }
        # }
        self._scheduler.start()

    def cog_unload(self):
        self._scheduler.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        """Delete a user's stored putt.day scores (GDPR/end-user data)."""
        uid = str(user_id)
        all_guilds = await self.config.all_guilds()
        for guild_id in all_guilds:
            async with self.config.guild_from_id(guild_id).weeks() as weeks:
                changed = False
                for week in weeks.values():
                    if uid in week:
                        del week[uid]
                        changed = True
                # Drop now-empty weeks to keep storage tidy.
                if changed:
                    for wk in [k for k, v in weeks.items() if not v]:
                        del weeks[wk]

    # ── Scheduler ─────────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _scheduler(self):
        """Once a minute, fire any due daily reminders / weekly announcements."""
        now = datetime.now(timezone.utc)
        for guild_id, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(conf.get("announce_channel") or 0)
            if channel is None or not channel.permissions_for(guild.me).send_messages:
                continue
            if conf.get("daily_reminder"):
                await self._maybe_daily_reminder(guild, channel, conf, now)
            if conf.get("weekly_announce"):
                await self._maybe_weekly_announce(guild, channel, conf, now)

    @_scheduler.before_loop
    async def _before_scheduler(self):
        await self.bot.wait_until_red_ready()

    async def _maybe_daily_reminder(self, guild, channel, conf, now):
        """Send the daily reminder once per day, at/after the configured time."""
        today = now.date().isoformat()
        if conf.get("last_reminder_date") == today:
            return
        try:
            hour, minute = (int(p) for p in conf["reminder_time"].split(":"))
        except (ValueError, KeyError):
            return
        if (now.hour, now.minute) < (hour, minute):
            return
        await self.config.guild(guild).last_reminder_date.set(today)
        try:
            await channel.send(conf.get("reminder_message") or "🏌️ Time to putt!")
        except discord.HTTPException:
            pass

    async def _maybe_weekly_announce(self, guild, channel, conf, now):
        """Announce last week's winner once, after the week rolls over."""
        last_week_key = _week_key(now - timedelta(weeks=1))
        if conf.get("last_weekly_week") == last_week_key:
            return

        week_data = (await self.config.guild(guild).weeks()).get(last_week_key, {})
        # Mark as handled even when empty so we don't recompute all week.
        await self.config.guild(guild).last_weekly_week.set(last_week_key)
        if not week_data:
            return

        totals = {
            uid: {
                "rounds": entry["rounds"],
                "total_rel": sum(s["relative"] for s in entry["scores"].values()),
            }
            for uid, entry in week_data.items()
        }
        lines = self._leaderboard_lines(
            self._rank_rows(guild, totals)
        )
        if not lines:
            return
        embed = discord.Embed(
            title=f"🏆 putt.day Weekly Results — {last_week_key}",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        match = SCORE_PATTERN.search(message.content)
        if not match:
            return

        day_num, strokes, par, relative = (int(g) for g in match.groups())

        now = datetime.now(timezone.utc)
        iso_week = _week_key(now)
        uid = str(message.author.id)
        day_key = str(day_num)

        async with self.config.guild(message.guild).weeks() as weeks:
            # One score per putt.day day per user — check every week, not just
            # the current one, so an old day can't be re-submitted later.
            duplicate = any(
                day_key in wk.get(uid, {}).get("scores", {})
                for wk in weeks.values()
            )
            if not duplicate:
                week = weeks.setdefault(iso_week, {})
                entry = week.setdefault(
                    uid,
                    {"scores": {}, "total_strokes": 0, "total_par": 0, "rounds": 0},
                )
                entry["scores"][day_key] = {
                    "strokes": strokes,
                    "par": par,
                    "relative": relative,
                    "timestamp": now.isoformat(),
                }
                entry["total_strokes"] += strokes
                entry["total_par"] += par
                entry["rounds"] += 1

        # React to confirm — ⛳ for a new score, 🔁 if it was already logged.
        try:
            await message.add_reaction("🔁" if duplicate else "⛳")
        except discord.HTTPException:
            pass

        # Reply to a newly recorded score with that day's updated leaderboard.
        if not duplicate and await self.config.guild(message.guild).auto_board():
            lines = self._day_lines(message.guild, weeks, day_key)
            await self._reply_board(
                message, f"⛳ Day #{day_num} Leaderboard", lines
            )

    async def _reply_board(self, message: discord.Message, title: str, lines: list):
        """Reply to ``message`` with a leaderboard embed (text fallback)."""
        if not lines:
            return
        body = "\n".join(lines)
        perms = message.channel.permissions_for(message.guild.me)
        try:
            if perms.embed_links:
                embed = discord.Embed(
                    title=title, description=body, color=discord.Color.gold()
                )
                await message.reply(embed=embed, mention_author=False)
            else:
                await message.reply(f"**{title}**\n{body}", mention_author=False)
        except discord.HTTPException:
            pass

    # ── Helpers ───────────────────────────────────────────────────────

    def _rank_rows(self, guild, totals: dict) -> list:
        """Resolve member names and sort ``{uid: {rounds, total_rel}}``.

        Sorted by average relative to par (lowest = best), with total then
        round count as tie-breakers. Returns ``(name, rounds, total_rel, avg)``.
        """
        rows = []
        for uid, data in totals.items():
            rounds = data["rounds"]
            if not rounds:
                continue
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            avg_rel = data["total_rel"] / rounds
            rows.append((name, rounds, data["total_rel"], avg_rel))

        rows.sort(key=lambda r: (r[3], r[2], -r[1]))
        return rows

    @staticmethod
    def _leaderboard_lines(rows: list) -> list:
        """Format ranked rows into display lines with medals."""
        lines = []
        for i, (name, rounds, total_rel, avg_rel) in enumerate(rows):
            prefix = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            lines.append(
                f"{prefix} **{name}** · {rounds} round{'s' if rounds != 1 else ''} "
                f"· total {_fmt_rel(total_rel)} · avg {avg_rel:+.1f}"
            )
        return lines

    def _build_leaderboard(self, ctx, totals: dict) -> list:
        """Convenience: rank + format a leaderboard for a command context."""
        return self._leaderboard_lines(self._rank_rows(ctx.guild, totals))

    def _day_lines(self, guild, weeks: dict, day_key: str) -> list:
        """Build the single-day leaderboard lines for ``day_key``.

        Sorted by relative to par (lowest = best), then strokes.
        """
        rows = []  # (name, strokes, par, relative)
        for week_data in weeks.values():
            for uid, entry in week_data.items():
                score = entry["scores"].get(day_key)
                if score is None:
                    continue
                member = guild.get_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                rows.append(
                    (name, score["strokes"], score["par"], score["relative"])
                )

        rows.sort(key=lambda r: (r[3], r[1]))
        lines = []
        for i, (name, strokes, par, relative) in enumerate(rows):
            prefix = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            lines.append(
                f"{prefix} **{name}** · {strokes}/{par} · {_fmt_rel(relative)}"
            )
        return lines

    # ── Commands ──────────────────────────────────────────────────────

    @commands.guild_only()
    @commands.group(name="putt", invoke_without_command=True)
    async def putt(self, ctx: commands.Context):
        """Putt.day score tracker. Use subcommands for details."""
        await ctx.send_help(ctx.command)

    @putt.command(name="weekly", aliases=["week", "w"])
    async def putt_weekly(self, ctx: commands.Context, week_offset: int = 0):
        """Show the weekly leaderboard. Defaults to current week.

        Use a negative offset for past weeks (e.g. `putt weekly -1`).
        """
        target = datetime.now(timezone.utc) + timedelta(weeks=week_offset)
        iso_week = _week_key(target)

        week_data = (await self.config.guild(ctx.guild).weeks()).get(iso_week, {})
        if not week_data:
            await ctx.send(f"No scores recorded for week **{iso_week}**.")
            return

        totals = {
            uid: {
                "rounds": entry["rounds"],
                "total_rel": sum(s["relative"] for s in entry["scores"].values()),
            }
            for uid, entry in week_data.items()
        }
        lines = self._build_leaderboard(ctx, totals)
        await self._send_embed(ctx, f"⛳ Weekly Leaderboard — {iso_week}", lines)

    @putt.command(name="daily", aliases=["today", "d"])
    async def putt_daily(self, ctx: commands.Context, when: str = "today"):
        """Show today's leaderboard. Pass `yesterday` for the previous day.

        Examples: `putt daily`, `putt daily yesterday`
        """
        when = when.lower()
        if when in ("today", "t"):
            offset, label = 0, "Today"
        elif when in ("yesterday", "y"):
            offset, label = 1, "Yesterday"
        else:
            await ctx.send("Use `putt daily` or `putt daily yesterday`.")
            return

        # The day is taken from the putt.day number in the post (#36), not from
        # when the message was sent. "Today" is the latest day number recorded.
        weeks = await self.config.guild(ctx.guild).weeks()
        all_days = {
            int(day_key)
            for week_data in weeks.values()
            for entry in week_data.values()
            for day_key in entry["scores"]
        }
        if not all_days:
            await ctx.send("No scores recorded yet.")
            return

        target_day = max(all_days) - offset
        lines = self._day_lines(ctx.guild, weeks, str(target_day))
        if not lines:
            await ctx.send(
                f"No scores recorded for **{label.lower()}** (Day #{target_day})."
            )
            return
        await self._send_embed(
            ctx, f"⛳ {label}'s Leaderboard — Day #{target_day}", lines
        )

    @putt.command(name="overall", aliases=["alltime", "o"])
    async def putt_overall(self, ctx: commands.Context):
        """Show the all-time overall leaderboard."""
        weeks = await self.config.guild(ctx.guild).weeks()
        if not weeks:
            await ctx.send("No scores recorded yet.")
            return

        totals = defaultdict(lambda: {"rounds": 0, "total_rel": 0})
        for week_data in weeks.values():
            for uid, entry in week_data.items():
                totals[uid]["rounds"] += entry["rounds"]
                totals[uid]["total_rel"] += sum(
                    s["relative"] for s in entry["scores"].values()
                )

        lines = self._build_leaderboard(ctx, totals)
        await self._send_embed(ctx, "⛳ All-Time Leaderboard", lines)

    @putt.command(name="myscore", aliases=["me", "m"])
    async def putt_myscore(self, ctx: commands.Context):
        """Show your own scores across all weeks."""
        uid = str(ctx.author.id)
        weeks = await self.config.guild(ctx.guild).weeks()

        all_scores = []
        total_rel = 0
        total_rounds = 0
        for entry in (w[uid] for w in weeks.values() if uid in w):
            total_rounds += entry["rounds"]
            for day_key, score in sorted(entry["scores"].items(), key=lambda kv: int(kv[0])):
                total_rel += score["relative"]
                all_scores.append(
                    f"**Day #{day_key}** · {score['strokes']}/{score['par']} "
                    f"· {_fmt_rel(score['relative'])}"
                )

        if not all_scores:
            await ctx.send("No scores recorded for you yet.")
            return

        avg_rel = total_rel / total_rounds if total_rounds else 0
        summary = (
            f"Total: {total_rounds} rounds · {_fmt_rel(total_rel)} overall "
            f"· {avg_rel:+.1f} avg"
        )
        await self._send_embed(
            ctx, f"⛳ {ctx.author.display_name}'s Scores", all_scores, footer=summary
        )

    @putt.command(name="reset")
    @commands.admin_or_permissions(manage_guild=True)
    async def putt_reset(self, ctx: commands.Context):
        """Delete ALL putt.day scores for this server.

        Requires the admin role or the Manage Server permission.
        """
        if not await self.config.guild(ctx.guild).weeks():
            await ctx.send("There are no putt.day scores to reset.")
            return

        view = ConfirmView(ctx.author, timeout=30, disable_buttons=True)
        view.message = await ctx.send(
            "⚠️ This will **permanently delete all** putt.day scores for this "
            "server. This cannot be undone.",
            view=view,
        )
        await view.wait()
        if not view.result:
            await ctx.send("Reset cancelled.")
            return

        await self.config.guild(ctx.guild).weeks.clear()
        await ctx.send("✅ All putt.day scores for this server have been reset.")

    # ── Admin: manual score corrections ───────────────────────────────

    @putt.command(name="addscore", aliases=["setscore"])
    @commands.admin_or_permissions(manage_guild=True)
    async def putt_addscore(
        self,
        ctx: commands.Context,
        member: discord.Member,
        day: int,
        strokes: int,
        par: int,
    ):
        """Add or correct a member's score for a day (relative is computed).

        Example: `putt addscore @Craig 36 20 6`
        """
        if day < 1 or strokes < 0 or par < 0:
            await ctx.send("Day must be ≥ 1 and strokes/par must be ≥ 0.")
            return

        relative = strokes - par
        uid = str(member.id)
        day_key = str(day)

        async with self.config.guild(ctx.guild).weeks() as weeks:
            existing = None
            for wk in weeks.values():
                ent = wk.get(uid)
                if ent and day_key in ent["scores"]:
                    existing = ent
                    break

            if existing is not None:
                old = existing["scores"][day_key]
                existing["total_strokes"] += strokes - old["strokes"]
                existing["total_par"] += par - old["par"]
                old.update(strokes=strokes, par=par, relative=relative)
                action = "Updated"
            else:
                week = weeks.setdefault(_week_key(datetime.now(timezone.utc)), {})
                entry = week.setdefault(
                    uid,
                    {"scores": {}, "total_strokes": 0, "total_par": 0, "rounds": 0},
                )
                entry["scores"][day_key] = {
                    "strokes": strokes,
                    "par": par,
                    "relative": relative,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                entry["total_strokes"] += strokes
                entry["total_par"] += par
                entry["rounds"] += 1
                action = "Added"

        await ctx.send(
            f"✅ {action} **{member.display_name}** — Day #{day}: "
            f"{strokes}/{par} ({_fmt_rel(relative)})."
        )

    @putt.command(name="removescore", aliases=["delscore", "rmscore"])
    @commands.admin_or_permissions(manage_guild=True)
    async def putt_removescore(
        self, ctx: commands.Context, member: discord.Member, day: int
    ):
        """Remove a member's score for a specific day.

        Example: `putt removescore @Craig 36`
        """
        uid = str(member.id)
        day_key = str(day)

        async with self.config.guild(ctx.guild).weeks() as weeks:
            removed = False
            for wk_key in list(weeks.keys()):
                ent = weeks[wk_key].get(uid)
                if ent and day_key in ent["scores"]:
                    old = ent["scores"].pop(day_key)
                    ent["total_strokes"] -= old["strokes"]
                    ent["total_par"] -= old["par"]
                    ent["rounds"] -= 1
                    if not ent["scores"]:
                        del weeks[wk_key][uid]
                    if not weeks[wk_key]:
                        del weeks[wk_key]
                    removed = True
                    break

        if removed:
            await ctx.send(
                f"✅ Removed **{member.display_name}**'s Day #{day} score."
            )
        else:
            await ctx.send(
                f"No Day #{day} score found for **{member.display_name}**."
            )

    # ── Admin: reminder / announcement settings ───────────────────────

    @putt.group(name="set", invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def putt_set(self, ctx: commands.Context):
        """Configure daily reminders and weekly announcements."""
        await ctx.send_help(ctx.command)

    @putt_set.command(name="channel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_channel(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ):
        """Set the channel for reminders/announcements. Omit to clear."""
        await self.config.guild(ctx.guild).announce_channel.set(
            channel.id if channel else None
        )
        if channel:
            await ctx.send(f"Announcements will be posted in {channel.mention}.")
        else:
            await ctx.send("Announcement channel cleared.")

    @putt_set.command(name="reminder")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_reminder(self, ctx: commands.Context, on_off: bool):
        """Turn the daily reminder on or off."""
        await self.config.guild(ctx.guild).daily_reminder.set(on_off)
        msg = f"Daily reminder {'enabled' if on_off else 'disabled'}."
        if on_off and not await self.config.guild(ctx.guild).announce_channel():
            msg += " Set a channel with `[p]putt set channel #channel`."
        await ctx.send(msg)

    @putt_set.command(name="time")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_time(self, ctx: commands.Context, time: str):
        """Set the daily reminder time as HH:MM in 24-hour UTC (e.g. `13:30`)."""
        try:
            hour, minute = (int(p) for p in time.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            await ctx.send("Please give a time as `HH:MM` in 24-hour UTC, e.g. `13:30`.")
            return
        await self.config.guild(ctx.guild).reminder_time.set(f"{hour:02d}:{minute:02d}")
        await ctx.send(f"Daily reminder time set to {hour:02d}:{minute:02d} UTC.")

    @putt_set.command(name="message")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_message(self, ctx: commands.Context, *, text: str):
        """Set the daily reminder message."""
        await self.config.guild(ctx.guild).reminder_message.set(text)
        await ctx.send("Reminder message updated.")

    @putt_set.command(name="autoboard")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_autoboard(self, ctx: commands.Context, on_off: bool):
        """Toggle replying with the day's leaderboard on each new score."""
        await self.config.guild(ctx.guild).auto_board.set(on_off)
        await ctx.send(
            f"Auto leaderboard reply {'enabled' if on_off else 'disabled'}."
        )

    @putt_set.command(name="weekly")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_weekly(self, ctx: commands.Context, on_off: bool):
        """Turn the weekly winner announcement on or off."""
        await self.config.guild(ctx.guild).weekly_announce.set(on_off)
        msg = f"Weekly winner announcement {'enabled' if on_off else 'disabled'}."
        if on_off and not await self.config.guild(ctx.guild).announce_channel():
            msg += " Set a channel with `[p]putt set channel #channel`."
        await ctx.send(msg)

    @putt_set.command(name="show", aliases=["settings"])
    @commands.admin_or_permissions(manage_guild=True)
    async def set_show(self, ctx: commands.Context):
        """Show the current reminder/announcement settings."""
        conf = await self.config.guild(ctx.guild).all()
        channel = (
            ctx.guild.get_channel(conf["announce_channel"])
            if conf["announce_channel"]
            else None
        )
        lines = [
            f"**Auto leaderboard reply:** {'on' if conf['auto_board'] else 'off'}",
            f"**Channel:** {channel.mention if channel else 'not set'}",
            f"**Daily reminder:** {'on' if conf['daily_reminder'] else 'off'}",
            f"**Reminder time:** {conf['reminder_time']} UTC",
            f"**Reminder message:** {conf['reminder_message']}",
            f"**Weekly announce:** {'on' if conf['weekly_announce'] else 'off'}",
        ]
        await self._send_embed(ctx, "⛳ PuttTracker Settings", lines)

    # ── Output ────────────────────────────────────────────────────────

    async def _send_embed(self, ctx, title: str, lines: list, footer: str = ""):
        """Render a leaderboard as an embed, falling back to plain text.

        Respects the bot/channel embed setting via ``ctx.embed_requested()``
        and paginates long results so they stay within Discord limits.
        """
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
                    title=heading,
                    description=page,
                    color=await ctx.embed_color(),
                )
                if footer and is_last:
                    embed.set_footer(text=footer)
                await ctx.send(embed=embed)
            else:
                text = f"**{heading}**\n{page}"
                if footer and is_last:
                    text += f"\n{footer}"
                await ctx.send(text)
