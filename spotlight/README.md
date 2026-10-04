# Spotlight

Spotlight keeps important, time-limited announcements visible without flooding a Discord channel. It is intentionally generic: tournaments, events, deadlines, sign-ups, community notices, and other temporary announcements can all become Spotlights.

Administrators promote an existing message instead of retyping it. Spotlight preserves the message text, author attribution, first image, attachments, and original-message link. Each repost shows the exact ending time and Discord's automatically updating relative time, such as “in 3 days.”

## Setup

Install and load the cog, then enable and sync its message action:

```text
[p]slash enable "Add to Spotlight" message
[p]slash sync
```

Red manages message actions separately from prefix commands, so syncing before enabling the action will report zero commands.

1. Right-click or long-press an announcement.
2. Choose **Apps → Add to Spotlight**.
3. Enter a duration such as `7d` (measured from the original post), or a local ending time such as `2026-10-11 21:00`.
4. Optionally override the reminder interval, role mention, or ended notice.

The prefix-command fallback is to reply to the announcement with:

```
[p]spotlight add 7d
```

Only server administrators can add, end, or configure Spotlights.

## Member commands

| Command | Purpose |
| --- | --- |
| `[p]spotlight` | Show all active Spotlights, ordered by ending time. |
| `[p]spotlight list` | Same as above. |

## Administrator commands

| Command | Purpose |
| --- | --- |
| `[p]spotlight add <duration>` | Add the message being replied to. Durations such as `30m`, `48h`, `7d`, or `2w` are measured from the original post. |
| `[p]spotlight end [ID]` | End a Spotlight by ID, or by replying to its source/latest reminder. |
| `[p]spotlightset show` | Show the server's settings. |
| `[p]spotlightset channel [#channel]` | Use one destination, or omit it to repost in each source channel. |
| `[p]spotlightset timezone <zone>` | Set an IANA timezone, such as `America/New_York`. |
| `[p]spotlightset interval <days>` | Set the default days between reminders. |
| `[p]spotlightset time <HH:MM>` | Set the reminder time in the configured timezone. |
| `[p]spotlightset mentionrole [@role]` | Set or clear the optional role that reminders may mention. |
| `[p]spotlightset mentiondefault <on/off>` | Choose whether new Spotlights mention that role by default. Off initially. |
| `[p]spotlightset endannounce <on/off>` | Choose whether new Spotlights announce when they end. |

## Reminder behavior

- Multiple Spotlights may be active at once.
- Each Spotlight expires automatically.
- Role mentions are disabled by default.
- If a Spotlight's previous reminder is still the newest message in its destination channel, the next reminder is skipped. Once conversation resumes, the due reminder can appear without stacking duplicate posts in a quiet channel.
- Server defaults apply to new Spotlights, and the message-action form can override the interval, mention, and ended-notice choices per announcement.

## Stored data

Spotlight stores active announcement content, message/channel IDs, author ID and display information, attachment links, scheduling settings, and the most recent reminder ID. Expired or manually ended Spotlights are removed. A Red data-deletion request removes active Spotlights attributed to that user.
