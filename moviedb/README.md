# MovieDB

This is the cog guide for the 'MovieDB' cog. This guide contains the collection of commands which you can use in the cog. Throughout this guide, `[p]` will always represent your prefix. Replace `[p]` with your own prefix when you use these commands in Discord.

> **Note:**
> Ensure that you are up to date by running `[p]cog update moviedb`.
> If there is something missing, or something that needs improving in this documentation, feel free to create an issue [here](https://github.com/90sCraig/Craigbot-Cogs/issues).
> This documentation is auto-generated every time this cog receives an update.

## About this cog

Fetch information from [The Movie Database](https://www.themoviedb.org/). Look up movies, TV shows and celebrities, or get recommendations for what to watch next.

## Commands

### `celebrity`
Show details about an actor, director or other movie personality.

```
[p]celebrity Tom Hanks
```

### `movie`
Display information about a specific movie.

```
[p]movie The Matrix
```

### `tvshow`
Display information about a TV series.

```
[p]tvshow Breaking Bad
```

### `suggestmovies`
Get a list of recommended movies similar to the one provided.

```
[p]suggestmovies "Back to the Future"
```

### `suggestshows`
Get a list of recommended TV shows similar to the one provided.

```
[p]suggestshows "Game of Thrones"
```

## Installation

Before using this cog you will need a free API key from themoviedb.org. Once you have the key, set it up with:

```
[p]set api tmdb api_key <api_key>
```

If you haven't added this repository before, install with the following commands:

```bash
[p]repo add Craigbot-cogs https://github.com/90sCraig/Craigbot-Cogs
[p]cog install Craigbot-cogs moviedb
[p]load moviedb
```

