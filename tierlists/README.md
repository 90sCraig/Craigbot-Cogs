# TierLists

This is the cog guide for the 'TierLists' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update tierlists`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Create community-driven tier lists in your server. Admins set up a **category** (e.g. "Best Pizza Topping") and add **options** to it. The bot posts a pinned voting message with a dropdown; members upvote or downvote the options, and the bot automatically sorts them into tiers (**S, A, B, C, D, E, F**) based on the percentage of upvotes each one receives. Great for ranking games, movies, foods — anything your community wants to argue about.

## How it works

1. **An admin creates a category** in a channel with `[p]tlset category create`. The bot posts a pinned embed there with a **"Select choice to vote for"** dropdown.
2. **The admin adds options** to the category with `[p]tlset category option add`. The voting message updates to include them.
3. **Members vote** by opening the dropdown on the pinned message and picking an option:
   - A private prompt appears with **Upvote** / **Downvote** buttons.
   - If they've already voted on that option, they instead get **Change Vote** / **Remove Vote**.
   - Each member can cast a limited number of upvotes and downvotes per category (default **3** each — configurable).
4. **The bot ranks the options** into tiers automatically and updates the embed live after every vote. Options are placed by the percentage of upvotes they hold, against the configured percentile thresholds.

> **Permissions:** Setup commands require the **admin** role (set via Red's `[p]set addadminrole`) or, for the settings, the **Manage Server** permission. The bot needs **Send Messages**, **Embed Links**, and **Manage Messages** (to pin the voting message) in the category's channel.

## Quick start

```
[p]tlset category create pizza #polls Vote for the best pizza topping!
[p]tlset category option add pizza Pepperoni
[p]tlset category option add pizza Pineapple
[p]tlset category option add pizza Mushroom
```

Members can now vote from the pinned message in `#polls`. Adjust how strict the tiers are with `[p]tlset setpercentiles`, and the per-user vote limits with `[p]tlset setmaxvotes`.

## Commands

All setup commands live under `[p]tierlistset` (alias `[p]tlset`).

### `tierlistset`
The base command for managing tier list settings. **Alias:** `tlset`

#### `tierlistset setpercentiles <tier> <value>`
Set the minimum upvote percentile required for a tier. **Alias:** `setp`

- `tier` — one of `S`, `A`, `B`, `C`, `D`, `E` (anything below `E` falls into `F`).
- `value` — the percentile threshold (0–100).

Defaults: **S = 90, A = 70, B = 50, C = 30, D = 25, E = 10**.

```
[p]tlset setpercentiles S 95
```

#### `tierlistset setmaxvotes <vote_type> <value>`
Set how many votes each member may cast per category. **Alias:** `setmv`

- `vote_type` — `upvotes` or `downvotes`.
- `value` — the maximum allowed (default **3** each).

```
[p]tlset setmaxvotes upvotes 5
```

#### `tierlistset showsettings`
Show the current settings (percentiles, vote limits, and categories). **Aliases:** `ss`, `show`, `settings`

### Category management — `tierlistset category`
Manage tier list categories. **Alias:** `cat`

#### `category list`
List every category with its choices.

#### `category create <name> [channel] [description]`
Create a category and post its pinned voting message. Defaults to the current channel if none is given. **Aliases:** `add`, `+`, `new`

```
[p]tlset category create games #tierlist The best games of all time
```

#### `category delete <name>`
Delete a category and remove its voting message. **Aliases:** `remove`, `-`, `del`

#### `category updatemessage <name>`
Re-post or refresh a category's voting message (useful if it was deleted or got out of sync). **Aliases:** `update`, `refresh`

### Editing a category — `tierlistset category edit`

#### `category edit channel <name> <channel>`
Move a category's voting message to a different channel. **Alias:** `chan`

#### `category edit description <name> <description>`
Change a category's description. **Alias:** `desc`

#### `category edit name <name> <new_name>`
Rename a category. **Alias:** `rename`

### Managing options — `tierlistset category option`
Manage the choices inside a category. **Aliases:** `opt`, `options`, `choices`, `choice`

#### `category option add <category> <option>`
Add a votable option to a category. **Aliases:** `+`, `new`

#### `category option remove <category> <option_index>`
Remove an option by its index. **Aliases:** `del`, `-`

#### `category option forceadd <category> <option>`
Add an option even if it looks similar to an existing one (bypasses the duplicate check). **Aliases:** `force`, `addforce`

#### `category option clear <category>`
Remove all options from a category. **Alias:** `reset`

## Installation

If you haven't added this repository before, let's add it first. We'll call it "Craigbot-Cogs" here.

```bash
[p]repo add Craigbot-Cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-Cogs tierlists
[p]load tierlists
```

## Further Support

- Join the [Craigbot Support Discord server](https://discord.gg/7ympDwSEqA) for direct assistance.
- Open an issue or pull request on the [Craigbot-Cogs GitHub repository](https://github.com/90sCraig/Craigbot-Cogs) if you encounter any issues or have suggestions for improvements.

## Credit

This cog is a fork of the original [Tierlists cog](https://github.com/i-am-zaidali/bounty-cogs/tree/main) by [i-am-zaidali](https://github.com/i-am-zaidali).
