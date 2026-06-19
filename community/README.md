# Community

This is the cog guide for the 'Community' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update community`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

A gentle, peer-driven recognition system — built as the **opposite of a grindy leveling bot**. There's no per-message XP, no "LEVEL UP!" spam, and no public "you're inactive" callouts. Instead, the bot stays quiet and lets your members do the recognizing:

- **⭐ The Fridge** — members react to great messages; standout moments are saved.
- **🙌 High Fives** — members thank each other; gratitude is counted, never announced.
- **👋 Regulars** — quiet, low-key presence tracking (active days, *not* message counts).

Day to day the bot only adds a small reaction to acknowledge these. Then, once a month, it posts a single warm **Recap** that celebrates everything together — like a community newsletter rather than a slot machine.

> **Designed for a calmer crowd:** plain language, no jargon, no streaks or FOMO, and every feature can be turned off. By default the cog is **whisper-quiet** — it never posts in chat except for the monthly recap.

## How it works

### ⭐ The Fridge (starboard)
When members react to a message with ⭐ (configurable) and it reaches the threshold (default **4**), the bot quietly marks it as a "moment of the month." By default it just adds a small ✨ to the message — **no repost, no ping**. The best moments appear in the monthly Recap. (If you'd rather have a live starboard channel, you can turn one on — see [`livefridge`](#community-set-livefridge).)

- You can't star your own message for credit, and bot messages don't count.
- Removing your ⭐ removes your vote.
- Ignored channels (e.g. spam/bot channels) are excluded.

### 🙌 High Fives (reputation)
Members thank each other in three natural ways:
- **React** to a message with 🙌 (configurable) — thanks that message's author.
- **Say it** — a message like `thanks @Dave` or `@Sam kudos` is credited automatically.
- **Command it** — `[p]community thank @user`.

The bot confirms with a tiny 🙏 reaction rather than a message. High fives are **rate-limited** so they stay meaningful: you can't thank yourself, there's a daily limit per giver (default **5**), and a cooldown before re-thanking the same person (default **12h**).

### 👋 Regulars (activity)
The bot quietly notes the *days* each member is active — never message counts, never XP. At month's end, anyone active on enough distinct days (default **5**) is recognized as a "regular." This celebrates belonging, not competition — there are no ranks and no losers.

### 📰 The monthly Recap
Once a month (default the **1st at 10:00 UTC**) the bot posts one roundup to your recap channel:

> 📰 **The June 2026 Recap**
> ⭐ **Moments of the month**
> 🥇 **Craig** · 12 ⭐ — [jump](#)
> 🙌 **Most appreciated**
> 🥇 **Dave** · 7 high fives
> 👋 **This month's regulars**
> **Craig**, **Dave**, **Sam** and 6 others

If nothing happened last month, the bot stays silent rather than posting an empty recap.

## Quick start

The cog works immediately, but to get the monthly recap you only need to set a channel:

```
[p]community set recapchannel #general
[p]community set show
```

That's it — members can start starring messages and thanking each other right away.

## Member commands

All commands live under `[p]community` (alias `[p]comm`).

### `community thank <member> [reason]`
Give someone a high five. **Aliases:** `props`, `kudos`, `highfive`, `hf`

```
[p]community thank @Dave for the great advice
```

### `community standing [member]`
See how many high fives you (or someone else) have received this month and all-time. **Aliases:** `myprops`, `highfives`

```
[p]community standing
[p]community standing @Dave
```

### `community highlights`
Show this month's most-starred moments so far. **Aliases:** `fridge`, `moments`

### `community regulars`
Show who's been a regular this month.

### `community recap [this|last]`
Preview the recap for the current or previous month (`last` by default).

```
[p]community recap
[p]community recap this
```

## Admin commands

These require the **admin** role or the **Manage Server** permission, under `[p]community set`.

| Command | What it does |
| --- | --- |
| `enable <on/off>` | Turn the whole cog on or off for this server. |
| `staremoji <emoji>` | Set the nomination emoji (default ⭐). |
| `starthreshold <n>` | Reactions needed to count as a moment (default 4). |
| `starack <on/off>` | Toggle the small ✨ the bot adds when a moment qualifies. |
| <a id="community-set-livefridge"></a>`livefridge <on/off> [#channel]` | Optionally repost moments live to a fridge channel (off by default). |
| `ignore <#channel>` | Toggle a channel as ignored (excluded from stars + activity). |
| `props <on/off>` | Turn high fives on or off. |
| `propsemoji <emoji>` | Set the high-five reaction emoji (default 🙌). |
| `propstext <on/off>` | Toggle crediting "thanks @user" style messages. |
| `propslimit <n>` | High fives a member can give per day (default 5). |
| `propscooldown <hours>` | Cooldown before re-thanking the same person (default 12). |
| `regulars <on/off>` | Turn quiet activity tracking on or off. |
| `regularmindays <n>` | Active days per month to count as a regular (default 5). |
| `recap <on/off>` | Turn the monthly recap on or off. |
| `recapchannel [#channel]` | Where the recap posts (omit to clear). |
| `recapday <1-28>` | Day of the month the recap posts (default 1). |
| `recaptime <HH:MM>` | Recap time in 24-hour UTC (default 10:00). |
| `postrecap [this\|last]` | Post a recap right now (handy for testing). |
| `show` | Show all current settings. **Alias:** `settings` |

> **Times are in UTC.** The recap fires once on or after the configured day and time each month.

## Data & privacy

This cog stores Discord user IDs alongside recognition data: message IDs and ⭐ counts for starred messages, high-five counts, and the calendar **dates** a member was active. **No message content is stored.** Data older than ~6 months is pruned automatically, and a user's data is removed on a Red data-deletion request (`[p]mydata` / owner data deletion).

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs community
[p]load community
```

Once loaded it runs quietly. Set a recap channel with `[p]community set recapchannel #channel` to get the monthly roundup.
