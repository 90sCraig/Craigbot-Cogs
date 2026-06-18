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
from redbot.core import commands, Config
from redbot.core.utils.chat_formatting import pagify

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
        self.config.register_guild(weeks={})
        # weeks = {
        #   "2026-W25": {
        #     "user_id_str": {
        #       "scores": {"36": {"strokes": 20, "par": 6, "relative": 14, "timestamp": "..."}},
        #       "total_strokes": 20, "total_par": 6, "rounds": 1
        #     }
        #   }
        # }

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
            week = weeks.setdefault(iso_week, {})
            entry = week.setdefault(
                uid,
                {"scores": {}, "total_strokes": 0, "total_par": 0, "rounds": 0},
            )

            # Dedupe: if they already posted this day, skip
            if day_key in entry["scores"]:
                return

            entry["scores"][day_key] = {
                "strokes": strokes,
                "par": par,
                "relative": relative,
                "timestamp": now.isoformat(),
            }
            entry["total_strokes"] += strokes
            entry["total_par"] += par
            entry["rounds"] += 1

        # React to confirm
        try:
            await message.add_reaction("⛳")
        except discord.HTTPException:
            pass

    # ── Helpers ───────────────────────────────────────────────────────

    def _build_leaderboard(self, ctx, totals: dict) -> list:
        """Build sorted leaderboard lines from ``{uid: {rounds, total_rel}}``.

        Sorted by average relative to par (lowest = best), with total then
        round count as tie-breakers.
        """
        rows = []
        for uid, data in totals.items():
            rounds = data["rounds"]
            if not rounds:
                continue
            member = ctx.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            avg_rel = data["total_rel"] / rounds
            rows.append((name, rounds, data["total_rel"], avg_rel))

        rows.sort(key=lambda r: (r[3], r[2], -r[1]))

        lines = []
        for i, (name, rounds, total_rel, avg_rel) in enumerate(rows):
            prefix = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
            lines.append(
                f"{prefix} **{name}** — {rounds} round{'s' if rounds != 1 else ''}, "
                f"total {_fmt_rel(total_rel)}, avg {avg_rel:+.1f}"
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
        await self._paginate(ctx, f"⛳ **Weekly Leaderboard — {iso_week}**", lines)

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
        await self._paginate(ctx, "⛳ **All-Time Leaderboard**", lines)

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
                    f"  Day #{day_key}: {score['strokes']}/{score['par']} "
                    f"({_fmt_rel(score['relative'])})"
                )

        if not all_scores:
            await ctx.send("No scores recorded for you yet.")
            return

        avg_rel = total_rel / total_rounds if total_rounds else 0
        summary = (
            f"\n**Total:** {total_rounds} rounds, {_fmt_rel(total_rel)} overall, "
            f"{avg_rel:+.1f} avg"
        )
        await self._paginate(
            ctx, f"⛳ **{ctx.author.display_name}'s Scores**", all_scores, footer=summary
        )

    # ── Output ────────────────────────────────────────────────────────

    async def _paginate(self, ctx, title: str, lines: list, footer: str = ""):
        """Send ``title`` + ``lines`` (+ optional ``footer``), paginated."""
        body = "\n".join(lines)
        if footer:
            body = f"{body}\n{footer}"
        pages = list(pagify(body, delims=["\n"], page_length=1900)) or [""]
        for i, page in enumerate(pages):
            await ctx.send(f"{title}\n{page}" if i == 0 else page)
