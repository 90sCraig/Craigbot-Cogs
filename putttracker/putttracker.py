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

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

import discord
from discord.ext import tasks
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.views import ConfirmView

# Matches the putt.day share line, e.g. "putt.day #36 ⛳ 20/6 +14" or
# "putt.day #37 ⛳ 10/9 Bogey". Only the day number and strokes/par are
# captured; relative-to-par is derived (strokes - par), because putt.day shows
# a golf term (Par/Bogey/Birdie…) instead of a number for small scores. The
# bit between the day number and strokes/par (a flag emoji + spaces) is skipped
# so a different glyph can't break detection.
SCORE_PATTERN = re.compile(
    r"putt\.day\s+#(\d+)[^\d\n]*?(\d+)\s*/\s*(\d+)",
    re.IGNORECASE,
)
# putt.day appends "· N restart(s)" when a hole was restarted. We prize
# no-restart rounds, so restarted scores are flagged with an asterisk.
RESTART_PATTERN = re.compile(r"(\d+)\s*restarts?\b", re.IGNORECASE)
RESTART_MARK = "\\*"  # renders as a literal * in Discord markdown
RESTART_NOTE = "\\* = used a restart"

MEDALS = ("🥇", "🥈", "🥉")
PUTT_URL = "https://putt.day"


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


def _parse_hhmm(value: str):
    """Parse ``HH:MM`` (24-hour) into ``(hour, minute)`` or ``None`` if invalid."""
    try:
        hour, minute = (int(p) for p in value.split(":"))
    except (ValueError, AttributeError):
        return None
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour, minute
    return None


# Friendly aliases for the timezones people actually ask for.
_TZ_SHORTCUTS = {
    "utc": "UTC",
    "eastern": "America/New_York", "et": "America/New_York",
    "est": "America/New_York", "edt": "America/New_York",
    "central": "America/Chicago", "ct": "America/Chicago",
    "cst": "America/Chicago", "cdt": "America/Chicago",
    "mountain": "America/Denver", "mt": "America/Denver",
    "mst": "America/Denver", "mdt": "America/Denver",
    "pacific": "America/Los_Angeles", "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
}


def _resolve_tz(name: str):
    """Return a tzinfo for ``name``, or ``None`` if it can't be resolved.

    Accepts IANA names (``America/New_York``) and the shortcuts above. The
    IANA database comes from the stdlib's ``zoneinfo`` plus the ``tzdata``
    package (a cog requirement), so it works even on Windows hosts that lack a
    system timezone database.
    """
    if not name:
        return None
    canonical = _TZ_SHORTCUTS.get(name.strip().lower(), name.strip())
    if canonical.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(canonical)
    except Exception:
        return None


def _canonical_tz_name(name: str):
    """Map a user-supplied tz to its canonical IANA name, or ``None``."""
    if not name:
        return None
    canonical = _TZ_SHORTCUTS.get(name.strip().lower(), name.strip())
    return "UTC" if canonical.upper() == "UTC" else canonical


def _safe_tz(name: str):
    """Like :func:`_resolve_tz` but always returns a tz (UTC as a fallback)."""
    return _resolve_tz(name) or timezone.utc


NAME_CAP = 18  # cap on leaderboard usernames so the table stays mobile-friendly


def _truncate(text: str, width: int) -> str:
    """Cap ``text`` to ``width`` chars, adding an ellipsis when shortened."""
    return text if len(text) <= width else text[: width - 1] + "…"


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
            timezone="UTC",               # IANA tz; week buckets follow this
            auto_board=True,              # reply with the day board on a new score
            announce_channel=None,        # channel id for reminders/announcements
            daily_reminder=False,         # post a "play today" reminder
            reminder_time="12:00",        # HH:MM in UTC
            reminder_message="🏌️ A new putt.day is live — post your score!",
            weekly_announce=False,        # announce last week's winner
            weekly_time="09:00",          # HH:MM in UTC, on/after week rollover
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

    async def _rebucket_weeks(self, guild, tz):
        """Re-file every stored score into the week bucket for timezone ``tz``.

        Each score keeps its own ``timestamp`` (UTC), so we can recompute which
        ISO week it belongs to under the new timezone and rebuild the ``weeks``
        map from scratch. Per-user totals are recomputed from the scores, so
        this also self-heals any drifted totals. Scores missing a timestamp
        stay in their existing bucket. Returns the number of weeks afterwards.
        """
        async with self.config.guild(guild).weeks() as weeks:
            rebuilt = {}
            for old_week, members in weeks.items():
                for uid, entry in members.items():
                    for day_key, score in entry.get("scores", {}).items():
                        ts = score.get("timestamp")
                        target_week = old_week
                        if ts:
                            try:
                                dt = datetime.fromisoformat(ts)
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                target_week = _week_key(dt.astimezone(tz))
                            except ValueError:
                                pass
                        bucket = rebuilt.setdefault(target_week, {})
                        member = bucket.setdefault(
                            uid,
                            {"scores": {}, "total_strokes": 0, "total_par": 0, "rounds": 0},
                        )
                        if day_key in member["scores"]:
                            continue  # a member logs each day once; guard anyway
                        member["scores"][day_key] = score
                        member["total_strokes"] += score["strokes"]
                        member["total_par"] += score["par"]
                        member["rounds"] += 1
            weeks.clear()
            weeks.update(rebuilt)
            return len(rebuilt)

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
        hhmm = _parse_hhmm(conf.get("reminder_time", ""))
        if hhmm is None or (now.hour, now.minute) < hhmm:
            return
        await self.config.guild(guild).last_reminder_date.set(today)
        text = conf.get("reminder_message") or "🏌️ Time to putt!"
        try:
            await channel.send(f"{text}\n{PUTT_URL}")
        except discord.HTTPException:
            pass

    async def _maybe_weekly_announce(self, guild, channel, conf, now):
        """Announce last week's winner once, after the week rolls over."""
        local_now = now.astimezone(_safe_tz(conf.get("timezone", "UTC")))
        last_week_key = _week_key(local_now - timedelta(weeks=1))
        if conf.get("last_weekly_week") == last_week_key:
            return

        # Hold until the configured time of day has passed (so it doesn't fire
        # at 00:00 UTC on the week rollover).
        hhmm = _parse_hhmm(conf.get("weekly_time", ""))
        if hhmm is None or (now.hour, now.minute) < hhmm:
            return

        week_data = (await self.config.guild(guild).weeks()).get(last_week_key, {})
        # Mark as handled even when empty so we don't recompute all week.
        await self.config.guild(guild).last_weekly_week.set(last_week_key)
        if not week_data:
            return

        totals = self._totals_from_scores(week_data)
        rows = self._rank_rows(guild, totals)
        if not rows:
            return
        podium, table, any_restart = self._rank_board_parts(rows)
        embed = discord.Embed(
            title=f"🏆 putt.day Weekly Results — {last_week_key}",
            description=self._board_description(podium, table, any_restart),
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

        day_num = int(match.group(1))
        strokes = int(match.group(2))
        par = int(match.group(3))
        relative = strokes - par  # always exact; matches putt.day's term/number
        rmatch = RESTART_PATTERN.search(message.content)
        restarts = int(rmatch.group(1)) if rmatch else 0

        now = datetime.now(timezone.utc)
        tz = _safe_tz(await self.config.guild(message.guild).timezone())
        iso_week = _week_key(now.astimezone(tz))
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
                    "restarts": restarts,
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
            day_rows = self._day_rows(message.guild, weeks, day_key)
            podium, table, any_restart = self._day_board_parts(day_rows)
            await self._reply_board(
                message, f"⛳ Day #{day_num} Leaderboard", podium, table, any_restart
            )

    async def _reply_board(self, message, title, podium_lines, table_lines, any_restart):
        """Reply to ``message`` with a board (podium + table), text fallback."""
        if not table_lines or len(table_lines) <= 1:
            return
        desc = self._board_description(podium_lines, table_lines, any_restart)
        perms = message.channel.permissions_for(message.guild.me)
        try:
            if perms.embed_links:
                embed = discord.Embed(
                    title=title, description=desc, color=discord.Color.gold()
                )
                await message.reply(embed=embed, mention_author=False)
            else:
                await message.reply(f"**{title}**\n{desc}", mention_author=False)
        except discord.HTTPException:
            pass

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _totals_from_scores(week_data: dict) -> dict:
        """Aggregate one week's data into ``{uid: {rounds, total_rel, restarts}}``."""
        totals = {}
        for uid, entry in week_data.items():
            scores = entry["scores"].values()
            totals[uid] = {
                "rounds": entry["rounds"],
                "total_rel": sum(s["relative"] for s in scores),
                "restarts": sum(s.get("restarts", 0) for s in scores),
            }
        return totals

    def _rank_rows(self, guild, totals: dict) -> list:
        """Resolve member names and sort ``{uid: {rounds, total_rel, restarts}}``.

        Sorted by average relative to par (lowest = best), with total then
        round count as tie-breakers. Returns the raw (unescaped) member name as
        ``(name, rounds, total_rel, avg, had_restart)``.
        """
        rows = []
        for uid, data in totals.items():
            rounds = data["rounds"]
            if not rounds:
                continue
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            avg_rel = data["total_rel"] / rounds
            rows.append(
                (name, rounds, data["total_rel"], avg_rel, data.get("restarts", 0) > 0)
            )

        rows.sort(key=lambda r: (r[3], r[2], -r[1]))
        return rows

    def _day_rows(self, guild, weeks: dict, day_key: str) -> list:
        """Rows for a single day: ``(name, strokes, par, relative, restarts)``.

        Sorted by relative to par (lowest = best), then strokes.
        """
        rows = []
        for week_data in weeks.values():
            for uid, entry in week_data.items():
                score = entry["scores"].get(day_key)
                if score is None:
                    continue
                member = guild.get_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                rows.append(
                    (name, score["strokes"], score["par"],
                     score["relative"], score.get("restarts", 0))
                )
        rows.sort(key=lambda r: (r[3], r[1]))
        return rows

    # Board rendering: a 🥇🥈🥉 podium (in normal embed text, so names can be
    # bold + markdown-escaped) above a monospace table (in a code block, so the
    # columns align; names there are raw but backtick-sanitised).

    @staticmethod
    def _table_name(name: str, had_restart) -> str:
        # Backticks would break the code fence; swap them out. Names are shown
        # in full up to NAME_CAP, then ellipsised so the table stays narrow.
        return _truncate(name.replace("`", "'"), NAME_CAP) + ("*" if had_restart else "")

    @staticmethod
    def _visual_len(text: str) -> int:
        """Approximate display width; emoji occupy ~two monospace cells."""
        return sum(2 if ord(c) >= 0x1F000 else 1 for c in text)

    @classmethod
    def _center(cls, line: str, width: int) -> str:
        """Pad ``line`` with leading spaces to centre it within ``width``."""
        pad = max(0, (width - cls._visual_len(line)) // 2)
        return " " * pad + line

    @staticmethod
    def _podium_plain(rows: list) -> list:
        """Top-three medal lines as plain text (for the code block)."""
        if not rows:
            return []

        def tag(i):
            name = _truncate(rows[i][0].replace("`", "'"), NAME_CAP)
            return f"{MEDALS[i]} {name}{'*' if rows[i][4] else ''}"

        out = [tag(0)]
        if len(rows) >= 3:
            out.append(f"{tag(1)}    {tag(2)}")
        elif len(rows) == 2:
            out.append(tag(1))
        return out

    def _rank_board_parts(self, rows: list):
        """Returns ``(podium_lines, table_lines, any_restart)`` for a rank board."""
        names = [self._table_name(r[0], r[4]) for r in rows]
        name_w = max([len("Player"), *(len(n) for n in names)])
        width = 3 + name_w + 21  # Rounds/Total/Avg columns are 7 wide each
        header = f"{'#':<3}{'Player':<{name_w}}{'Rounds':>7}{'Total':>7}{'Avg':>7}"
        table = [header]
        any_restart = False
        for i, (name, rounds, total_rel, avg, had_restart) in enumerate(rows, 1):
            any_restart = any_restart or had_restart
            table.append(
                f"{i:<3}{names[i-1]:<{name_w}}{rounds:>7}"
                f"{_fmt_rel(total_rel):>7}{avg:>+7.1f}"
            )
        podium = [self._center(line, width) for line in self._podium_plain(rows)]
        return podium, table, any_restart

    def _day_board_parts(self, day_rows: list):
        """Returns ``(podium_lines, table_lines, any_restart)`` for a daily board."""
        names = [self._table_name(r[0], r[4]) for r in day_rows]
        name_w = max([len("Player"), *(len(n) for n in names)])
        width = 3 + name_w + 13  # Score column is 7 wide, +/- is 6
        header = f"{'#':<3}{'Player':<{name_w}}{'Score':>7}{'+/-':>6}"
        table = [header]
        any_restart = False
        for i, (name, strokes, par, relative, restarts) in enumerate(day_rows, 1):
            any_restart = any_restart or bool(restarts)
            table.append(
                f"{i:<3}{names[i-1]:<{name_w}}{f'{strokes}/{par}':>7}"
                f"{_fmt_rel(relative):>6}"
            )
        podium = [self._center(line, width) for line in self._podium_plain(day_rows)]
        return podium, table, any_restart

    @staticmethod
    def _board_description(podium_lines, table_lines, any_restart) -> str:
        inner = []
        if podium_lines:
            inner.extend(podium_lines)
            inner.append("")  # blank line between podium and table
        inner.extend(table_lines)
        desc = "```\n" + "\n".join(inner) + "\n```"
        if any_restart:
            desc += "\n" + RESTART_NOTE
        return desc

    async def _send_board(self, ctx, title, podium_lines, table_lines, any_restart):
        """Send a podium + monospace-table board, paginating the table by rows.

        Each page is a complete code block (the fence never splits), the podium
        rides the first page, and the restart legend the last. Falls back to
        plain text when embeds aren't available.
        """
        use_embed = await ctx.embed_requested()
        header, data = table_lines[0], table_lines[1:]
        budget = 1800  # keep each code block comfortably under Discord limits
        chunks, cur, cur_len = [], [], len(header)
        for line in data:
            if cur and cur_len + len(line) + 1 > budget:
                chunks.append(cur)
                cur, cur_len = [], len(header)
            cur.append(line)
            cur_len += len(line) + 1
        chunks.append(cur)
        total = len(chunks)

        for idx, chunk in enumerate(chunks):
            inner = []
            if idx == 0 and podium_lines:
                inner.extend(podium_lines)
                inner.append("")  # blank line between podium and table
            inner.append(header)
            inner.extend(chunk)
            desc = "```\n" + "\n".join(inner) + "\n```"
            if idx == total - 1 and any_restart:
                desc += "\n" + RESTART_NOTE
            heading = title if total == 1 else f"{title} ({idx + 1}/{total})"
            if use_embed:
                await ctx.send(embed=discord.Embed(
                    title=heading, description=desc, color=await ctx.embed_color()
                ))
            else:
                await ctx.send(f"**{heading}**\n{desc}")

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
        tz = _safe_tz(await self.config.guild(ctx.guild).timezone())
        target = datetime.now(tz) + timedelta(weeks=week_offset)
        iso_week = _week_key(target)

        week_data = (await self.config.guild(ctx.guild).weeks()).get(iso_week, {})
        if not week_data:
            await ctx.send(f"No scores recorded for week **{iso_week}**.")
            return

        totals = self._totals_from_scores(week_data)
        podium, table, any_restart = self._rank_board_parts(self._rank_rows(ctx.guild, totals))
        await self._send_board(
            ctx, f"⛳ Weekly Leaderboard — {iso_week}", podium, table, any_restart
        )

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
        day_rows = self._day_rows(ctx.guild, weeks, str(target_day))
        if not day_rows:
            await ctx.send(
                f"No scores recorded for **{label.lower()}** (Day #{target_day})."
            )
            return
        podium, table, any_restart = self._day_board_parts(day_rows)
        await self._send_board(
            ctx, f"⛳ {label}'s Leaderboard — Day #{target_day}", podium, table, any_restart
        )

    @putt.command(name="overall", aliases=["alltime", "o"])
    async def putt_overall(self, ctx: commands.Context):
        """Show the all-time overall leaderboard."""
        weeks = await self.config.guild(ctx.guild).weeks()
        if not weeks:
            await ctx.send("No scores recorded yet.")
            return

        totals = defaultdict(lambda: {"rounds": 0, "total_rel": 0, "restarts": 0})
        for week_data in weeks.values():
            for uid, entry in week_data.items():
                scores = entry["scores"].values()
                totals[uid]["rounds"] += entry["rounds"]
                totals[uid]["total_rel"] += sum(s["relative"] for s in scores)
                totals[uid]["restarts"] += sum(s.get("restarts", 0) for s in scores)

        podium, table, any_restart = self._rank_board_parts(self._rank_rows(ctx.guild, totals))
        await self._send_board(ctx, "⛳ All-Time Leaderboard", podium, table, any_restart)

    @putt.command(name="myscore", aliases=["me", "m"])
    async def putt_myscore(self, ctx: commands.Context):
        """Show your own scores across all weeks."""
        uid = str(ctx.author.id)
        weeks = await self.config.guild(ctx.guild).weeks()

        all_scores = []
        total_rel = 0
        total_rounds = 0
        any_restart = False
        for entry in (w[uid] for w in weeks.values() if uid in w):
            total_rounds += entry["rounds"]
            for day_key, score in sorted(entry["scores"].items(), key=lambda kv: int(kv[0])):
                total_rel += score["relative"]
                restarts = score.get("restarts", 0)
                mark = RESTART_MARK if restarts else ""
                any_restart = any_restart or bool(restarts)
                all_scores.append(
                    f"**Day #{day_key}** · {score['strokes']}/{score['par']} "
                    f"· {_fmt_rel(score['relative'])}{mark}"
                )

        if not all_scores:
            await ctx.send("No scores recorded for you yet.")
            return
        if any_restart:
            all_scores.append(RESTART_NOTE)

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
        restarts: int = 0,
    ):
        """Add or correct a member's score for a day (relative is computed).

        Optionally pass the number of restarts (defaults to 0).
        Example: `putt addscore @Craig 36 20 6` or `putt addscore @Craig 37 24 9 1`
        """
        if day < 1 or strokes < 0 or par < 0 or restarts < 0:
            await ctx.send("Day must be ≥ 1 and strokes/par/restarts must be ≥ 0.")
            return

        relative = strokes - par
        uid = str(member.id)
        day_key = str(day)
        iso_week = _week_key(
            datetime.now(_safe_tz(await self.config.guild(ctx.guild).timezone()))
        )

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
                old.update(strokes=strokes, par=par, relative=relative, restarts=restarts)
                action = "Updated"
            else:
                week = weeks.setdefault(iso_week, {})
                entry = week.setdefault(
                    uid,
                    {"scores": {}, "total_strokes": 0, "total_par": 0, "rounds": 0},
                )
                entry["scores"][day_key] = {
                    "strokes": strokes,
                    "par": par,
                    "relative": relative,
                    "restarts": restarts,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                entry["total_strokes"] += strokes
                entry["total_par"] += par
                entry["rounds"] += 1
                action = "Added"

        mark = RESTART_MARK if restarts else ""
        await ctx.send(
            f"✅ {action} **{member.display_name}** — Day #{day}: "
            f"{strokes}/{par} ({_fmt_rel(relative)}){mark}."
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
        hhmm = _parse_hhmm(time)
        if hhmm is None:
            await ctx.send("Please give a time as `HH:MM` in 24-hour UTC, e.g. `13:30`.")
            return
        hour, minute = hhmm
        await self.config.guild(ctx.guild).reminder_time.set(f"{hour:02d}:{minute:02d}")
        await ctx.send(f"Daily reminder time set to {hour:02d}:{minute:02d} UTC.")

    @putt_set.command(name="weeklytime")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_weeklytime(self, ctx: commands.Context, time: str):
        """Set the weekly announcement time as HH:MM in 24-hour UTC (e.g. `09:00`).

        The announcement still posts on the first day of a new week (Monday),
        but at or after this time instead of at midnight UTC.
        """
        hhmm = _parse_hhmm(time)
        if hhmm is None:
            await ctx.send("Please give a time as `HH:MM` in 24-hour UTC, e.g. `09:00`.")
            return
        hour, minute = hhmm
        await self.config.guild(ctx.guild).weekly_time.set(f"{hour:02d}:{minute:02d}")
        await ctx.send(f"Weekly announcement time set to {hour:02d}:{minute:02d} UTC.")

    @putt_set.command(name="timezone", aliases=["tz"])
    @commands.admin_or_permissions(manage_guild=True)
    async def set_timezone(self, ctx: commands.Context, *, name: str):
        """Set the timezone the leaderboard week follows (default UTC).

        Accepts IANA names like `America/New_York` or shortcuts like
        `eastern`, `central`, `mountain`, `pacific`. Existing scores are
        automatically re-filed into the right weeks for the new timezone.
        """
        canonical = _canonical_tz_name(name)
        if canonical is None or _resolve_tz(name) is None:
            await ctx.send(
                f"I don't recognise the timezone `{name}`. Try an IANA name like "
                f"`America/New_York`, or `eastern` / `central` / `mountain` / `pacific`. "
                f"(If IANA names fail, the bot host may need `pip install tzdata`.)"
            )
            return
        await self.config.guild(ctx.guild).timezone.set(canonical)
        async with ctx.typing():
            week_count = await self._rebucket_weeks(ctx.guild, _safe_tz(canonical))
        await ctx.send(
            f"🕔 Leaderboard timezone set to **{canonical}**. "
            f"Re-filed existing scores across {week_count} week(s). "
            f"`{ctx.clean_prefix}putt weekly` now reflects your local week."
        )

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
            f"**Timezone:** {conf['timezone']}",
            f"**Auto leaderboard reply:** {'on' if conf['auto_board'] else 'off'}",
            f"**Channel:** {channel.mention if channel else 'not set'}",
            f"**Daily reminder:** {'on' if conf['daily_reminder'] else 'off'}",
            f"**Reminder time:** {conf['reminder_time']} UTC",
            f"**Reminder message:** {conf['reminder_message']}",
            f"**Weekly announce:** {'on' if conf['weekly_announce'] else 'off'}",
            f"**Weekly time:** {conf['weekly_time']} UTC",
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
