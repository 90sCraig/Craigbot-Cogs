# PuttTracker

This is the cog guide for the 'PuttTracker' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update putttracker`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Automatically tracks [putt.day](https://putt.day) scores posted in your server and maintains **weekly** and **all-time** leaderboards.

When a member posts their daily putt.day result, the bot detects it, records the score, and reacts with ⛳ to confirm it was logged. No commands are needed to record a score — just paste the result. Leaderboards are ranked by **average relative to par** (lower is better).

### How scores are detected

The bot looks for the standard putt.day share format anywhere in a message:

```
putt.day #36 ⛳ 20/6 +14
```

| Part      | Meaning                      | Example |
| --------- | ---------------------------- | ------- |
| `#36`     | putt.day day number          | 36      |
| `20/6`    | strokes / par                | 20 / 6  |
| `+14`     | score relative to par        | +14     |

Notes:
- Each member's score for a given day is recorded **once** — reposting the same day is ignored, so totals can't be inflated.
- Scores are tracked **per server**. Each guild has its own independent leaderboard.
- Weeks are grouped by ISO week (e.g. `2026-W25`).

## Commands

All commands are subcommands of `[p]putt` and can only be used in a server.

### `putt`
Show the help menu for the score tracker.

```
[p]putt
```

### `putt daily`
Show today's leaderboard for the day's putt.day puzzle. Pass `yesterday` to see the previous day instead.

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
