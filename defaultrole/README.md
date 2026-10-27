# DefaultRole

Assigns VHS Detectives (or another configured default role) to human members.
Disabled until configured. Requires Craigbot's Manage Roles permission, its role
above the target role, and Server Members Intent enabled in Discord and Red.
Commands require administrator or Manage Roles permission.

## Install and configure

Replace `[p]` with Craigbot's prefix. If the repository is already added, use its
existing local name in place of `Craigbot-cogs`.

```text
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs defaultrole
[p]load defaultrole
[p]defaultrole role VHS Detectives
[p]defaultrole blocked Unverified
[p]defaultrole enable
[p]defaultrole status
[p]defaultrole preview
[p]defaultrole backfill confirm
```

New joins, screening completion, and removal of the blocked role trigger a
30-second delay followed by a fresh member fetch. Bots, pending screening,
blocked members, and members already holding the role are skipped. A missing
configured role stops assignments. Backfill fetches all members and rechecks each
before writing; it can be rerun after interruption. Failed writes are logged.
`[p]defaultrole disable` stops further assignments and retains existing roles.

The delay gives other verification handlers time to act; it is not proof of
verification. If another bot adds Unverified more than 30 seconds after joining,
coordinate that workflow before enabling this cog. It never removes roles.
Changes to Discord membership can race with any role write; use Discord screening
or an explicit verified-role workflow if verification must gate sensitive access.
Missed events while Craigbot is offline are repaired with preview/backfill.
Pending delayed jobs are cancelled on cog unload; no member data is persisted.

Only one autorole cog should manage this default role. Test with a human join,
a bot join, a pending member, and an Unverified member before relying on it live.
