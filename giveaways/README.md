# Giveaways

This is the cog guide for the 'Giveaways' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update giveaways`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).
> This documentation is auto-generated every time this cog receives an update.

## About this cog

Manage giveaways in your Discord server. Features include adjustable duration, automatic winner selection, multipliers, role restrictions, and more. Great for community events and prize drawings.

## Commands

### `giveaway start`
Start a giveaway in the current channel. You can specify a duration and prize, for example:

```
[p]giveaway start 1h Awesome Prize
```

### `giveaway reroll`
Pick a new winner for a finished giveaway.

```
[p]giveaway reroll <message_id>
```

### `giveaway end`
End a running giveaway early.

```
[p]giveaway end <message_id>
```

### `giveaway advanced`
Create a giveaway with advanced settings like custom emoji, images, or multiple winners.

```
[p]giveaway advanced prize="Big Prize" duration=1d winners=3
```

## Installation

If you haven't added this repository before, run the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs giveaways
[p]load giveaways
```

