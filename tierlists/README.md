# TierLists

This is the cog guide for the 'TierLists' cog. This guide contains the collection of commands which you can use in the cog. Through this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**  
> Ensure that you are up to date by running `[p]cog update tierlists`.  
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).  
> This documentation is auto-generated every time this cog receives an update.

## About this cog

A cog to manage tier lists within your Discord server. Users can vote on items in various categories, and the items are ranked by tiers divided by percentiles based on up/down votes. This cog is ideal for creating community-driven rankings, such as favorite movies, games, or anything else that can be categorized.

## Quick Start

Below is a short example showing how to create a simple tier list. This assumes
you already have a channel where the voting message will be posted.

```bash
[p]tierlistset category create Movies #tierlists "Top movies of the 90s"
[p]tierlistset category option add Movies "The Matrix"
[p]tierlistset category option add Movies "Jurassic Park"
[p]tierlistset category updatemessage Movies
```

Once created, members can vote on each option to help determine the final tier
ranking.

## Commands

Here are all the commands included in this cog:

### `tierlistset`

- **Description**: The base command for managing tier list settings.
- **Usage**: `[p]tierlistset` or `[p]tlset`
- **Aliases**: `tlset`

#### `setpercentiles`

- **Description**: Set the percentile value for a specific tier.
- **Usage**: `[p]tierlistset setpercentiles <tier> <value>`
- **Aliases**: `setp`
- **Parameters**:
  - `tier`: The tier to set the percentile for (S, A, B, C, D, E).
  - `value`: The percentile value to assign to the tier.

#### `setmaxvotes`

- **Description**: Set the maximum number of votes a user can cast.
- **Usage**: `[p]tierlistset setmaxvotes <vote_type> <value>`
- **Aliases**: `setmv`
- **Parameters**:
  - `vote_type`: The type of vote to limit (upvotes or downvotes).
  - `value`: The maximum number of votes allowed per user.

#### `showsettings`

- **Description**: Display the current tier list settings.
- **Usage**: `[p]tierlistset showsettings`
- **Aliases**: `ss`, `show`, `settings`

### `category`

- **Description**: Manage tier list categories.
- **Usage**: `[p]tierlistset category`

#### `list`

- **Description**: List all categories with their choices.
- **Usage**: `[p]tierlistset category list`

#### `create`

- **Description**: Create a new tier list category.
- **Usage**: `[p]tierlistset category create <name> [channel] [description]`
- **Aliases**: `add`, `+`, `new`

#### `delete`

- **Description**: Delete a tier list category.
- **Usage**: `[p]tierlistset category delete <name>`
- **Aliases**: `remove`, `-`, `del`

#### `updatemessage`

- **Description**: Update a category's voting message.
- **Usage**: `[p]tierlistset category updatemessage <name>`
- **Aliases**: `update`, `refresh`

### `edit`

- **Description**: Edit a tier list category.
- **Usage**: `[p]tierlistset category edit`

#### `channel`

- **Description**: Change the channel for a category's voting message.
- **Usage**: `[p]tierlistset category edit channel <name> <channel>`
- **Aliases**: `chan`

#### `description`

- **Description**: Edit a category's description.
- **Usage**: `[p]tierlistset category edit description <name> <description>`
- **Aliases**: `desc`

#### `name`

- **Description**: Rename a category.
- **Usage**: `[p]tierlistset category edit name <name> <new_name>`
- **Aliases**: `rename`

### `option`

- **Description**: Manage options within a category.
- **Usage**: `[p]tierlistset category option`

#### `add`

- **Description**: Add an option to a category.
- **Usage**: `[p]tierlistset category option add <category> <option>`
- **Aliases**: `+`, `new`

#### `remove`

- **Description**: Remove an option from a category.
- **Usage**: `[p]tierlistset category option remove <category> <option_index>`
- **Aliases**: `del`, `-`

#### `forceadd`

- **Description**: Force add an option to a category, bypassing similarity checks.
- **Usage**: `[p]tierlistset category option forceadd <category> <option>`
- **Aliases**: `force`, `addforce`

#### `clear`

- **Description**: Clear all options from a category.
- **Usage**: `[p]tierlistset category option clear <category>`
- **Aliases**: `reset`

## Installation

If you haven't added the original repository before, let's add it first. We'll call it "Craigbot-Cogs" here.

`[p]repo add Craigbot-Cogs https://github.com/90sCraig/Craigbot-Cogs`

Now, we can install TierLists.

`[p]cog install Craigbot-Cogs tierlists`

Once it's installed, it is not loaded by default. Load it by running the following command:
`[p]load tierlists`

## Further Support

For additional help, you can reach out via the support channels listed below:

- Join the [Craigbot Support Discord server](https://discord.gg/7ympDwSEqA) for direct assistance.
- Open an issue or pull request on the [Craigbot-Cogs GitHub repository](https://github.com/90sCraig/Craigbot-Cogs) if you encounter any issues or have suggestions for improvements.

## Changelog

**Version 1.0.0**

- Initial release of the TierLists cog.

## Credit

This cog is a fork of the original Tierlists cog by [i-am-zaidali](https://github.com/i-am-zaidali). Special thanks to [i-am-zaidali](https://github.com/i-am-zaidali) for the original [Tierlists cog](https://github.com/i-am-zaidali/bounty-cogs/tree/main).
