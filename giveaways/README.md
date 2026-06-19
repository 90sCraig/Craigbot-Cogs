# Giveaways

This is the cog guide for the 'Giveaways' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update giveaways`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Manage giveaways in your Discord server. Members enter by clicking a button on the giveaway message, and the bot automatically draws winners when the timer ends. Features include adjustable duration, multiple winners, role restrictions and multipliers, entry requirements (account/server age, credit cost), custom embeds, and several third-party integrations. Great for community events and prize drawings.

> **Permissions:** All giveaway commands require the **Manage Server** permission. The bot needs **Add Reactions** and **Embed Links** in the target channel. Giveaways are checked every 20 seconds, so they may end up running slightly longer than the specified duration.

## Commands

All commands are subcommands of `[p]giveaway` (alias `[p]gw`).

### `giveaway start`
Start a simple giveaway. Optionally pass a channel first; otherwise the current channel is used. Time accepts formats like `1h`, `30m`, or `1d` (a bare number defaults to minutes). By default the winner is DMed, and users who can't enter are DMed the reason.

```
[p]giveaway start 1h Awesome Prize
[p]giveaway start #giveaways 2d A Steam key
```

### `giveaway advanced`
Create a fully customized giveaway using `--flag` arguments. Run `[p]gw explain` for the complete, up-to-date list of flags.

```
[p]gw advanced --prize A new sword --duration 1h30m --winners 3 --multiplier 2 --multi-roles @Booster
```

**Alias:** `adv`

**Common flags:**

| Flag | Meaning |
| --- | --- |
| `--prize` | The prize (required). |
| `--duration` | How long it runs, e.g. `2d3h30m`. *(Use this **or** `--end`.)* |
| `--end` | Absolute end time, e.g. `tomorrow at 3am`, `in 4 hours`. Defaults to UTC. |
| `--channel` | Channel to post in (defaults to the current channel). |
| `--winners` | Number of winners to draw. |
| `--emoji` | Emoji used for the giveaway. |
| `--roles` | Restrict entry to these roles. |
| `--multiplier` / `--multi-roles` | Extra entries for the given roles. |
| `--cost` | Credits required to enter. |
| `--joined` / `--created` | Minimum days in the server / on Discord to enter. |
| `--blacklist` | Roles that cannot enter. |
| `--description`, `--image`, `--thumbnail`, `--colour` | Customize the embed. |
| `--button-text`, `--button-style` | Customize the entry button. |
| `--congratulate`, `--notify`, `--multientry`, `--announce` | Behaviour toggles. |

See `[p]gw explain` for the full list and `[p]gw integrations` for third-party level/economy integrations.

### `giveaway end`
End a running giveaway early and draw the winner(s) immediately.

```
[p]giveaway end <message_id>
```

### `giveaway reroll`
Draw a new winner for a giveaway that has already ended.

```
[p]giveaway reroll <message_id>
```

### `giveaway edit`
Edit a running giveaway's settings using the same `--flag` arguments as `advanced`. Editing resets the end time based on the new duration.

```
[p]giveaway edit <message_id> --prize A better prize --duration 2h
```

### `giveaway entrants`
List everyone who has entered a running giveaway, with their entry counts.

```
[p]giveaway entrants <message_id>
```

### `giveaway info`
Show details about a running giveaway (entrant count, end time, and its configured settings).

```
[p]giveaway info <message_id>
```

### `giveaway list`
List all giveaways currently running in the server, each linking to its message.

```
[p]giveaway list
```

### `giveaway explain`
Show the full explanation of `giveaway advanced` and every argument it supports.

```
[p]giveaway explain
```

### `giveaway integrations`
Show the available third-party integrations (e.g. Fixator's leveler level/rep requirements, Tatsumaki levels) and the flags that enable them.

```
[p]giveaway integrations
```

## Installation

If you haven't added this repository before, run the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs giveaways
[p]load giveaways
```

## Credit

This cog is a fork of the original Giveaways cog by [flaree](https://github.com/flaree/flare-cogs).
