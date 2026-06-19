# CaseFiles

This is the cog guide for the 'CaseFiles' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update casefiles`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Crowdsource the gaps in your tape archive. A **cold case** is an unidentified tape. You feed the bot a batch of images; it serves them to a case channel **one at a time**; your community (the detectives) reply with leads; a detective confirms the ID; and the bot **advances to the next case** — banking each solve so you can export it and merge it back into your [Obsidian](https://obsidian.md/) vault.

**Decoupled by design:** the bot never touches your vault. Images come *in* over Discord, and solved cases go *out* as a file you review and import. Nothing is written to your notes automatically.

## How the loop works

```
   Your vault (blank tapes)
            │  export images
            ▼
   [ intake channel ]  ──ingest──▶  queue  ──serve──▶  [ case channel ]
                                                              │  detectives reply with leads
                                                              ▼
                                                          [p]case solve
                                                              │  credits + advances
                                                              ▼
                                              solved (banked)  ──[p]case export──▶  Obsidian-ready file
                                                                                          │
                                                                                  you review & merge
```

1. **Get images to the bot.** Drag a batch of tape photos into your **intake channel** (no hosting needed), then run `[p]case ingest`. The bot downloads and stores each one as a cold case. *(You can also `[p]case add` a single image, or `[p]case import` a JSON manifest.)*
2. **Serve the queue.** `[p]case start` posts the first cold case to your **case channel** — the image plus any details you already know.
3. **Collect leads.** Members reply with anything they can ID — distributor, catalog number, year, cover details. The bot quietly logs each reply (🔍) onto the case.
4. **Crack it.** A detective runs `[p]case solve title=… distributor=… @whoever-cracked-it`. The bot records the answer, credits the detectives, and automatically serves the next cold case.
5. **Export & merge.** `[p]case export` hands you an Obsidian-ready Markdown file (one note per solve, with frontmatter and the collected leads). Review it, drop it into your vault, then `[p]case clearsolved`.

## Setup

```
[p]case set channel #cold-cases     # where cases are served & leads collected
[p]case set intake #tape-intake     # private channel to drop raw images into
[p]case set role @Detective         # who can run/solve cases (optional)
[p]case set show
```

> **Permissions & intents:** the bot needs **Embed Links** and **Attach Files** in the case channel, **Read Message History** in the intake channel, and the **Message Content** intent (so it can read replies as leads). Running and solving cases is limited to the **Detective** role, or anyone with **Manage Server** if no role is set.

## Getting images in

| Method | Best for | How |
| --- | --- | --- |
| **Intake channel** | A backlog of local vault images | Drag photos into the intake channel, then `[p]case ingest [limit]`. Already-ingested images are skipped. |
| **Add one** | One-offs spotted on stream | `[p]case add` with an image attached (optionally with known fields). |
| **JSON manifest** | Bulk, when images are already hosted | `[p]case import` with a `.json` attachment (see below). |

**Manifest format** — a JSON list; every field is optional:

```json
[
  { "id": "0481", "image_url": "https://…/0481.jpg", "distributor": "Vestron", "year": "1987" },
  { "image_url": "https://…/0482.jpg" }
]
```

## Member commands

### `case current`
Re-show the active cold case. **Alias:** `show`

### `case leads [case_id]`
Show the leads collected for the active case (or a specific id).

### `case detectives`
Show the detective leaderboard — who's cracked the most cases. **Aliases:** `leaderboard`, `lb`

> Replying in the case channel is all a detective needs to do to contribute a lead — no command required.

## Detective / mod commands

These require the **Detective** role or **Manage Server**.

### `case start`
Serve the next cold case. Begins the queue, or moves it along. **Alias when advancing:** `case next` (sends the current case to the back of the queue and serves the next).

### `case solve [fields] [@detectives]`
Confirm the ID for the active case, credit whoever cracked it, and advance.

```
[p]case solve title=Blood Diner distributor=Vestron catalog=VA-5023 year=1987 @Craig @Dave
```

Recognized fields: `title`, `distributor`, `catalog`, `year`, `notes` (a title is required). Any members you @mention are credited with the solve.

### `case skip [reason]`
Shelve the active case (still unidentified) and advance to the next.

### `case add [fields]`
Add one cold case from an attached image. Attach a tape photo; optionally pass known details like `distributor=Vestron year=1987`.

### `case ingest [limit]`
Harvest images from the intake channel into the queue (default scans the last 25 messages).

### `case import`
Bulk-add cases from an attached JSON manifest (see [format](#getting-images-in) above).

### `case queue`
Show how many cases are queued, solved, and shelved, plus what's up next.

### `case export [md|json]`
Export solved cases as a file to import into your vault. `md` (default) gives Obsidian-ready notes; `json` gives a manifest.

### `case clearsolved`
Remove exported (solved) cases from storage. Asks for confirmation first — export before you clear.

## Admin settings — `case set`

| Command | What it does |
| --- | --- |
| `channel [#channel]` | Where cases are served and leads collected. |
| `intake [#channel]` | Where you drop raw tape images for `ingest`. |
| `role [@role]` | The Detective role allowed to run/solve cases (omit to clear). |
| `autoadvance <on/off>` | Automatically serve the next case after a solve/skip (default on). |
| `captureall <on/off>` | Log every case-channel message as a lead, or only direct replies (default on). |
| `show` | Show the current settings. **Alias:** `settings` |

## Data & privacy

This cog stores Discord user IDs alongside the **leads** (message text) members post in the case channel, and a count of cases each member has helped solve. Submitted **tape images** are stored in the cog's own data folder (not your vault). No vault files are ever read or written. A user's leads and solve credit are removed on a Red data-deletion request, and solved cases (with their images) are removed when you run `[p]case clearsolved`.

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs casefiles
[p]load casefiles
```

## Tip: pairs well with…

- **MovieDB** — once a case is solved, `[p]movie <title>` pulls the poster and details to enrich the note.
- **Community** — case solves are a natural thing to celebrate in the monthly recap.
