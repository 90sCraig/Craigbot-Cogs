# Tierlist Admin Commands Documentation

This documentation covers the `tierlistset` command group, which is used to manage tier list settings and categories for your Discord server.

## Command Overview

### `tierlistset`

- **Description**: The base command for managing tier list settings.
- **Usage**: `[p]tierlistset`

#### `setpercentiles`

- **Description**: Set the percentile value for a specific tier.
- **Usage**: `[p]tierlistset setpercentiles <tier> <value>`
- **Aliases**: `setp`
- **Parameters**:
  - `tier`: The tier to set the percentile for (S, A, B, C, D, E).
  - `value`: The percentile value to assign to the tier.
- **Example**: `[p]tierlistset setpercentiles A 85`

#### `setmaxvotes`

- **Description**: Set the maximum number of votes a user can cast.
- **Usage**: `[p]tierlistset setmaxvotes <vote_type> <value>`
- **Aliases**: `setmv`
- **Parameters**:
  - `vote_type`: The type of vote to limit (upvotes or downvotes).
  - `value`: The maximum number of votes allowed per user.
- **Example**: `[p]tierlistset setmaxvotes upvotes 10`

#### `showsettings`

- **Description**: Display the current tier list settings.
- **Usage**: `[p]tierlistset showsettings`
- **Aliases**: `ss`, `show`, `settings`
- **Example**: `[p]tierlistset showsettings`

### `category`

- **Description**: Manage tier list categories.
- **Usage**: `[p]tierlistset category`

#### `list`

- **Description**: List all categories with their choices.
- **Usage**: `[p]tierlistset category list`
- **Example**: `[p]tierlistset category list`

#### `create`

- **Description**: Create a new tier list category.
- **Usage**: `[p]tierlistset category create <name> [channel] [description]`
- **Aliases**: `add`, `+`, `new`
- **Parameters**:
  - `name`: The name of the new category.
  - `channel`: (Optional) The channel where the voting embed will be posted. Defaults to the current channel.
  - `description`: (Optional) A description for the category.
- **Example**: `[p]tierlistset category create BestMovies #voting "Vote for the best movies"`

#### `delete`

- **Description**: Delete a tier list category.
- **Usage**: `[p]tierlistset category delete <name>`
- **Aliases**: `remove`, `-`, `del`
- **Parameters**:
  - `name`: The name of the category to delete.
- **Example**: `[p]tierlistset category delete BestMovies`

#### `updatemessage`

- **Description**: Update a category's voting message.
- **Usage**: `[p]tierlistset category updatemessage <name>`
- **Aliases**: `update`, `refresh`
- **Parameters**:
  - `name`: The name of the category to update.
- **Example**: `[p]tierlistset category updatemessage BestMovies`

### `edit`

- **Description**: Edit a tier list category.
- **Usage**: `[p]tierlistset category edit`

#### `channel`

- **Description**: Change the channel for a category's voting message.
- **Usage**: `[p]tierlistset category edit channel <name> <channel>`
- **Aliases**: `chan`
- **Parameters**:
  - `name`: The name of the category.
  - `channel`: The new channel for the voting message.
- **Example**: `[p]tierlistset category edit channel BestMovies #new-channel`

#### `description`

- **Description**: Edit a category's description.
- **Usage**: `[p]tierlistset category edit description <name> <description>`
- **Aliases**: `desc`
- **Parameters**:
  - `name`: The name of the category.
  - `description`: The new description.
- **Example**: `[p]tierlistset category edit description BestMovies "Vote for your favorite movies"`

#### `name`

- **Description**: Rename a category.
- **Usage**: `[p]tierlistset category edit name <name> <new_name>`
- **Aliases**: `rename`
- **Parameters**:
  - `name`: The current name of the category.
  - `new_name`: The new name for the category.
- **Example**: `[p]tierlistset category edit name BestMovies FavoriteMovies`

### `option`

- **Description**: Manage options within a category.
- **Usage**: `[p]tierlistset category option`

#### `add`

- **Description**: Add an option to a category.
- **Usage**: `[p]tierlistset category option add <category> <option>`
- **Aliases**: `+`, `new`
- **Parameters**:
  - `category`: The name of the category.
  - `option`: The option to add.
- **Example**: `[p]tierlistset category option add BestMovies "The Matrix"`

#### `remove`

- **Description**: Remove an option from a category.
- **Usage**: `[p]tierlistset category option remove <category> <option_index>`
- **Aliases**: `del`, `-`
- **Parameters**:
  - `category`: The name of the category.
  - `option_index`: The index of the option to remove (as shown in `[p]tierlistset showsettings`).
- **Example**: `[p]tierlistset category option remove BestMovies 2`

#### `forceadd`

- **Description**: Force add an option to a category, bypassing similarity checks.
- **Usage**: `[p]tierlistset category option forceadd <category> <option>`
- **Aliases**: `force`, `addforce`
- **Parameters**:
  - `category`: The name of the category.
  - `option`: The option to force add.
- **Example**: `[p]tierlistset category option forceadd BestMovies "Inception"`

#### `clear`

- **Description**: Clear all options from a category.
- **Usage**: `[p]tierlistset category option clear <category>`
- **Aliases**: `reset`
- **Parameters**:
  - `category`: The name of the category.
- **Example**: `[p]tierlistset category option clear BestMovies`

## Notes

- Replace `[p]` with your bot's prefix when using these commands.
- Some commands require admin permissions to execute.
- Use the commands responsibly to manage your server’s tier list categories effectively.

## Credits

This cog is a part of the tier list management system in the Red-DiscordBot framework, customized for your specific server needs.
