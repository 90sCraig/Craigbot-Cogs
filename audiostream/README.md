# AudioStream

AudioStream plays media stored on the bot computer in a Discord voice or stage channel. An administrator chooses the file and channel from Discord, schedules a start time, and the bot disconnects automatically when playback finishes.

This is voice playback, not Discord screen sharing or video broadcasting. FFmpeg extracts and sends the audio track from supported audio and video files.

## Requirements

- FFmpeg must be installed on the same computer as the bot and available on its PATH.
- The Red instance must have voice support (`PyNaCl`).
- The bot needs **View Channel**, **Connect**, **Speak**, **Send Messages**, and **Embed Links** in the destination channel. Give it **Set Voice Channel Status** if you want the selected status shown above the voice channel. On a stage channel it also needs permission to become a speaker, or a moderator must invite it to speak.

## Setup

The bot owner sets the only folder AudioStream is allowed to read:

```text
[p]audiostreamset folder C:\Media\Radio
```

Subfolders are included. Supported files are AAC, FLAC, M4A, MKV, MOV, MP3, MP4, OGG, Opus, WAV, WebM, and WMA.

Set each server's scheduling timezone if UTC is not appropriate:

```text
[p]audiostreamserverset timezone America/New_York
```

## Scheduling playback

Run `[p]audiostream` (or `[p]localstream`) and use the interactive controls:

1. Select a local media file.
2. Select a voice or stage channel.
3. Choose **Play now** or **Choose start time**.
4. Set the now-playing title.
5. Set the voice-channel status, leave it blank to use `Now playing: <title>`, or enter `off` to disable it for this stream.
6. Optionally enter a message to post in the voice channel's text chat when playback starts.
7. For scheduled playback, enter `YYYY-MM-DD HH:MM`, `in 10m`, `in 2h`, or `now`.

Scheduled jobs survive bot restarts. If the bot restarts during playback, that playback cannot resume from its previous position.

AudioStream retains the 100 most recent playback results per server. History records the file, voice channel, optional chat message, actual start and finish times, duration, and whether playback completed, was stopped, or failed.

When playback begins, AudioStream posts a now-playing card with the chosen title, job ID, start time, media duration, and expected finish time when FFprobe can read it. The same card is updated to Completed, Stopped, or Failed at the end. A custom voice-channel status is cleared automatically when playback ends. Voice-channel statuses are not available on stage channels, but their now-playing cards still work.

## Commands

| Command | Who | Purpose |
| --- | --- | --- |
| `[p]audiostream` | Admin | Open the file/channel/time picker. |
| `[p]audiostream list` | Admin | List queued or active jobs. |
| `[p]audiostream cancel <ID>` | Admin | Cancel a job that has not started. |
| `[p]audiostream stop` | Admin | Stop current playback and disconnect. |
| `[p]audiostream history [1-20]` | Admin | Show recent playback history, newest first. |
| `[p]audiostreamserverset timezone <zone>` | Admin | Set the server's IANA timezone. |
| `[p]audiostreamset folder <path>` | Bot owner | Set the permitted local media folder. |
| `[p]audiostreamset show` | Bot owner | Check the folder, file count, and FFmpeg availability. |

Only one file can play in a server at a time. If two jobs overlap, the later job reports the conflict and is removed rather than interrupting the first.
