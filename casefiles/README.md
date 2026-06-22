# CaseFiles — VHS Detectives

This is the cog guide for the 'CaseFiles' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update casefiles`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

A community-engagement bot for a VHS tape archive. It turns two solo bottlenecks — reading bad handwriting on mystery tapes, and post-stream research — into community detective work.

**One case is live at a time** in a single case channel. The admin opens a case, the community replies right there, and the admin **stamps** good messages with an emoji to confirm them. A stamp is the one action that drives everything: it **awards the author points**, **records a Confirmed Finding** on the case card, and **bumps their rank**. Nothing counts until it's stamped — that's the anti-spam and the reward in one.

No threads, no commands for detectives — just talk in the channel. Opening the next case archives the current one and the channel moves on.

> **This is v1 (the Discord loop).** Rank *roles*, writing findings back to the Obsidian/Gitea archive, and the monthly "Top Detective" shoutout are planned follow-ups and are **not** in this version yet.

## How the loop works

1. **Open a case.** The admin runs `/case mystery` (a tape that's never been streamed) or `/case stream` (post-stream research). The bot posts a **case card** to the case channel and **pins** it.
2. **Detectives reply** in the channel — reading the label, calling the content, answering the open questions. No command needed.
3. **The admin stamps** a good reply by reacting to it with a stamp emoji:

   | Emoji | Meaning | Points |
   | --- | --- | --- |
   | 💡 | Helpful lead | +1 |
   | 🔍 | Solid solve | +3 |
   | 🏆 | Cracked a stumper | +5 |

   The bot awards the points, adds the finding to the card, and posts a one-line congrats if the author hits a new rank.
4. **Move on.** Opening the next case archives the current one (its card stays as a record). Use `/case close` to archive without opening a new one.

Stamping is **idempotent** (re-adding the same emoji does nothing), reactions from non-admins are ignored, and you can't stamp the bot, the case card, or your own message. Removing your stamp — or deleting a stamped message — **reverses** the points and the finding automatically.

## Setup

```
[p]caseset channel #the-evidence-room   # the single channel cases live in
[p]caseset adminrole @Curator           # optional: who can stamp (else Manage Server)
[p]caseset show
```

> **Permissions & intents:** the bot needs **Manage Messages** (to pin the active case), **Embed Links**, **Add Reactions**, and the **Message Content** intent in the case channel. Only members with **Manage Server** (or the configured stamp role) can stamp or open cases.

## Commands

### Admin
- `/case mystery image:<photo> guess:<text?>` — open a mystery case. `guess` is an optional machine/AI transcription for detectives to push against.
- `/case stream image:<photo> tape_id:<text> title:<text> questions:<text>` — open a post-stream case. `questions` (2–3 seeded unknowns) is required and is the biggest driver of good discussion.
- `/case close` — archive the current case.
- `/case rescan` — re-read reactions on the active case and reconcile any stamps made while the bot was offline (Discord doesn't replay those).
- `[p]caseset channel|adminrole|show` — configuration.

### Everyone
- `/case status` — reprint the current case card and its confirmed findings (handy once it's scrolled off).
- `/rank` — privately show your points, current rank, and points to the next rank.

> Slash commands may need a one-time `[p]slash sync` after install.

## Ranks

Points are cumulative and permanent. Default thresholds (configurable later):

| Rank | Points |
| --- | --- |
| Tape Spotter | 1 |
| Label Reader | 5 |
| Case Cracker | 15 |
| Field Archivist | 35 |
| Senior Investigator | 70 |
| Cold Case Closer | 125 |

In v1 ranks are shown via `/rank` and a congrats line when you cross one. (Assigning a coloured **Discord role** per rank is a planned follow-up.)

## Data & privacy

This cog stores Discord user IDs alongside the **content of messages the admin stamps** as confirmed findings, plus each user's points and rank. Submitted **tape images** are stored in the cog's own data folder — **no archive/vault files are read or written in v1**. A user's stamped contributions are removed on a Red data-deletion request.

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs casefiles
[p]load casefiles
```
