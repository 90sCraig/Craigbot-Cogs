# Dictionary

This is the cog guide for the 'Dictionary' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update dictionary`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Look up English words without leaving Discord. The cog fetches definitions from the free [Dictionary API](https://dictionaryapi.dev/) and shows the word's meanings grouped by part of speech, along with synonyms, antonyms, and phonetics (including pronunciation audio where available).

The bot needs the **Embed Links** permission, and **Attach Files** if you want pronunciation audio clips to be uploaded.

## Commands

### `dictionary`
Look up a word in the English dictionary. The bot replies with an embed containing the definitions, synonyms, and antonyms.

**Alias:** `define`

```
[p]dictionary serendipity
[p]define ubiquitous
```

This is a **hybrid command**, so it also works as a slash command: `/dictionary query:<word>`.

### Using the result

The reply includes interactive buttons:

- **Phonetics** — shows the word's phonetic spelling(s) and, when the source provides them, uploads the pronunciation audio clip(s).
- **View the source** — opens the original dictionary source page in your browser (shown when a source URL is available).
- **✖️** — closes and deletes the result.

> **Notes:**
> - Only the person who ran the command (and the bot owner) can use the buttons. The view stops responding after about 3 minutes.
> - If the word isn't found, the bot replies with *"Word not found in English dictionary."* Check the spelling and try again.
> - Single words work best. Look-ups are cached, so repeating the same word is instant.

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs dictionary
[p]load dictionary
```

## Credit

This cog is a fork of the original [Dictionary cog](https://github.com/AAA3A-AAA3A/AAA3A-cogs) by [AAA3A-AAA3A](https://github.com/AAA3A-AAA3A). Check out the original docs [here](https://aaa3a-cogs.readthedocs.io/en/latest/).
