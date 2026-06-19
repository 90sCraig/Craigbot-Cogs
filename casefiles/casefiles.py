"""
CaseFiles — crowdsource the gaps in a tape archive.

A "cold case" is an unidentified tape from your Obsidian vault. You feed the
bot a batch of images (drag them into an intake channel, add them one by one,
or import a JSON manifest); it serves them to a case channel **one at a time**.
Detectives reply with leads, a detective/mod confirms the ID, and the bot
advances to the next case — banking the solved record so you can export it and
import it back into your vault.

Decoupled by design: the bot never touches your vault. Images come in over
Discord and are stored by the cog; solved cases go out as an Obsidian-ready
file you review and merge yourself.
"""

import io
import json
import re
from datetime import datetime, timezone

import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.views import ConfirmView

# Fields a case carries. "title" is the headline gap; the rest are the
# collector details that pin a release down.
KNOWN_KEYS = ("title", "distributor", "catalog", "year", "notes")
FIELD_LABELS = {
    "title": "Title",
    "distributor": "Distributor / label",
    "catalog": "Catalog #",
    "year": "Year",
    "notes": "Notes",
}
# Matches "key=value" tokens in a solve/add command, where a value runs until
# the next known key or the end of the string (so values may contain spaces).
_FIELD_RE = re.compile(
    r"(?i)\b(" + "|".join(KNOWN_KEYS) + r")\s*=\s*(.*?)(?=\s+\b(?:"
    + "|".join(KNOWN_KEYS) + r")\s*=|$)"
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _parse_fields(text: str) -> dict:
    """Pull ``key=value`` pairs (from KNOWN_KEYS) out of free text."""
    out = {}
    for key, value in _FIELD_RE.findall(text or ""):
        value = value.strip()
        if value:
            out[key.lower()] = value
    return out


def _detective_check():
    """Allow bot owner, Manage Server, or the configured Detective role."""

    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.manage_guild:
            return True
        role_id = await ctx.cog.config.guild(ctx.guild).detective_role()
        return bool(role_id) and any(r.id == role_id for r in ctx.author.roles)

    return commands.check(predicate)


class CaseFiles(commands.Cog):
    """Crowdsource tape IDs: serve unidentified tapes, collect leads, export solves."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.image_root = cog_data_path(self) / "images"
        self.image_root.mkdir(parents=True, exist_ok=True)

        self.config = Config.get_conf(
            self, identifier=20260620, force_registration=True
        )
        self.config.register_guild(
            case_channel=None,        # where cases are served + leads collected
            intake_channel=None,      # drop raw tape images here for `ingest`
            detective_role=None,      # who may solve/skip (None = Manage Server)
            auto_advance=True,        # serve the next case automatically on solve
            capture_all=True,         # treat all case-channel msgs as leads (else replies only)
            counter=0,                # for auto-generated case ids
            active_id=None,           # id of the case currently being served
            order=[],                 # queued case ids, FIFO
            cases={},                 # id -> case dict (see below)
            detective_scores={},      # uid -> solved count
        )
        # case = {
        #   "id", "image_file", "source",            # source = origin attachment id
        #   "known": {title, distributor, catalog, year},
        #   "status": "queued"|"active"|"solved"|"skipped",
        #   "leads": [{uid, name, text, msg_id, ts}],
        #   "solution": {...}, "solved_by": [uid], "solved_at",
        #   "posted_msg",
        # }

    async def cog_unload(self):
        await self.session.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        for guild_id in await self.config.all_guilds():
            gconf = self.config.guild_from_id(guild_id)
            async with gconf.cases() as cases:
                for case in cases.values():
                    case["leads"] = [
                        lead for lead in case.get("leads", [])
                        if lead.get("uid") != user_id
                    ]
                    if user_id in case.get("solved_by", []):
                        case["solved_by"].remove(user_id)
            async with gconf.detective_scores() as scores:
                scores.pop(str(user_id), None)

    # ── Image storage ────────────────────────────────────────────────────

    def _image_dir(self, guild):
        path = self.image_root / str(guild.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _store_image(self, guild, case_id, *, url=None, attachment=None):
        """Download an image to the cog's data folder; return the filename."""
        ext = ".jpg"
        if attachment is not None:
            url = attachment.url
            name = attachment.filename.lower()
            ext = next((e for e in IMAGE_EXTS if name.endswith(e)), ".jpg")
        elif url:
            lower = url.split("?")[0].lower()
            ext = next((e for e in IMAGE_EXTS if lower.endswith(e)), ".jpg")
        if not url:
            return None
        filename = f"{case_id}{ext}"
        try:
            async with self.session.get(url) as resp:
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

    # ── Lead collection (replies in the case channel) ────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not message.content:
            return
        conf = await self.config.guild(message.guild).all()
        if not conf["case_channel"] or message.channel.id != conf["case_channel"]:
            return
        active_id = conf["active_id"]
        if not active_id or active_id not in conf["cases"]:
            return

        is_reply = bool(
            message.reference
            and message.reference.message_id == conf["cases"][active_id].get("posted_msg")
        )
        if not (conf["capture_all"] or is_reply):
            return
        # Don't log bot commands as leads.
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        async with self.config.guild(message.guild).cases() as cases:
            case = cases.get(active_id)
            if case is None:
                return
            case.setdefault("leads", []).append({
                "uid": message.author.id,
                "name": message.author.display_name,
                "text": message.content[:500],
                "msg_id": message.id,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        try:
            await message.add_reaction("🔍")
        except discord.HTTPException:
            pass

    # ── Serving cases ────────────────────────────────────────────────────

    def _known_lines(self, known: dict) -> str:
        return "\n".join(
            f"**{FIELD_LABELS[k]}:** {known.get(k) or '—'}"
            for k in ("title", "distributor", "catalog", "year")
        )

    async def _serve_case(self, guild, channel, case):
        """Post a cold case to the channel; record its message id."""
        embed = discord.Embed(
            title=f"🔍 Cold Case #{case['id']}",
            description=(
                f"{self._known_lines(case.get('known', {}))}\n\n"
                "*Recognise this tape? Reply with anything you can ID — "
                "distributor, catalog number, year, cover details…*"
            ),
            color=discord.Color.dark_gold(),
        )
        leads = len(case.get("leads", []))
        if leads:
            embed.set_footer(text=f"{leads} lead{'s' if leads != 1 else ''} so far")
        file = self._image_file(guild, case)
        if file:
            embed.set_image(url=f"attachment://{case['image_file']}")
        try:
            msg = await channel.send(embed=embed, file=file)
        except discord.HTTPException:
            return None
        case["posted_msg"] = msg.id
        return msg

    async def _advance(self, guild):
        """Activate and serve the next queued case. Returns the case or None."""
        channel_id = await self.config.guild(guild).case_channel()
        channel = guild.get_channel(channel_id or 0)
        if channel is None:
            return None
        async with self.config.guild(guild).cases() as cases:
            async with self.config.guild(guild).order() as order:
                next_id = None
                while order:
                    candidate = order.pop(0)
                    if candidate in cases and cases[candidate]["status"] == "queued":
                        next_id = candidate
                        break
                if next_id is None:
                    await self.config.guild(guild).active_id.set(None)
                    return None
                cases[next_id]["status"] = "active"
                case_copy = dict(cases[next_id])
        await self.config.guild(guild).active_id.set(next_id)
        # Serve outside the context managers, then persist the message id.
        msg = await self._serve_case(guild, channel, case_copy)
        if msg is not None:
            async with self.config.guild(guild).cases() as cases:
                if next_id in cases:
                    cases[next_id]["posted_msg"] = msg.id
            return case_copy
        return None

    # ── Adding cases ─────────────────────────────────────────────────────

    async def _new_case_id(self, guild, provided=None):
        if provided:
            return str(provided)
        n = await self.config.guild(guild).counter()
        n += 1
        await self.config.guild(guild).counter.set(n)
        return f"{n:04d}"

    @commands.guild_only()
    @commands.group(name="casefile", aliases=["case", "cc"], invoke_without_command=True)
    async def casefile(self, ctx: commands.Context):
        """Crowdsourced tape identification. Use subcommands for details."""
        await ctx.send_help(ctx.command)

    @casefile.command(name="add")
    @_detective_check()
    async def case_add(self, ctx: commands.Context, *, fields: str = ""):
        """Add one cold case from an attached image.

        Attach a tape photo and optionally pass known details, e.g.
        `[p]case add distributor=Vestron year=1987`
        """
        images = [a for a in ctx.message.attachments
                  if (a.content_type or "").startswith("image")
                  or a.filename.lower().endswith(IMAGE_EXTS)]
        if not images:
            await ctx.send("Attach a tape image to add a case.")
            return
        known = _parse_fields(fields)
        added = 0
        for att in images:
            case_id = await self._new_case_id(ctx.guild)
            image_file = await self._store_image(ctx.guild, case_id, attachment=att)
            await self._register_case(ctx.guild, case_id, image_file, known, att.id)
            added += 1
        await ctx.send(f"🗂️ Added **{added}** cold case{'s' if added != 1 else ''} to the queue.")

    @casefile.command(name="ingest")
    @_detective_check()
    async def case_ingest(self, ctx: commands.Context, limit: int = 25):
        """Harvest images from the intake channel into the queue.

        Drag a batch of tape photos into the intake channel, then run this.
        Already-ingested images are skipped. `limit` caps how many recent
        messages are scanned (default 25).
        """
        intake_id = await self.config.guild(ctx.guild).intake_channel()
        intake = ctx.guild.get_channel(intake_id or 0)
        if intake is None:
            await ctx.send("Set an intake channel first: `[p]case set intake #channel`.")
            return
        seen = {
            c.get("source")
            for c in (await self.config.guild(ctx.guild).cases()).values()
            if c.get("source") is not None
        }
        added = 0
        async with ctx.typing():
            async for message in intake.history(limit=max(1, min(200, limit))):
                for att in message.attachments:
                    if att.id in seen:
                        continue
                    if not ((att.content_type or "").startswith("image")
                            or att.filename.lower().endswith(IMAGE_EXTS)):
                        continue
                    case_id = await self._new_case_id(ctx.guild)
                    image_file = await self._store_image(ctx.guild, case_id, attachment=att)
                    await self._register_case(ctx.guild, case_id, image_file, {}, att.id)
                    added += 1
        await ctx.send(
            f"🗂️ Ingested **{added}** new image{'s' if added != 1 else ''} from "
            f"{intake.mention}." if added else "No new images found to ingest."
        )

    @casefile.command(name="import")
    @_detective_check()
    async def case_import(self, ctx: commands.Context):
        """Bulk-add cases from an attached JSON manifest.

        Attach a `.json` file: a list of objects, each optionally with
        `id`, `image_url`, and any of: title, distributor, catalog, year.
        """
        if not ctx.message.attachments:
            await ctx.send("Attach a JSON manifest to import.")
            return
        try:
            raw = await ctx.message.attachments[0].read()
            entries = json.loads(raw)
            assert isinstance(entries, list)
        except (json.JSONDecodeError, AssertionError, UnicodeDecodeError):
            await ctx.send("That doesn't look like a JSON list. See `[p]help case import`.")
            return

        added = 0
        async with ctx.typing():
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                case_id = await self._new_case_id(ctx.guild, entry.get("id"))
                known = {k: str(entry[k]) for k in KNOWN_KEYS if entry.get(k)}
                image_file = None
                if entry.get("image_url"):
                    image_file = await self._store_image(
                        ctx.guild, case_id, url=entry["image_url"]
                    )
                await self._register_case(ctx.guild, case_id, image_file, known, None)
                added += 1
        await ctx.send(f"🗂️ Imported **{added}** case{'s' if added != 1 else ''} into the queue.")

    async def _register_case(self, guild, case_id, image_file, known, source):
        async with self.config.guild(guild).cases() as cases:
            cases[case_id] = {
                "id": case_id,
                "image_file": image_file,
                "source": source,
                "known": {k: known.get(k) for k in ("title", "distributor", "catalog", "year")},
                "status": "queued",
                "leads": [],
                "solution": {},
                "solved_by": [],
                "solved_at": None,
                "posted_msg": None,
            }
        async with self.config.guild(guild).order() as order:
            order.append(case_id)

    # ── Running the queue ────────────────────────────────────────────────

    @casefile.command(name="start", aliases=["next"])
    @_detective_check()
    async def case_start(self, ctx: commands.Context):
        """Serve the next cold case (begins the queue or moves it along)."""
        if not await self.config.guild(ctx.guild).case_channel():
            await ctx.send("Set a case channel first: `[p]case set channel #channel`.")
            return
        active_id = await self.config.guild(ctx.guild).active_id()
        if active_id and ctx.invoked_with != "next":
            await ctx.send(
                f"Cold Case #{active_id} is already active. Use `[p]case next` to skip ahead "
                f"or `[p]case solve` to crack it."
            )
            return
        # `next` on an active case sends it to the back of the queue, not the bin.
        if active_id:
            async with self.config.guild(ctx.guild).cases() as cases:
                if active_id in cases:
                    cases[active_id]["status"] = "queued"
            async with self.config.guild(ctx.guild).order() as order:
                order.append(active_id)
            await self.config.guild(ctx.guild).active_id.set(None)
        case = await self._advance(ctx.guild)
        if case is None:
            await ctx.send("The queue is empty — no cold cases waiting. 🎉")
        elif ctx.channel.id != await self.config.guild(ctx.guild).case_channel():
            await ctx.send(f"Now serving Cold Case #{case['id']}.")

    @casefile.command(name="solve")
    @_detective_check()
    async def case_solve(self, ctx: commands.Context, *, details: str = ""):
        """Confirm the ID for the active case, credit detectives, and advance.

        Pass the confirmed details and @mention whoever cracked it, e.g.
        `[p]case solve title=Blood Diner distributor=Vestron year=1987 @Craig`
        """
        active_id = await self.config.guild(ctx.guild).active_id()
        if not active_id:
            await ctx.send("There's no active case. Start one with `[p]case start`.")
            return
        fields = _parse_fields(details)
        credited = [m.id for m in ctx.message.mentions if not m.bot]

        async with self.config.guild(ctx.guild).cases() as cases:
            case = cases.get(active_id)
            if case is None:
                await ctx.send("Active case not found.")
                return
            solution = dict(case.get("known", {}))
            solution.update(fields)
            if not solution.get("title"):
                await ctx.send(
                    "Give at least a title to solve, e.g. `[p]case solve title=Blood Diner`."
                )
                return
            case["solution"] = solution
            case["status"] = "solved"
            case["solved_by"] = credited
            case["solved_at"] = datetime.now(timezone.utc).isoformat()
            solved_title = solution["title"]

        async with self.config.guild(ctx.guild).detective_scores() as scores:
            for uid in credited:
                scores[str(uid)] = scores.get(str(uid), 0) + 1

        await self.config.guild(ctx.guild).active_id.set(None)
        who = (
            " · cracked by " + ", ".join(f"<@{uid}>" for uid in credited)
            if credited else ""
        )
        await ctx.send(
            f"✅ **Cold Case #{active_id} solved** — *{solved_title}*{who}. "
            f"Banked for export.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if await self.config.guild(ctx.guild).auto_advance():
            if await self._advance(ctx.guild) is None:
                await ctx.send("That was the last one — the queue is clear. 🎉")

    @casefile.command(name="skip")
    @_detective_check()
    async def case_skip(self, ctx: commands.Context, *, reason: str = ""):
        """Shelve the active case (still unidentified) and advance."""
        active_id = await self.config.guild(ctx.guild).active_id()
        if not active_id:
            await ctx.send("There's no active case to skip.")
            return
        async with self.config.guild(ctx.guild).cases() as cases:
            if active_id in cases:
                cases[active_id]["status"] = "skipped"
                if reason:
                    cases[active_id]["skip_reason"] = reason[:300]
        await self.config.guild(ctx.guild).active_id.set(None)
        await ctx.send(f"⏭️ Shelved Cold Case #{active_id}.")
        if await self.config.guild(ctx.guild).auto_advance():
            if await self._advance(ctx.guild) is None:
                await ctx.send("Queue is clear. 🎉")

    # ── Viewing ──────────────────────────────────────────────────────────

    @casefile.command(name="current", aliases=["show"])
    async def case_current(self, ctx: commands.Context):
        """Re-show the active cold case."""
        conf = await self.config.guild(ctx.guild).all()
        active_id = conf["active_id"]
        if not active_id or active_id not in conf["cases"]:
            await ctx.send("No active case right now.")
            return
        channel = ctx.guild.get_channel(conf["case_channel"] or 0) or ctx.channel
        msg = await self._serve_case(ctx.guild, channel, conf["cases"][active_id])
        if msg is not None:
            async with self.config.guild(ctx.guild).cases() as cases:
                if active_id in cases:
                    cases[active_id]["posted_msg"] = msg.id

    @casefile.command(name="leads")
    async def case_leads(self, ctx: commands.Context, case_id: str = None):
        """Show the leads collected for the active case (or a given id)."""
        conf = await self.config.guild(ctx.guild).all()
        case_id = case_id or conf["active_id"]
        case = conf["cases"].get(case_id) if case_id else None
        if not case:
            await ctx.send("No such case.")
            return
        leads = case.get("leads", [])
        if not leads:
            await ctx.send(f"No leads on Cold Case #{case_id} yet.")
            return
        body = "\n".join(f"• **{ld['name']}**: {ld['text']}" for ld in leads)
        for page in pagify(body, page_length=1800):
            await ctx.send(
                embed=discord.Embed(
                    title=f"🔍 Leads — Cold Case #{case_id}",
                    description=page,
                    color=discord.Color.dark_gold(),
                )
            )

    @casefile.command(name="queue")
    @_detective_check()
    async def case_queue(self, ctx: commands.Context):
        """Show how many cases are queued, solved, and shelved."""
        conf = await self.config.guild(ctx.guild).all()
        cases = conf["cases"].values()
        counts = {"queued": 0, "active": 0, "solved": 0, "skipped": 0}
        for c in cases:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
        upcoming = ", ".join(f"#{cid}" for cid in conf["order"][:10]) or "—"
        await ctx.send(
            embed=discord.Embed(
                title="🗂️ Case Files",
                description=(
                    f"**Queued:** {counts['queued']}\n"
                    f"**Active:** {conf['active_id'] or '—'}\n"
                    f"**Solved (awaiting export):** {counts['solved']}\n"
                    f"**Shelved:** {counts['skipped']}\n\n"
                    f"**Up next:** {upcoming}"
                ),
                color=discord.Color.dark_gold(),
            )
        )

    @casefile.command(name="detectives", aliases=["leaderboard", "lb"])
    async def case_detectives(self, ctx: commands.Context):
        """Show the detective leaderboard (cases cracked)."""
        scores = await self.config.guild(ctx.guild).detective_scores()
        rows = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not rows:
            await ctx.send("No cases cracked yet — get sleuthing! 🔍")
            return
        medals = ("🥇", "🥈", "🥉")
        lines = []
        for i, (uid, count) in enumerate(rows[:15]):
            member = ctx.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            prefix = medals[i] if i < len(medals) else f"`{i + 1}.`"
            lines.append(f"{prefix} **{name}** · {count} solved")
        await ctx.send(
            embed=discord.Embed(
                title="🕵️ Detective Leaderboard",
                description="\n".join(lines),
                color=discord.Color.dark_gold(),
            )
        )

    # ── Export (the write-back you import into Obsidian) ─────────────────

    @casefile.command(name="export")
    @_detective_check()
    async def case_export(self, ctx: commands.Context, fmt: str = "md"):
        """Export solved cases as a file to import into your vault.

        `[p]case export` gives Obsidian-ready Markdown (one note per solve);
        `[p]case export json` gives a JSON manifest.
        """
        cases = await self.config.guild(ctx.guild).cases()
        solved = [c for c in cases.values() if c["status"] == "solved"]
        if not solved:
            await ctx.send("No solved cases to export yet.")
            return
        solved.sort(key=lambda c: c["id"])

        if fmt.lower() == "json":
            payload = [
                {
                    "id": c["id"],
                    "image_file": c.get("image_file"),
                    **c["solution"],
                    "solved_by": [
                        (ctx.guild.get_member(uid).display_name
                         if ctx.guild.get_member(uid) else str(uid))
                        for uid in c.get("solved_by", [])
                    ],
                    "solved_at": c.get("solved_at"),
                    "leads": [ld["text"] for ld in c.get("leads", [])],
                }
                for c in solved
            ]
            data = json.dumps(payload, indent=2, ensure_ascii=False)
            filename = "cold-cases-solved.json"
        else:
            data = self._render_markdown(ctx.guild, solved)
            filename = "cold-cases-solved.md"

        file = discord.File(io.BytesIO(data.encode("utf-8")), filename=filename)
        await ctx.send(
            f"🗄️ **{len(solved)}** solved case{'s' if len(solved) != 1 else ''}. "
            f"Review and merge into your vault, then clear with `[p]case clearsolved`.",
            file=file,
        )

    def _render_markdown(self, guild, solved) -> str:
        blocks = []
        for c in solved:
            sol = c["solution"]
            solvers = [
                guild.get_member(uid).display_name if guild.get_member(uid) else str(uid)
                for uid in c.get("solved_by", [])
            ]
            fm = [
                "---",
                "status: identified",
                f"case: {c['id']}",
                f"title: {sol.get('title', '')}",
                f"distributor: {sol.get('distributor', '')}",
                f"catalog: {sol.get('catalog', '')}",
                f"year: {sol.get('year', '')}",
                f"image: {c.get('image_file') or ''}",
                f"solved_by: [{', '.join(solvers)}]",
                f"solved_on: {(c.get('solved_at') or '')[:10]}",
                "---",
            ]
            body = [f"# {sol.get('title', 'Unknown')} (Cold Case #{c['id']})"]
            if sol.get("notes"):
                body.append(f"\n{sol['notes']}")
            leads = c.get("leads", [])
            if leads:
                body.append("\n## Leads")
                body.extend(f"- ({ld['name']}) {ld['text']}" for ld in leads)
            blocks.append("\n".join(fm) + "\n\n" + "\n".join(body))
        return "\n\n---\n\n".join(blocks) + "\n"

    @casefile.command(name="clearsolved")
    @_detective_check()
    async def case_clearsolved(self, ctx: commands.Context):
        """Remove exported (solved) cases from storage. Ask before deleting."""
        cases = await self.config.guild(ctx.guild).cases()
        solved_ids = [cid for cid, c in cases.items() if c["status"] == "solved"]
        if not solved_ids:
            await ctx.send("No solved cases to clear.")
            return
        view = ConfirmView(ctx.author, timeout=30, disable_buttons=True)
        view.message = await ctx.send(
            f"⚠️ Remove **{len(solved_ids)}** solved case(s) from storage? "
            "Make sure you've exported them first. This can't be undone.",
            view=view,
        )
        await view.wait()
        if not view.result:
            await ctx.send("Cancelled.")
            return
        async with self.config.guild(ctx.guild).cases() as cases:
            for cid in solved_ids:
                fname = cases[cid].get("image_file")
                if fname:
                    path = self._image_dir(ctx.guild) / fname
                    path.unlink(missing_ok=True)
                del cases[cid]
        await ctx.send(f"🧹 Cleared **{len(solved_ids)}** solved case(s).")

    # ── Settings ─────────────────────────────────────────────────────────

    @casefile.group(name="set", invoke_without_command=True)
    @commands.admin_or_permissions(manage_guild=True)
    async def case_set(self, ctx: commands.Context):
        """Configure CaseFiles (admin / Manage Server only)."""
        await ctx.send_help(ctx.command)

    @case_set.command(name="channel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the channel where cases are served and leads collected."""
        await self.config.guild(ctx.guild).case_channel.set(channel.id if channel else None)
        await ctx.send(
            f"Cases will be served in {channel.mention}." if channel else "Case channel cleared."
        )

    @case_set.command(name="intake")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_intake(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the intake channel (drop tape images here for `ingest`)."""
        await self.config.guild(ctx.guild).intake_channel.set(channel.id if channel else None)
        await ctx.send(
            f"Intake channel set to {channel.mention}." if channel else "Intake channel cleared."
        )

    @case_set.command(name="role")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_role(self, ctx: commands.Context, role: discord.Role = None):
        """Set the Detective role allowed to run/solve cases (omit to clear)."""
        await self.config.guild(ctx.guild).detective_role.set(role.id if role else None)
        await ctx.send(
            f"Detective role set to **{role.name}**." if role
            else "Detective role cleared (Manage Server only)."
        )

    @case_set.command(name="autoadvance")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_autoadvance(self, ctx: commands.Context, on_off: bool):
        """Toggle automatically serving the next case after a solve/skip."""
        await self.config.guild(ctx.guild).auto_advance.set(on_off)
        await ctx.send(f"Auto-advance {'on' if on_off else 'off'}.")

    @case_set.command(name="captureall")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_captureall(self, ctx: commands.Context, on_off: bool):
        """Toggle logging every case-channel message as a lead (vs replies only)."""
        await self.config.guild(ctx.guild).capture_all.set(on_off)
        await ctx.send(
            "Capturing all messages in the case channel as leads."
            if on_off else "Only direct replies to the case will be logged as leads."
        )

    @case_set.command(name="show", aliases=["settings"])
    @commands.admin_or_permissions(manage_guild=True)
    async def set_show(self, ctx: commands.Context):
        """Show the current CaseFiles settings."""
        c = await self.config.guild(ctx.guild).all()
        case_channel = ctx.guild.get_channel(c["case_channel"]) if c["case_channel"] else None
        intake = ctx.guild.get_channel(c["intake_channel"]) if c["intake_channel"] else None
        role = ctx.guild.get_role(c["detective_role"]) if c["detective_role"] else None
        lines = [
            f"**Case channel:** {case_channel.mention if case_channel else 'not set'}",
            f"**Intake channel:** {intake.mention if intake else 'not set'}",
            f"**Detective role:** {role.mention if role else 'Manage Server only'}",
            f"**Auto-advance:** {'on' if c['auto_advance'] else 'off'}",
            f"**Capture all as leads:** {'on' if c['capture_all'] else 'off'}",
            f"**Active case:** {c['active_id'] or '—'}",
        ]
        await ctx.send(
            embed=discord.Embed(
                title="🗂️ CaseFiles Settings",
                description="\n".join(lines),
                color=discord.Color.dark_gold(),
            )
        )
