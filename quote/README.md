# Quote

This is the cog guide for the 'Quote' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update quote`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Turn any message into a stylized quote image. Reply to a message with the `[p]quote` command and the bot generates a picture showing the message text in quotation marks alongside the author's avatar — handy for screenshotting memorable, funny, or noteworthy moments in your server.

This cog requires the [`Pillow`](https://pypi.org/project/pillow/) library, which is installed automatically when the cog is loaded.

## Commands

### `quote`
Reply to a message, then run the command to render that message as a quote image. The bot reads the replied message's text and author avatar, composes a 600px-wide PNG (text in curly quotes next to the avatar), and posts it back to the channel.

```
[p]quote
```

**How to use it:**
1. Right-click (or long-press) the message you want to quote and choose **Reply**.
2. In your reply, type `[p]quote` and send it.
3. The bot responds with the generated quote image.

If you run `[p]quote` without replying to a message, the bot reminds you to reply to one first.

> **Note:** Only the message's text content is rendered. Embeds, attachments, and stickers are not included in the image.

## Installation

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs quote
[p]load quote
```
