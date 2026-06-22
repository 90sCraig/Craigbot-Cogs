# PuttTracker

This is the cog guide for the 'PuttTracker' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update putttracker`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Automatically tracks [putt.day](https://putt.day) scores posted in your server and maintains **daily**, **weekly**, and **all-time** leaderboards.

When a member posts their daily putt.day result, the bot detects it, records the score, reacts with ⛳ to confirm it was logged, and replies with that day's updated leaderboard (this auto-reply can be turned off with `[p]putt set autoboard off`). No commands are needed to record a score — just paste the result. Leaderboards are ranked by **average relative to par** (lower is better).

Each day can only be logged **once per member**. If someone posts the same putt.day result again — even in a later week — it is ignored and the bot reacts with 🔁 instead of ⛳, so scores can't be accidentally counted twice.

Leaderboards are shown as a 🥇🥈🥉 podium above an aligned monospace table, sorted by average relative to par (lower is better). For example:

> ⛳ **Weekly Leaderboard — 2026-W25**
> 🥇 **Craig**   🥈 **Dave**   🥉 **Sam**
> ```
> #  Player          Rounds  Total    Avg
> 1  Craig                5     -3   -0.6
> 2  Dave                 5     +2   +0.4
> 3  Sam                  4     +8   +2.0
> 4  Pat*                 3    +15   +5.0
> ```
> \* = used a restart

Columns are **Rounds**, **Total** (total relative to par) and **Avg** (average per round). The daily board uses the same layout with **Score** (strokes/par) and **+/-** columns instead.

### How scores are detected

The bot looks for the putt.day share line anywhere in a message:

```
putt.day #36 ⛳ 20/6 +14
putt.day #37 ⛳ 10/9 Bogey
```

| Part      | Meaning                      | Example |
| --------- | ---------------------------- | ------- |
| `#36`     | putt.day day number          | 36      |
| `20/6`    | strokes / par                | 20 / 6  |

Only the day number and **strokes/par** are read. The score relative to par is computed as `strokes − par`, so it works whether putt.day shows a number (`+14`) or a golf term (`Par`, `Bogey`, `Birdie`, …). The flag glyph between the day number and the score is ignored, so a different emoji won't break detection.

**Restarts:** if a post includes a restart count (e.g. `… +15 · 1 restart`), that round is flagged with an asterisk (`*`) wherever it appears, since clean no-restart rounds are the goal. On weekly/all-time boards a player's name is asterisked if any of their counted rounds used a restart. A short `* = used a restart` legend is added when relevant.

Notes:
- Each member's score for a given day is recorded **once, ever** — reposting the same day (in any week) is ignored, so totals can't be inflated. The bot reacts 🔁 on an ignored repost.
- Scores are tracked **per server**. Each guild has its own independent leaderboard.
- Weeks are grouped by ISO week (e.g. `2026-W25`), using the server's configured timezone (see [Timezone](#timezone) — defaults to UTC).
- The day a score belongs to comes from the putt.day number in the post (e.g. `#36`), not from when the message was sent. "Today" is the latest day number recorded; "yesterday" is the one before it.
- Leaderboards are sent as embeds when the bot has the **Embed Links** permission; otherwise it falls back to formatted text automatically.

## Commands

All commands are subcommands of `[p]putt` and can only be used in a server.

### `putt`
Show the help menu for the score tracker.

```
[p]putt
```

### `putt daily`
Show the leaderboard for the latest putt.day puzzle (by its `#` day number). Pass `yesterday` to see the day before instead.

**Aliases:** `today`, `d`

```
[p]putt daily            # today
[p]putt daily yesterday  # the previous day
```

### `putt weekly`
Show the weekly leaderboard. Defaults to the current week. Pass a negative offset to view past weeks.

**Aliases:** `week`, `w`

```
[p]putt weekly        # current week
[p]putt weekly -1     # last week
[p]putt weekly -2     # two weeks ago
```

### `putt overall`
Show the all-time leaderboard, aggregated across every recorded week.

**Aliases:** `alltime`, `o`

```
[p]putt overall
```

### `putt myscore`
Show your own recorded scores across all weeks, with your total and average.

**Aliases:** `me`, `m`

```
[p]putt myscore
```

## Admin commands

These require the admin role or the **Manage Server** permission.

### `putt addscore`
Add or correct a member's score for a day. Relative-to-par is computed automatically (`strokes - par`). An optional final number records restarts (defaults to 0). If the day already exists for that member it is updated; otherwise it is added.

```
[p]putt addscore @Craig 36 20 6      # no restarts
[p]putt addscore @Craig 37 24 9 1    # 1 restart (flagged with *)
```

**Aliases:** `setscore`

### `putt removescore`
Remove a member's score for a specific day (and adjust their totals).

```
[p]putt removescore @Craig 36
```

**Aliases:** `delscore`, `rmscore`

### `putt reset`
Permanently delete **all** putt.day scores for the current server. Shows **Confirm / Cancel** buttons before deleting.

```
[p]putt reset
```

## Reminders & announcements

PuttTracker can post a daily reminder to play and announce last week's winner. All settings are per server and configured under `[p]putt set` (admin / Manage Server only). Set a channel first:

```
[p]putt set timezone eastern       # timezone the leaderboard WEEK follows (see below)
[p]putt set autoboard on           # reply with the day's leaderboard on each new score
[p]putt set channel #putt-day      # where reminders/announcements are posted
[p]putt set reminder on            # enable the daily reminder
[p]putt set time 13:30             # reminder time, 24-hour UTC
[p]putt set message Time to putt!  # customise the reminder text
[p]putt set weekly on              # announce last week's winner when a new week starts
[p]putt set weeklytime 09:00       # weekly announcement time, 24-hour UTC
[p]putt set show                   # view current settings
```

### Timezone

By default the weekly leaderboard groups scores by **UTC** ISO week, which means the week rolls over at midnight UTC — i.e. on **Sunday evening** for the Americas, splitting a single day's scores across two weeks. Set your community's timezone so the week rolls over at your local Sunday→Monday midnight instead:

```
[p]putt set timezone America/New_York   # or a shortcut: eastern / central / mountain / pacific
```

Accepts any IANA timezone name. When you change it, **existing scores are automatically re-filed** into the correct weeks (each score remembers when it was posted), so nothing is lost. Only the **weekly** view and weekly announcement are affected — daily and all-time leaderboards are unchanged.

Notes:
- **Reminder/announcement times** (`set time`, `set weeklytime`) are always in **UTC**; only the leaderboard *week boundary* follows `set timezone`. The daily reminder fires once per day at or after the set time.
- The daily reminder automatically includes a link to <https://putt.day> after your message text.
- The weekly announcement posts once at the start of a new ISO week (Monday), at or after the configured weekly time, showing the previous week's leaderboard.
- If a feature is enabled without a channel set, nothing is posted until you set one.

## Data & privacy

This cog stores Discord user IDs and putt.day scores (strokes, par, relative to par) per server. No other personal data is collected. A user's data is automatically removed when Red's data-deletion request is processed (`[p]mydata` / owner data deletion).

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs putttracker
[p]load putttracker
```

Once loaded, members can simply post their putt.day results and the bot will start tracking automatically.
