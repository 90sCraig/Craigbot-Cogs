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
HISTORY_LIMIT = 100


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


class PlaybackModal(discord.ui.Modal):
    def __init__(self, view, *, play_now=False):
        super().__init__(
            title="Play audio now" if play_now else "Schedule audio playback",
            timeout=300,
        )
        self.picker = view
        self.play_now = play_now
        self.start_time = None
        if not play_now:
            zone = _safe_zone(view.timezone_name)
            example = (_utcnow() + timedelta(minutes=10)).astimezone(zone)
            self.start_time = discord.ui.TextInput(
                label=f"Start time ({view.timezone_name})"[:45],
                placeholder=example.strftime("%Y-%m-%d %H:%M") + ", now, or in 10m",
                required=True,
                max_length=32,
            )
            self.add_item(self.start_time)
        default_title = Path(view.selected_file).stem[:100]
        self.display_title = discord.ui.TextInput(
            label="Now-playing title",
            default=default_title,
            placeholder="Shown in the status, card, and history",
            required=True,
            max_length=100,
        )
        self.voice_status = discord.ui.TextInput(
            label="Voice channel status",
            placeholder="Blank: Now playing: title • Enter off to disable",
            required=False,
            max_length=500,
        )
        self.announcement = discord.ui.TextInput(
            label="Voice channel chat message (optional)",
            placeholder="Posted in the selected voice channel when playback starts",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=2000,
        )
        self.add_item(self.display_title)
        self.add_item(self.voice_status)
        self.add_item(self.announcement)

    async def on_submit(self, interaction):
        try:
            display_title = str(self.display_title).strip()
            status_text = str(self.voice_status).strip()
            if status_text.lower() in {"off", "none", "disabled"}:
                status_text = None
            elif not status_text:
                status_text = f"Now playing: {display_title}"[:500]
            start_at = (
                _utcnow()
                if self.play_now
                else _parse_start(str(self.start_time), self.picker.timezone_name)
            )
            if start_at < _utcnow() - timedelta(seconds=30):
                raise ValueError("That time has already passed.")
            item_id = await self.picker.cog.create_job(
                interaction.guild,
                self.picker.selected_file,
                self.picker.selected_channel_id,
                interaction.channel_id,
                start_at,
                announcement=str(self.announcement).strip() or None,
                display_title=display_title,
                voice_status=status_text,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if self.play_now:
            message = f"Starting **{item_id}** now."
        else:
            timestamp = int(start_at.timestamp())
            message = f"Scheduled **{item_id}** for <t:{timestamp}:F> (<t:{timestamp}:R>)."
        await interaction.response.send_message(message, ephemeral=True)
        await self.picker.finish_selection()


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
            await interaction.response.send_modal(PlaybackModal(self))

        schedule_button.callback = schedule_callback
        self.add_item(schedule_button)

        play_button = discord.ui.Button(
            label="Play now",
            style=discord.ButtonStyle.success,
            disabled=not ready,
            row=2,
        )

        async def play_callback(interaction):
            await interaction.response.send_modal(PlaybackModal(self, play_now=True))

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

    async def finish_selection(self):
        self.stop()
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

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
        self.config.register_guild(timezone="UTC", counter=0, jobs={}, history=[])
        self._starting = set()
        self._play_tasks = set()
        self._locks = {}
        self._active_jobs = {}
        self._stop_requested = set()
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

    async def _probe_duration(self, media):
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            return None
        try:
            process = await asyncio.create_subprocess_exec(
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise
            duration = float(stdout.decode("utf-8", errors="replace").strip())
            return duration if duration > 0 else None
        except (OSError, ValueError, asyncio.TimeoutError):
            log.warning("Could not determine the duration of %s", media)
            return None

    async def create_job(
        self,
        guild,
        filename,
        channel_id,
        text_channel_id,
        start_at,
        *,
        announcement=None,
        display_title=None,
        voice_status=None,
    ):
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
                "announcement": announcement,
                "display_title": display_title or Path(filename).stem,
                "voice_status": voice_status,
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

    async def _record_history(
        self, guild, job, *, status, started_at=None, error=None
    ):
        entry = {
            "id": job["id"],
            "filename": job["filename"],
            "channel_id": job["channel_id"],
            "scheduled_at": job["start_at"],
            "started_at": started_at,
            "finished_at": _utcnow().timestamp(),
            "status": status,
            "error": str(error)[:300] if error else None,
            "announcement": job.get("announcement"),
            "display_title": job.get("display_title"),
            "voice_status": job.get("voice_status"),
        }
        async with self.config.guild(guild).history() as history:
            history.append(entry)
            del history[:-HISTORY_LIMIT]

    def _build_playback_embed(
        self, job, channel, status, *, started_at=None, finished_at=None, duration=None
    ):
        styles = {
            "playing": ("Now playing", discord.Color.blurple()),
            "completed": ("Playback completed", discord.Color.green()),
            "stopped": ("Playback stopped", discord.Color.orange()),
            "failed": ("Playback failed", discord.Color.red()),
        }
        heading, color = styles[status]
        title = job.get("display_title") or Path(job["filename"]).stem
        embed = discord.Embed(title=heading, description=f"**{title}**", color=color)
        embed.add_field(name="Job", value=job["id"], inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        if started_at:
            embed.add_field(
                name="Started", value=f"<t:{int(started_at)}:F>", inline=False
            )
        if duration:
            seconds = max(0, int(duration))
            duration_text = f"{seconds // 60}m {seconds % 60}s"
            embed.add_field(name="Duration", value=duration_text, inline=True)
            if status == "playing" and started_at:
                embed.add_field(
                    name="Expected finish",
                    value=f"<t:{int(started_at + duration)}:R>",
                    inline=True,
                )
        if finished_at:
            embed.add_field(
                name="Finished", value=f"<t:{int(finished_at)}:F>", inline=False
            )
        embed.set_footer(text=job["filename"][:2048])
        return embed

    async def _run_job(self, guild, item_id, job):
        key = (guild.id, item_id)
        lock = self._locks.setdefault(guild.id, asyncio.Lock())
        error = None
        status = "failed"
        failure_reason = None
        started_at = None
        playback_started = False
        connected_by_us = False
        media_duration = None
        now_playing_message = None
        voice_status_set = False
        channel = None
        try:
            if lock.locked():
                failure_reason = "another AudioStream job was active"
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
                media_duration = await self._probe_duration(media)
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
                started_at = _utcnow().timestamp()
                self._active_jobs[guild.id] = item_id
                status_text = job.get("voice_status")
                if isinstance(channel, discord.VoiceChannel) and status_text:
                    try:
                        await channel.edit(
                            status=status_text,
                            reason=f"AudioStream started {item_id}",
                        )
                        voice_status_set = True
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        log.warning(
                            "Could not set the voice status for %s in guild %s: %s",
                            item_id,
                            guild.id,
                            exc,
                        )
                        await self._notify(
                            guild,
                            job,
                            f"**{item_id}** started, but I couldn't set the status for "
                            f"{channel.mention}. Check my Set Voice Channel Status permission.",
                        )
                elif isinstance(channel, discord.StageChannel) and status_text:
                    await self._notify(
                        guild,
                        job,
                        f"**{item_id}** started. Voice-channel statuses aren't available "
                        "for stage channels, so only the now-playing card was posted.",
                    )
                await self._notify(
                    guild,
                    job,
                    f"**{item_id}** is now playing **{job['filename']}** in {channel.mention}.",
                )
                announcement = job.get("announcement")
                try:
                    now_playing_message = await channel.send(
                        content=announcement,
                        embed=self._build_playback_embed(
                            job,
                            channel,
                            "playing",
                            started_at=started_at,
                            duration=media_duration,
                        ),
                    )
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.warning(
                        "Could not post the now-playing card for %s in guild %s: %s",
                        item_id,
                        guild.id,
                        exc,
                    )
                    await self._notify(
                        guild,
                        job,
                        f"**{item_id}** started, but I couldn't post in "
                        f"{channel.mention}. Check my Send Messages and Embed Links permissions there.",
                    )
                await finished.wait()
                if playback_error:
                    raise RuntimeError(str(playback_error[0]))
                if guild.id in self._stop_requested:
                    status = "stopped"
                    await self._notify(
                        guild, job, f"**{item_id}** was stopped during **{job['filename']}**."
                    )
                else:
                    status = "completed"
                    await self._notify(
                        guild, job, f"**{item_id}** finished playing **{job['filename']}**."
                    )
        except asyncio.CancelledError:
            failure_reason = "playback was interrupted while the cog was unloading"
            raise
        except Exception as exc:  # Discord/voice errors vary across supported versions.
            error = exc
            failure_reason = str(exc)
            log.exception("Audio job %s failed in guild %s", item_id, guild.id)
            await self._notify(guild, job, f"**{item_id}** could not play: {exc}")
        finally:
            finished_at = _utcnow().timestamp()
            if now_playing_message is not None and channel is not None:
                actual_duration = (
                    finished_at - started_at if started_at is not None else None
                )
                try:
                    await now_playing_message.edit(
                        embed=self._build_playback_embed(
                            job,
                            channel,
                            status,
                            started_at=started_at,
                            finished_at=finished_at,
                            duration=actual_duration,
                        )
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
            if voice_status_set and isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.edit(
                        status=None,
                        reason=f"AudioStream ended {item_id}",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
            voice = guild.voice_client
            if voice is not None and (playback_started or connected_by_us):
                try:
                    await voice.disconnect(force=True)
                except (discord.ClientException, discord.HTTPException):
                    pass
            try:
                await self._record_history(
                    guild,
                    job,
                    status=status,
                    started_at=started_at,
                    error=failure_reason,
                )
            finally:
                await self._remove_job(guild, item_id)
                self._starting.discard(key)
                self._stop_requested.discard(guild.id)
                if self._active_jobs.get(guild.id) == item_id:
                    self._active_jobs.pop(guild.id, None)
            if error:
                log.info("Removed failed audio job %s", item_id)

    def _job_lines(self, guild, conf):
        lines = []
        for job in sorted(conf["jobs"].values(), key=lambda item: item["start_at"]):
            channel = guild.get_channel(job["channel_id"])
            timestamp = int(job["start_at"])
            title = job.get("display_title") or job["filename"]
            if len(title) > 70:
                title = title[:69] + "…"
            voice_status = job.get("voice_status") or "off"
            if len(voice_status) > 50:
                voice_status = voice_status[:49] + "…"
            lines.append(
                f"**{job['id']}** · `{title}` · "
                f"{channel.mention if channel else 'missing channel'} · <t:{timestamp}:F> · "
                f"status `{voice_status}` · message "
                f"**{'yes' if job.get('announcement') else 'no'}**"
            )
        return lines

    def _history_lines(self, guild, history):
        icons = {"completed": "✅", "stopped": "⏹️", "failed": "⚠️"}
        lines = []
        for entry in reversed(history):
            channel = guild.get_channel(entry.get("channel_id") or 0)
            display_title = (
                entry.get("display_title")
                or entry.get("filename")
                or "Unknown file"
            )
            if len(display_title) > 70:
                display_title = display_title[:69] + "…"
            status = entry.get("status", "failed")
            started_at = entry.get("started_at")
            finished_at = entry.get("finished_at")
            if started_at:
                when = f"<t:{int(started_at)}:f>"
                duration = max(0, int((finished_at or started_at) - started_at))
                elapsed = f"{duration // 60}m {duration % 60}s"
            else:
                when = f"scheduled <t:{int(entry.get('scheduled_at', 0))}:f>"
                elapsed = "not started"
            line = (
                f"{icons.get(status, '•')} **{entry.get('id', 'Unknown')}** · "
                f"**{status.title()}** · `{display_title}` · "
                f"{channel.mention if channel else 'missing channel'} · "
                f"{when} · {elapsed}"
            )
            if entry.get("announcement"):
                announcement = " ".join(entry["announcement"].split())
                line += f"\n↳ Message: {announcement[:180]}"
            if entry.get("error"):
                line += f"\n↳ {entry['error'][:180]}"
            lines.append(line)
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
        heading = "**Scheduled audio**\n"
        visible = []
        current_length = len(heading)
        for line in lines:
            if len(visible) >= 15 or current_length + len(line) + 1 > 1900:
                break
            visible.append(line)
            current_length += len(line) + 1
        if len(lines) > len(visible):
            remainder = f"…and **{len(lines) - len(visible)}** more."
            if current_length + len(remainder) + 1 <= 2000:
                visible.append(remainder)
        await ctx.send(heading + ("\n".join(visible) if visible else "Nothing scheduled."))

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

    @audiostream.command(name="history")
    async def audiostream_history(self, ctx, limit: int = 10):
        """Show recently completed, stopped, and failed playback attempts."""
        if not 1 <= limit <= 20:
            await ctx.send("Choose a history limit between 1 and 20.")
            return
        history = await self.config.guild(ctx.guild).history()
        candidates = self._history_lines(ctx.guild, history)[0:limit]
        if not candidates:
            await ctx.send("AudioStream has no playback history yet.")
            return
        lines = []
        description_length = 0
        for line in candidates:
            added_length = len(line) + (2 if lines else 0)
            if description_length + added_length > 4000:
                break
            lines.append(line)
            description_length += added_length
        embed = discord.Embed(
            title="AudioStream history",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=(
                f"Showing {len(lines)} of {len(history)} retained "
                f"entr{'y' if len(history) == 1 else 'ies'}"
            )
        )
        await ctx.send(embed=embed)

    @audiostream.command(name="stop")
    async def audiostream_stop(self, ctx):
        """Stop the current playback and disconnect the bot."""
        voice = ctx.guild.voice_client
        if (
            ctx.guild.id not in self._active_jobs
            or voice is None
            or not (voice.is_playing() or voice.is_paused())
        ):
            await ctx.send("This server has no active AudioStream playback.")
            return
        self._stop_requested.add(ctx.guild.id)
        voice.stop()
        await ctx.send(
            f"Stopped **{self._active_jobs[ctx.guild.id]}**. It will appear in playback history."
        )

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
            f"FFmpeg: **{'available' if shutil.which('ffmpeg') else 'not found'}**\n"
            f"FFprobe: **{'available' if shutil.which('ffprobe') else 'not found'}**"
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
