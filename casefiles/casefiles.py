"""
CaseFiles — the "VHS Detectives" engagement bot (v1).

One case is live at a time in a single case channel. The admin opens a case
(a mystery tape to read, or a post-stream research case); the community talks
right there in the channel; the admin **stamps** good messages with an emoji
to confirm them. A stamp is the one action that matters: it awards the author
points, records a Confirmed Finding on the case card, and bumps their rank.

No threads. Opening the next case archives the current one. Nothing counts
until it's stamped — that's the anti-spam, the reward, and (later) the
archive-write, all in one.

v1 scope: the Discord loop only. Rank *roles*, vault/Gitea notes, and the
monthly shoutout are deliberately left for the fast-follow.
"""

from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.data_manager import cog_data_path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

DEFAULT_STAMP_EMOJI = {"💡": 1, "🔍": 3, "🏆": 5}
DEFAULT_RANKS = [
    {"name": "Tape Spotter", "points": 1},
    {"name": "Label Reader", "points": 5},
    {"name": "Case Cracker", "points": 15},
    {"name": "Field Archivist", "points": 35},
    {"name": "Senior Investigator", "points": 70},
    {"name": "Cold Case Closer", "points": 125},
]


def _now():
    return datetime.now(timezone.utc)


def _trunc(text: str, width: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


class CaseFiles(commands.Cog):
    """VHS Detectives — stamp community findings on the live case to award points & ranks."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.image_root = cog_data_path(self) / "images"
        self.image_root.mkdir(parents=True, exist_ok=True)

        self.config = Config.get_conf(self, identifier=20260621, force_registration=True)
        self.config.register_guild(
            case_channel=None,         # the single channel cases live in
            admin_role=None,           # who may stamp (else Manage Server)
            stamp_emoji=DEFAULT_STAMP_EMOJI,
            ranks=DEFAULT_RANKS,
            counter=0,                 # for sequential CASE-001 ids
            active_case=None,          # case_id of the live case
            cases={},                  # case_id -> case dict
            contributions={},          # message_id(str) -> contribution (source of truth)
        )
        # case = {case_id, type, channel_id, image_file, status, opened_at, opened_ts,
        #         message_id, tape_id?, title?, machine_guess?, open_questions?}
        # contribution = {case_id, author_id, author_name, content, emoji, points,
        #                 posted_ts, stamped_at}

    async def cog_unload(self):
        await self.session.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        for guild_id in await self.config.all_guilds():
            async with self.config.guild_from_id(guild_id).contributions() as contribs:
                for mid in [m for m, c in contribs.items() if c.get("author_id") == user_id]:
                    del contribs[mid]

    # ── Image storage ────────────────────────────────────────────────────

    def _image_dir(self, guild):
        path = self.image_root / str(guild.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _is_image(att: discord.Attachment) -> bool:
        return (att.content_type or "").startswith("image") or att.filename.lower().endswith(IMAGE_EXTS)

    async def _store_image(self, guild, case_id, attachment) -> str:
        name = attachment.filename.lower()
        ext = next((e for e in IMAGE_EXTS if name.endswith(e)), ".jpg")
        filename = f"{case_id}{ext}"
        try:
            async with self.session.get(attachment.url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        except aiohttp.ClientError:
            return None
        (self._image_dir(guild) / filename).write_bytes(data)
        return filename

    def _image_file(self, guild, case):
        fname = case.get("image_file")
        if not fname:
            return None
        path = self._image_dir(guild) / fname
        return discord.File(path, filename=fname) if path.exists() else None

    # ── Permissions / ranks ──────────────────────────────────────────────

    @staticmethod
    def _is_stamper(member: discord.Member, conf: dict) -> bool:
        if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
            return True
        role_id = conf.get("admin_role")
        return bool(role_id) and any(r.id == role_id for r in member.roles)

    @staticmethod
    def _rank_index(conf: dict, total: int) -> int:
        idx = -1
        for i, rank in enumerate(conf["ranks"]):
            if total >= rank["points"]:
                idx = i
        return idx

    def _rank_name(self, conf: dict, total: int) -> str:
        idx = self._rank_index(conf, total)
        return conf["ranks"][idx]["name"] if idx >= 0 else "Unranked"

    def _points_to_next(self, conf: dict, total: int):
        idx = self._rank_index(conf, total)
        if idx + 1 < len(conf["ranks"]):
            nxt = conf["ranks"][idx + 1]
            return nxt["points"] - total, nxt["name"]
        return None, None

    @staticmethod
    def _author_total(contribs: dict, author_id: int) -> int:
        return sum(c["points"] for c in contribs.values() if c["author_id"] == author_id)

    # ── Case lookup / attribution ────────────────────────────────────────

    @staticmethod
    def _case_for_message(conf: dict, channel_id: int, posted_ts: float):
        """The case that was live in ``channel_id`` when the message was posted."""
        best, best_ts = None, -1.0
        for cid, case in conf["cases"].items():
            if case["channel_id"] != channel_id:
                continue
            if best_ts < case["opened_ts"] <= posted_ts:
                best, best_ts = cid, case["opened_ts"]
        return best

    @staticmethod
    def _findings_for(conf: dict, case_id: str) -> list:
        rows = [c for c in conf["contributions"].values() if c["case_id"] == case_id]
        rows.sort(key=lambda c: c["stamped_at"])
        return rows

    # ── Card rendering ───────────────────────────────────────────────────

    def _build_card_embed(self, case: dict, findings: list, limit: int = 5) -> discord.Embed:
        mystery = case["type"] == "mystery"
        if mystery:
            embed = discord.Embed(
                title=f"🔍 NEW CASE — {case['case_id']}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Status", value="🟡 Cold — never streamed", inline=False)
            if case.get("machine_guess"):
                embed.add_field(
                    name="🤖 Machine guess (unverified)",
                    value=case["machine_guess"],
                    inline=False,
                )
            embed.add_field(
                name="Your mission",
                value="Read the label and call the content — just reply in this channel.",
                inline=False,
            )
        else:
            embed = discord.Embed(
                title=f"📂 CASE FILE — {case.get('tape_id') or case['case_id']}",
                description=f"**{case.get('title') or 'Untitled tape'}**",
                color=discord.Color.green(),
            )
            embed.add_field(name="Status", value="🟢 Open for research", inline=False)
            embed.add_field(
                name="Streamed", value=case["opened_at"][:10], inline=True
            )
            if case.get("open_questions"):
                embed.add_field(
                    name="❓ Open questions", value=case["open_questions"], inline=False
                )
            embed.add_field(
                name="​",
                value="🔒 *Core notes are locked. Anything stamped lives in the case file.*",
                inline=False,
            )

        if case.get("image_file"):
            embed.set_image(url=f"attachment://{case['image_file']}")

        if findings:
            shown = findings[-limit:]
            lines = [
                f"{c['emoji']} {_trunc(c['content'] or '(see message)', 80)} — "
                f"**{c['author_name']}** (+{c['points']})"
                for c in shown
            ]
            body = "\n".join(lines)
            if len(findings) > limit:
                body = f"➕ {len(findings) - limit} more · `/case status`\n" + body
        else:
            body = "*None yet — be the first to crack it.*"
        embed.add_field(name="✅ Confirmed Findings", value=body[:1024], inline=False)
        embed.set_footer(text=case["case_id"])
        return embed

    async def _refresh_card(self, guild, case_id: str):
        conf = await self.config.guild(guild).all()
        case = conf["cases"].get(case_id)
        if not case or not case.get("message_id"):
            return
        channel = guild.get_channel(case["channel_id"])
        if channel is None:
            return
        embed = self._build_card_embed(case, self._findings_for(conf, case_id))
        try:
            msg = await channel.fetch_message(case["message_id"])
            await msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    # ── Stamp / un-stamp (shared by listeners and rescan) ────────────────

    async def _record_stamp(self, guild, message: discord.Message, emoji: str, *, announce=True) -> bool:
        conf = await self.config.guild(guild).all()
        points = conf["stamp_emoji"].get(emoji)
        if points is None:
            return False
        case_id = self._case_for_message(conf, message.channel.id, message.created_at.timestamp())
        if case_id is None:
            return False  # message predates every case

        mid = str(message.id)
        crossed = None
        async with self.config.guild(guild).contributions() as contribs:
            existing = contribs.get(mid)
            if existing and existing["emoji"] == emoji:
                return False  # idempotent
            author_id = message.author.id
            before = self._author_total(contribs, author_id)
            contribs[mid] = {
                "case_id": case_id,
                "author_id": author_id,
                "author_name": message.author.display_name,
                "content": (message.content or "")[:300],
                "emoji": emoji,
                "points": points,
                "posted_ts": message.created_at.timestamp(),
                "stamped_at": _now().isoformat(),
            }
            after = self._author_total(contribs, author_id)
            if self._rank_index(conf, after) > self._rank_index(conf, before):
                crossed = self._rank_name(conf, after)

        await self._refresh_card(guild, case_id)
        if announce and crossed:
            channel = guild.get_channel(message.channel.id)
            if channel:
                try:
                    await channel.send(
                        f"🎉 {message.author.mention} reached **{crossed}**!",
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.HTTPException:
                    pass
        return True

    async def _remove_stamp(self, guild, mid: str) -> bool:
        async with self.config.guild(guild).contributions() as contribs:
            existing = contribs.pop(mid, None)
        if not existing:
            return False
        await self._refresh_card(guild, existing["case_id"])
        return True

    # ── Listeners ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        conf = await self.config.guild(guild).all()
        if not conf["case_channel"] or payload.channel_id != conf["case_channel"]:
            return
        emoji = str(payload.emoji)
        if emoji not in conf["stamp_emoji"]:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or not self._is_stamper(member, conf):
            return
        channel = guild.get_channel(payload.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.author.bot or message.author.id == member.id:
            return  # no bot/self stamping
        if any(c.get("message_id") == message.id for c in conf["cases"].values()):
            return  # don't stamp a case card itself
        await self._record_stamp(guild, message, emoji)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        conf = await self.config.guild(guild).all()
        if not conf["case_channel"] or payload.channel_id != conf["case_channel"]:
            return
        emoji = str(payload.emoji)
        mid = str(payload.message_id)
        existing = conf["contributions"].get(mid)
        if not existing or existing["emoji"] != emoji:
            return
        # Only un-stamp if no admin is still reacting with this emoji (a regular
        # member removing their own copy must not undo the admin's stamp).
        channel = guild.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        for reaction in message.reactions:
            if str(reaction.emoji) != emoji:
                continue
            async for user in reaction.users():
                m = guild.get_member(user.id)
                if m and self._is_stamper(m, conf):
                    return  # an admin stamp remains
        await self._remove_stamp(guild, mid)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if str(payload.message_id) in (await self.config.guild(guild).contributions()):
            await self._remove_stamp(guild, str(payload.message_id))

    # ── Opening cases ────────────────────────────────────────────────────

    async def _open_case(self, ctx, ctype, attachment, **fields):
        await ctx.defer(ephemeral=True)  # downloading the image can take a moment
        conf = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(conf["case_channel"] or 0)
        if channel is None:
            await ctx.send("Set the case channel first: `[p]caseset channel #channel`.")
            return
        if not self._is_image(attachment):
            await ctx.send("Please attach an image of the tape.")
            return

        n = conf["counter"] + 1
        await self.config.guild(ctx.guild).counter.set(n)
        case_id = f"CASE-{n:03d}"
        image_file = await self._store_image(ctx.guild, case_id, attachment)
        now = _now()
        case = {
            "case_id": case_id,
            "type": ctype,
            "channel_id": channel.id,
            "image_file": image_file,
            "status": "active",
            "opened_at": now.isoformat(),
            "opened_ts": now.timestamp(),
            "message_id": None,
            "tape_id": fields.get("tape_id"),
            "title": fields.get("title"),
            "machine_guess": fields.get("machine_guess"),
            "open_questions": fields.get("open_questions"),
        }

        await self._archive_active(ctx.guild, conf)
        async with self.config.guild(ctx.guild).cases() as cases:
            cases[case_id] = case
        await self.config.guild(ctx.guild).active_case.set(case_id)

        embed = self._build_card_embed(case, [])
        file = self._image_file(ctx.guild, case)
        try:
            msg = await channel.send(embed=embed, file=file)
        except discord.HTTPException:
            await ctx.send("Couldn't post the case card — check my permissions in that channel.")
            return
        try:
            await msg.pin(reason="Active VHS Detectives case")
        except discord.HTTPException:
            pass
        async with self.config.guild(ctx.guild).cases() as cases:
            cases[case_id]["message_id"] = msg.id

        await ctx.send(f"🗂️ Opened **{case_id}** in {channel.mention}.", ephemeral=True)

    async def _archive_active(self, guild, conf):
        active = conf.get("active_case")
        if not active:
            return
        case = conf["cases"].get(active)
        if case and case.get("message_id"):
            channel = guild.get_channel(case["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(case["message_id"])
                    await msg.unpin(reason="Case archived")
                except discord.HTTPException:
                    pass
        async with self.config.guild(guild).cases() as cases:
            if active in cases:
                cases[active]["status"] = "archived"
        await self.config.guild(guild).active_case.set(None)

    # ── Commands ─────────────────────────────────────────────────────────

    @commands.guild_only()
    @commands.hybrid_group(name="case")
    async def case(self, ctx: commands.Context):
        """VHS Detectives case board."""
        await ctx.send_help(ctx.command)

    @case.command(name="mystery")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        image="Photo of the tape label",
        guess="Optional machine/AI transcription for detectives to push against",
    )
    async def case_mystery(self, ctx: commands.Context, image: discord.Attachment, *, guess: str = None):
        """Open a mystery case (a tape that's never been streamed)."""
        await self._open_case(ctx, "mystery", image, machine_guess=guess)

    @case.command(name="stream")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(
        image="Photo of the tape",
        tape_id="Archive id, e.g. VHS-2026-112",
        title="The tape's known title",
        questions="2–3 open questions to seed the research",
    )
    async def case_stream(
        self, ctx: commands.Context, image: discord.Attachment,
        tape_id: str, title: str, *, questions: str,
    ):
        """Open a post-stream research case."""
        await self._open_case(
            ctx, "stream", image, tape_id=tape_id, title=title, open_questions=questions
        )

    @case.command(name="status")
    async def case_status(self, ctx: commands.Context):
        """Reprint the current case card and its confirmed findings."""
        conf = await self.config.guild(ctx.guild).all()
        active = conf["active_case"]
        if not active or active not in conf["cases"]:
            await ctx.send("No case is open right now.")
            return
        case = conf["cases"][active]
        embed = self._build_card_embed(case, self._findings_for(conf, active), limit=10)
        file = self._image_file(ctx.guild, case)
        await ctx.send(embed=embed, file=file)

    @case.command(name="close")
    @commands.admin_or_permissions(manage_guild=True)
    async def case_close(self, ctx: commands.Context):
        """Archive the current case without opening a new one."""
        conf = await self.config.guild(ctx.guild).all()
        if not conf["active_case"]:
            await ctx.send("No case is open.")
            return
        closed = conf["active_case"]
        await self._archive_active(ctx.guild, conf)
        await ctx.send(f"📦 Archived **{closed}**.", ephemeral=True)

    @case.command(name="rescan")
    @commands.admin_or_permissions(manage_guild=True)
    async def case_rescan(self, ctx: commands.Context):
        """Reconcile stamps on the active case (catches any made while I was offline)."""
        conf = await self.config.guild(ctx.guild).all()
        active = conf["active_case"]
        if not active or active not in conf["cases"]:
            await ctx.send("No case is open to rescan.")
            return
        case = conf["cases"][active]
        channel = ctx.guild.get_channel(case["channel_id"])
        if channel is None:
            await ctx.send("Case channel not found.")
            return
        await ctx.defer(ephemeral=True)  # scanning history can take a moment

        added = 0
        after = datetime.fromtimestamp(case["opened_ts"], tz=timezone.utc)
        async for message in channel.history(limit=500, after=after):
            if message.author.bot or message.id == case["message_id"]:
                continue
            if str(message.id) in (await self.config.guild(ctx.guild).contributions()):
                continue
            stamp = None
            for reaction in message.reactions:
                e = str(reaction.emoji)
                if e not in conf["stamp_emoji"]:
                    continue
                async for user in reaction.users():
                    m = ctx.guild.get_member(user.id)
                    if m and self._is_stamper(m, conf) and m.id != message.author.id:
                        stamp = e
                        break
                if stamp:
                    break
            if stamp and await self._record_stamp(ctx.guild, message, stamp, announce=False):
                added += 1
        await ctx.send(f"🔁 Rescan complete — reconciled **{added}** stamp(s).", ephemeral=True)

    @commands.guild_only()
    @commands.hybrid_command(name="rank")
    async def rank(self, ctx: commands.Context):
        """Show your detective points and rank (only you see this)."""
        conf = await self.config.guild(ctx.guild).all()
        total = self._author_total(conf["contributions"], ctx.author.id)
        rank = self._rank_name(conf, total)
        to_next, next_name = self._points_to_next(conf, total)
        line = f"🕵️ You have **{total}** point{'' if total == 1 else 's'} — **{rank}**."
        if to_next is not None:
            line += f" {to_next} to go until **{next_name}**."
        else:
            line += " That's the top rank — nice work."
        await ctx.send(line, ephemeral=True)

    # ── Settings ─────────────────────────────────────────────────────────

    @commands.guild_only()
    @commands.group(name="caseset")
    @commands.admin_or_permissions(manage_guild=True)
    async def caseset(self, ctx: commands.Context):
        """Configure the VHS Detectives case board."""
        await ctx.send_help(ctx.command)

    @caseset.command(name="channel")
    async def caseset_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the channel cases are posted in (omit to clear)."""
        await self.config.guild(ctx.guild).case_channel.set(channel.id if channel else None)
        await ctx.send(
            f"Cases will live in {channel.mention}." if channel else "Case channel cleared."
        )

    @caseset.command(name="adminrole")
    async def caseset_adminrole(self, ctx: commands.Context, role: discord.Role = None):
        """Set a role (besides Manage Server) whose reactions count as stamps."""
        await self.config.guild(ctx.guild).admin_role.set(role.id if role else None)
        await ctx.send(
            f"Stamp role set to **{role.name}**." if role
            else "Stamp role cleared (Manage Server only)."
        )

    @caseset.command(name="show", aliases=["settings"])
    async def caseset_show(self, ctx: commands.Context):
        """Show the current settings."""
        c = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(c["case_channel"]) if c["case_channel"] else None
        role = ctx.guild.get_role(c["admin_role"]) if c["admin_role"] else None
        emoji = " · ".join(f"{e} = {p}" for e, p in c["stamp_emoji"].items())
        ranks = ", ".join(f"{r['name']} ({r['points']})" for r in c["ranks"])
        active = c["active_case"] or "—"
        embed = discord.Embed(title="🗂️ VHS Detectives Settings", color=discord.Color.gold())
        embed.add_field(name="Case channel", value=channel.mention if channel else "not set", inline=False)
        embed.add_field(name="Stamp role", value=role.mention if role else "Manage Server only", inline=False)
        embed.add_field(name="Stamps", value=emoji, inline=False)
        embed.add_field(name="Active case", value=active, inline=False)
        embed.add_field(name="Ranks", value=ranks, inline=False)
        await ctx.send(embed=embed)
