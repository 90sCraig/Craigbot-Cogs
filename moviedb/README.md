# MovieDB

This is the cog guide for the 'MovieDB' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update moviedb`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).

## About this cog

Fetch rich information from [The Movie Database (TMDb)](https://www.themoviedb.org/) right inside Discord. Look up movies, TV shows, and the people who make them, or get recommendations for what to watch next. Results are shown as scrollable embeds — use the ◀️ ▶️ reactions to page through extra details such as production info and the cast.

All commands are **hybrid commands**, so they work both with your prefix (`[p]movie ...`) and as Discord slash commands (`/movie ...`).

## Setup — API key required

Before the cog will work you need a free TMDb API key:

1. Create an account at [themoviedb.org](https://www.themoviedb.org/) and request an API key under **Settings → API**.
2. Give the key to your bot (do this in DM with the bot so the key stays private):

   ```
   [p]set api tmdb api_key <your_api_key>
   ```

The bot also needs the **Embed Links** and **Read Message History** permissions in any channel where the commands are used.

## Commands

### `movie`
Show detailed info about a movie — rating, runtime, genres, overview, production companies/countries, tagline, and cast. Be specific for the best match.

```
[p]movie The Matrix
```

### `tvshow`
Show detailed info about a TV series, including production info and cast.

**Aliases:** `tv`, `tvseries`

```
[p]tvshow Breaking Bad
```

### `celebrity`
Show info about an actor, director, producer, or other crew member, including their most recent acting and production credits.

**Aliases:** `actor`, `director`

```
[p]celebrity Tom Hanks
```

### `suggestmovies`
Get a paginated list of movies similar to the one you name — great for finding your next watch.

**Alias:** `suggestmovie`

```
[p]suggestmovies Back to the Future
```

### `suggestshows`
Get a paginated list of TV shows similar to the one you name.

**Alias:** `suggestshow`

```
[p]suggestshows Game of Thrones
```

> **Tip:** If a title has multiple matches (remakes, reboots), add the year or be more specific. For multi-word titles you don't need quotes — the command reads the rest of the line as the title.

## Installation

Before using this cog you will need a TMDb API key — see [Setup](#setup--api-key-required) above.

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs moviedb
[p]load moviedb
```

## Credit

This cog is a fork of the original [MovieDB cog](https://github.com/owocado/MovieDB-cog) by [owocado](https://github.com/owocado).
