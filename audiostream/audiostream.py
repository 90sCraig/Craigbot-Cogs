"""Schedule local media files for playback in Discord voice channels."""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, commands

log = logging.getLogger("red.craigbot.audiostream")

MEDIA_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}
PAGE_SIZE = 25


def _utcnow():
    return datetime.now(timezone.utc)


def _safe_zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return timezone.utc


def _parse_start(value, timezone_name):
    """Return a UTC start time from `now`, `in 10m`, or local date/time text."""
    text = (value or "").strip().lower()
    now = _utcnow()
    if text in {"", "now"}:
        return now

    if text.startswith("in ") and len(text) > 4:
        amount_text = text[3:-1].strip()
        unit = text[-1]
        try:
            amount = int(amount_text)
        except ValueError as exc:
            raise ValueError("Use `now`, `in 10m`, or `YYYY-MM-DD HH:MM`.") from exc
        if amount < 1 or unit not in {"m", "h", "d"}:
            raise ValueError("Relative times use a positive number followed by m, h, or d.")
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return now + delta

    try:
        local = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Use `now`, `in 10m`, or `YYYY-MM-DD HH:MM`.") from exc
    return local.replace(tzinfo=_safe_zone(timezone_name)).astimezone(timezone.utc)


class StartTimeModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Schedule audio playback", timeout=300)
        self.picker = view
        zone = _safe_zone(view.timezone_name)
        example = (_utcnow() + timedelta(minutes=10)).astimezone(zone)
        self.start_time = discord.ui.TextInput(
            label=f"Start time ({view.timezone_name})"[:45],
            placeholder=example.strftime("%Y-%m-%d %H:%M") + ", now, or in 10m",
            required=True,
            max_length=32,
        )
        self.add_item(self.start_time)

    async def on_submit(self, interaction):
        try:
            start_at = _parse_start(str(self.start_time), self.picker.timezone_name)
            if start_at < _utcnow() - timedelta(seconds=30):
                raise ValueError("That time has already passed.")
            item_id = await self.picker.cog.create_job(
                interaction.guild,
                self.picker.selected_file,
                self.picker.selected_channel_id,
                interaction.channel_id,
                start_at,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        self.picker.stop()
        timestamp = int(start_at.timestamp())
        await interaction.response.send_message(
            f"Scheduled **{item_id}** for <t:{timestamp}:F> (<t:{timestamp}:R>).",
            ephemeral=True,
        )


class MediaPickerView(discord.ui.View):
    def __init__(self, cog, guild, files, timezone_name):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.files = files
        self.timezone_name = timezone_name
        self.page = 0
        self.selected_file = None
        self.selected_channel_id = None
        self.message = None
        self.rebuild()

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.guild.id:
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Only server administrators can schedule audio.", ephemeral=True
            )
            return False
        return True

    def rebuild(self):
        self.clear_items()
        page_count = max(1, (len(self.files) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(self.page, page_count - 1)
        page_start = self.page * PAGE_SIZE
        page_files = self.files[page_start : (self.page + 1) * PAGE_SIZE]

        file_select = discord.ui.Select(
            placeholder=f"Choose a media file (page {self.page + 1}/{page_count})",
            options=[
                discord.SelectOption(
                    label=Path(name).name[:100],
                    description=(name[:100] if name != Path(name).name else None),
                    value=str(index),
                    default=name == self.selected_file,
                )
                for index, name in enumerate(page_files, start=page_start)
            ],
            row=0,
        )

        async def file_callback(interaction):
            self.selected_file = self.files[int(file_select.values[0])]
            self.rebuild()
            await interaction.response.edit_message(view=self)

        file_select.callback = file_callback
        self.add_item(file_select)

        channel_select = discord.ui.ChannelSelect(
            placeholder="Choose a voice or stage channel",
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
            min_values=1,
            max_values=1,
            row=1,
        )

        async def channel_callback(interaction):
            self.selected_channel_id = channel_select.values[0].id
            self.rebuild()
            await interaction.response.edit_message(view=self)

        channel_select.callback = channel_callback
        self.add_item(channel_select)

        ready = self.selected_file is not None and self.selected_channel_id is not None
        schedule_button = discord.ui.Button(
            label="Choose start time",
            style=discord.ButtonStyle.primary,
            disabled=not ready,
            row=2,
        )

        async def schedule_callback(interaction):
            await interaction.response.send_modal(StartTimeModal(self))

        schedule_button.callback = schedule_callback
        self.add_item(schedule_button)

        play_button = discord.ui.Button(
            label="Play now",
            style=discord.ButtonStyle.success,
            disabled=not ready,
            row=2,
        )

        async def play_callback(interaction):
            try:
                item_id = await self.cog.create_job(
                    interaction.guild,
                    self.selected_file,
                    self.selected_channel_id,
                    interaction.channel_id,
                    _utcnow(),
                )
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
            self.stop()
            await interaction.response.send_message(
                f"Starting **{item_id}** now.", ephemeral=True
            )

        play_button.callback = play_callback
        self.add_item(play_button)

        if page_count > 1:
            previous = discord.ui.Button(
                label="Previous", disabled=self.page == 0, row=3
            )
            next_button = discord.ui.Button(
                label="Next", disabled=self.page >= page_count - 1, row=3
            )

            async def previous_callback(interaction):
                self.page -= 1
                self.rebuild()
                await interaction.response.edit_message(view=self)

            async def next_callback(interaction):
                self.page += 1
                self.rebuild()
                await interaction.response.edit_message(view=self)

            previous.callback = previous_callback
            next_button.callback = next_callback
            self.add_item(previous)
            self.add_item(next_button)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AudioStream(commands.Cog):
    """Play scheduled local media in voice channels."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=20261005, force_registration=True)
        self.config.register_global(media_folder=None)
        self.config.register_guild(timezone="UTC", counter=0, jobs={})
        self._starting = set()
        self._play_tasks = set()
        self._locks = {}
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()
        for task in self._play_tasks:
            task.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        return

    @tasks.loop(seconds=5)
    async def scheduler(self):
        now_timestamp = _utcnow().timestamp()
        for guild_id, conf in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            for item_id, job in list(conf["jobs"].items()):
                key = (guild_id, item_id)
                if job["start_at"] <= now_timestamp and key not in self._starting:
                    self._starting.add(key)
                    task = asyncio.create_task(self._run_job(guild, item_id, job))
                    self._play_tasks.add(task)
                    task.add_done_callback(self._play_tasks.discard)

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_red_ready()

    async def _configured_root(self):
        folder = await self.config.media_folder()
        if not folder:
            return None
        return Path(folder).expanduser().resolve()

    async def _list_media(self):
        root = await self._configured_root()
        if root is None or not root.is_dir():
            return []
        files = []
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                files.append(path.relative_to(root).as_posix())
        return sorted(files, key=str.casefold)

    async def _resolve_media(self, relative_name):
        root = await self._configured_root()
        if root is None or not root.is_dir():
            raise ValueError("The configured media folder is unavailable.")
        candidate = (root / relative_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("That file is outside the configured media folder.") from exc
        if not candidate.is_file() or candidate.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError("That media file is no longer available.")
        return candidate

    async def create_job(self, guild, filename, channel_id, text_channel_id, start_at):
        await self._resolve_media(filename)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            raise ValueError("Choose a voice or stage channel from this server.")
        if shutil.which("ffmpeg") is None:
            raise ValueError("FFmpeg is not installed or is not available to the bot.")

        async with self.config.guild(guild).all() as conf:
            conf["counter"] += 1
            item_id = f"AUDIO-{conf['counter']:04d}"
            conf["jobs"][item_id] = {
                "id": item_id,
                "filename": filename,
                "channel_id": channel_id,
                "text_channel_id": text_channel_id,
                "start_at": start_at.timestamp(),
            }
        return item_id

    async def _notify(self, guild, job, message):
        channel = guild.get_channel(job.get("text_channel_id") or 0)
        if channel is not None:
            try:
                await channel.send(message)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _remove_job(self, guild, item_id):
        async with self.config.guild(guild).jobs() as jobs:
            jobs.pop(item_id, None)

    async def _run_job(self, guild, item_id, job):
        key = (guild.id, item_id)
        lock = self._locks.setdefault(guild.id, asyncio.Lock())
        error = None
        playback_started = False
        connected_by_us = False
        try:
            if lock.locked():
                await self._notify(
                    guild,
                    job,
                    f"**{item_id}** could not play because another AudioStream job is active.",
                )
                return
            async with lock:
                channel = guild.get_channel(job["channel_id"])
                if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                    raise RuntimeError("the selected voice channel no longer exists")
                media = await self._resolve_media(job["filename"])
                voice = guild.voice_client
                if voice is not None and (voice.is_playing() or voice.is_paused()):
                    raise RuntimeError("the bot is already playing audio in this server")
                if voice is None:
                    voice = await channel.connect()
                    connected_by_us = True
                elif voice.channel.id != channel.id:
                    await voice.move_to(channel)

                if isinstance(channel, discord.StageChannel):
                    member = guild.me
                    if member is not None and member.voice and member.voice.suppress:
                        try:
                            await member.edit(suppress=False)
                        except (discord.Forbidden, discord.HTTPException):
                            pass

                await self._notify(
                    guild,
                    job,
                    f"**{item_id}** is now playing **{job['filename']}** in {channel.mention}.",
                )
                finished = asyncio.Event()
                playback_error = []
                loop = asyncio.get_running_loop()

                def after_playback(exc):
                    if exc is not None:
                        playback_error.append(exc)
                    loop.call_soon_threadsafe(finished.set)

                source = discord.FFmpegPCMAudio(
                    str(media), before_options="-nostdin", options="-vn"
                )
                voice.play(source, after=after_playback)
                playback_started = True
                await finished.wait()
                if playback_error:
                    raise RuntimeError(str(playback_error[0]))
                await self._notify(
                    guild, job, f"**{item_id}** finished playing **{job['filename']}**."
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Discord/voice errors vary across supported versions.
            error = exc
            log.exception("Audio job %s failed in guild %s", item_id, guild.id)
            await self._notify(guild, job, f"**{item_id}** could not play: {exc}")
        finally:
            voice = guild.voice_client
            if voice is not None and (playback_started or connected_by_us):
                try:
                    await voice.disconnect(force=True)
                except (discord.ClientException, discord.HTTPException):
                    pass
            await self._remove_job(guild, item_id)
            self._starting.discard(key)
            if error:
                log.info("Removed failed audio job %s", item_id)

    def _job_lines(self, guild, conf):
        lines = []
        for job in sorted(conf["jobs"].values(), key=lambda item: item["start_at"]):
            channel = guild.get_channel(job["channel_id"])
            timestamp = int(job["start_at"])
            filename = job["filename"]
            if len(filename) > 80:
                filename = "…" + filename[-79:]
            lines.append(
                f"**{job['id']}** · `{filename}` · "
                f"{channel.mention if channel else 'missing channel'} · <t:{timestamp}:F>"
            )
        return lines

    @commands.guild_only()
    @commands.hybrid_group(name="audiostream", aliases=["localstream"], invoke_without_command=True)
    @commands.admin()
    async def audiostream(self, ctx):
        """Select and schedule a local media file for voice playback."""
        files = await self._list_media()
        if not files:
            await ctx.send(
                "No media files are available. The bot owner should run "
                f"`{ctx.clean_prefix}audiostreamset folder <path>`."
            )
            return
        conf = await self.config.guild(ctx.guild).all()
        view = MediaPickerView(self, ctx.guild, files, conf["timezone"])
        embed = discord.Embed(
            title="Schedule local audio",
            description=(
                "Choose a file and a voice or stage channel, then play it now or choose "
                f"a start time. Times use **{conf['timezone']}**."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"{len(files)} media file(s) available")
        view.message = await ctx.send(embed=embed, view=view)

    @audiostream.command(name="list")
    async def audiostream_list(self, ctx):
        """List scheduled and active audio jobs."""
        conf = await self.config.guild(ctx.guild).all()
        lines = self._job_lines(ctx.guild, conf)
        visible = lines[:15]
        if len(lines) > len(visible):
            visible.append(f"…and **{len(lines) - len(visible)}** more.")
        await ctx.send(
            "**Scheduled audio**\n"
            + ("\n".join(visible) if visible else "Nothing scheduled.")
        )

    @audiostream.command(name="cancel")
    async def audiostream_cancel(self, ctx, item_id: str):
        """Cancel a scheduled job before it starts."""
        item_id = item_id.upper()
        if (ctx.guild.id, item_id) in self._starting:
            await ctx.send("That job has already started. Use the stop command instead.")
            return
        async with self.config.guild(ctx.guild).jobs() as jobs:
            removed = jobs.pop(item_id, None)
        await ctx.send(
            f"Cancelled **{item_id}**." if removed else "I couldn't find that scheduled job."
        )

    @audiostream.command(name="stop")
    async def audiostream_stop(self, ctx):
        """Stop the current playback and disconnect the bot."""
        voice = ctx.guild.voice_client
        if voice is None or not (voice.is_playing() or voice.is_paused()):
            await ctx.send("This server has no active audio playback.")
            return
        voice.stop()
        await ctx.send("Stopped the current audio playback.")

    @commands.group(name="audiostreamset")
    @commands.is_owner()
    async def audiostreamset(self, ctx):
        """Configure access to local media on the bot host."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @audiostreamset.command(name="folder")
    async def audiostreamset_folder(self, ctx, *, folder: str):
        """Set the local folder from which media may be selected."""
        root = Path(folder.strip().strip('"')).expanduser().resolve()
        if not root.is_dir():
            await ctx.send("That folder does not exist or is not a directory.")
            return
        await self.config.media_folder.set(str(root))
        count = len(await self._list_media())
        await ctx.send(f"Media folder set. I found **{count}** supported file(s).")

    @audiostreamset.command(name="show")
    async def audiostreamset_show(self, ctx):
        """Show the configured media folder and FFmpeg status."""
        root = await self._configured_root()
        count = len(await self._list_media())
        await ctx.send(
            "**AudioStream host settings**\n"
            f"Folder: `{root if root else 'not configured'}`\n"
            f"Media files: **{count}**\n"
            f"FFmpeg: **{'available' if shutil.which('ffmpeg') else 'not found'}**"
        )

    @commands.guild_only()
    @commands.group(name="audiostreamserverset")
    @commands.admin()
    async def audiostreamserverset(self, ctx):
        """Configure AudioStream for this Discord server."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @audiostreamserverset.command(name="timezone")
    async def audiostreamserverset_timezone(self, ctx, timezone_name: str):
        """Set the timezone used by the scheduling form."""
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await ctx.send("That timezone wasn't recognized. Try `America/New_York`.")
            return
        await self.config.guild(ctx.guild).timezone.set(timezone_name)
        await ctx.send(f"AudioStream timezone set to **{timezone_name}**.")
