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
from datetime import datetime
from collections import defaultdict

import discord
from redbot.core import commands, Config, data_manager

SCORE_PATTERN = re.compile(
    r"putt\.day\s+#(\d+)\s+⛳\s+(\d+)/(\d+)\s+([+-]?\d+)",
    re.IGNORECASE,
)


class PuttTracker(commands.Cog):
    """Track putt.day scores with weekly and overall leaderboards."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=20260617, force_registration=True
        )
        self.config.register_global(weeks={})
        # weeks = {
        #   "2026-W25": {
        #     "user_id_str": {
        #       "scores": {"36": {"strokes": 20, "par": 6, "relative": 14, "timestamp": "..."}},
        #       "total_strokes": 20, "total_par": 6, "rounds": 1
        #     }
        #   }
        # }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        match = SCORE_PATTERN.search(message.content)
        if not match:
            return

        day_num = int(match.group(1))
        strokes = int(match.group(2))
        par = int(match.group(3))
        relative = int(match.group(4))

        now = datetime.utcnow()
        iso_week = f"{now.year}-W{now.isocalendar()[1]:02d}"
        uid = str(message.author.id)

        async with self.config.weeks() as weeks:
            if iso_week not in weeks:
                weeks[iso_week] = {}
            week = weeks[iso_week]
            if uid not in week:
                week[uid] = {
                    "scores": {},
                    "total_strokes": 0,
                    "total_par": 0,
                    "rounds": 0,
                }
            entry = week[uid]

            # Dedupe: if they already posted this day, skip
            day_key = str(day_num)
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

    # ── Commands ──────────────────────────────────────────────────────

    @commands.group(name="putt", invoke_without_command=True)
    async def putt(self, ctx: commands.Context):
        """Putt.day score tracker. Use subcommands for details."""
        await ctx.send_help()

    @putt.command(name="weekly", aliases=["week", "w"])
    async def putt_weekly(self, ctx: commands.Context, week_offset: int = 0):
        """Show the weekly leaderboard. Defaults to current week.

        Use a negative offset for past weeks (e.g. `putt weekly -1`).
        """
        now = datetime.utcnow()
        iso = now.isocalendar()
        target_year = iso[0]
        target_week = iso[1] + week_offset
        # Handle year boundaries
        while target_week < 1:
            target_year -= 1
            target_week += 52
        while target_week > 52:
            target_year += 1
            target_week -= 52

        iso_week = f"{target_year}-W{target_week:02d}"
        weeks = await self.config.weeks()
        week_data = weeks.get(iso_week, {})

        if not week_data:
            await ctx.send(f"No scores recorded for week **{iso_week}**.")
            return

        # Resolve members and sort by average relative to par (lowest = best)
        rows = []
        for uid, entry in week_data.items():
            member = ctx.guild.get_member(int(uid)) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            rounds = entry["rounds"]
            total_rel = sum(
                s["relative"] for s in entry["scores"].values()
            )
            avg_rel = total_rel / rounds if rounds else 0
            rows.append((name, rounds, total_rel, avg_rel))

        rows.sort(key=lambda r: r[3])  # lowest avg relative first (best)

        lines = [f"⛳ **Weekly Leaderboard — {iso_week}**\n"]
        medal = ["🥇", "🥈", "🥉"]
        for i, (name, rounds, total_rel, avg_rel) in enumerate(rows):
            prefix = medal[i] if i < 3 else f"{i+1}."
            rel_str = f"+{total_rel}" if total_rel > 0 else str(total_rel)
            lines.append(
                f"{prefix} **{name}** — {rounds} round{'s' if rounds != 1 else ''}, "
                f"total {rel_str}, avg {avg_rel:+.1f}"
            )

        await ctx.send("\n".join(lines))

    @putt.command(name="overall", aliases=["alltime", "o"])
    async def putt_overall(self, ctx: commands.Context):
        """Show the all-time overall leaderboard."""
        weeks = await self.config.weeks()
        if not weeks:
            await ctx.send("No scores recorded yet.")
            return

        # Aggregate across all weeks
        totals = defaultdict(lambda: {"rounds": 0, "total_rel": 0})
        for week_key, week_data in weeks.items():
            for uid, entry in week_data.items():
                totals[uid]["rounds"] += entry["rounds"]
                totals[uid]["total_rel"] += sum(
                    s["relative"] for s in entry["scores"].values()
                )

        rows = []
        for uid, data in totals.items():
            member = ctx.guild.get_member(int(uid)) if ctx.guild else None
            name = member.display_name if member else f"User {uid}"
            avg_rel = data["total_rel"] / data["rounds"] if data["rounds"] else 0
            rows.append((name, data["rounds"], data["total_rel"], avg_rel))

        rows.sort(key=lambda r: r[3])

        lines = ["⛳ **All-Time Leaderboard**\n"]
        medal = ["🥇", "🥈", "🥉"]
        for i, (name, rounds, total_rel, avg_rel) in enumerate(rows):
            prefix = medal[i] if i < 3 else f"{i+1}."
            rel_str = f"+{total_rel}" if total_rel > 0 else str(total_rel)
            lines.append(
                f"{prefix} **{name}** — {rounds} round{'s' if rounds != 1 else ''}, "
                f"total {rel_str}, avg {avg_rel:+.1f}"
            )

        await ctx.send("\n".join(lines))

    @putt.command(name="myscore", aliases=["me", "m"])
    async def putt_myscore(self, ctx: commands.Context):
        """Show your own scores across all weeks."""
        uid = str(ctx.author.id)
        weeks = await self.config.weeks()

        all_scores = []
        total_rel = 0
        total_rounds = 0
        for week_key, week_data in weeks.items():
            if uid not in week_data:
                continue
            entry = week_data[uid]
            total_rounds += entry["rounds"]
            for day_key, score in entry["scores"].items():
                total_rel += score["relative"]
                rel_str = f"+{score['relative']}" if score["relative"] > 0 else str(score["relative"])
                all_scores.append(
                    f"  Day #{day_key}: {score['strokes']}/{score['par']} ({rel_str})"
                )

        if not all_scores:
            await ctx.send("No scores recorded for you yet.")
            return

        avg_rel = total_rel / total_rounds if total_rounds else 0
        rel_str = f"+{total_rel}" if total_rel > 0 else str(total_rel)
        lines = [
            f"⛳ **{ctx.author.display_name}'s Scores**",
            *all_scores,
            f"\n**Total:** {total_rounds} rounds, {rel_str} overall, {avg_rel:+.1f} avg",
        ]
        await ctx.send("\n".join(lines))