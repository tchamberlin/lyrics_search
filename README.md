# Lyrics Search

A CLI tool to generate playlists of songs whose lyrics contain a given query.

## How it Works

```sh
# Generate a Spotify playlist of songs "about" marshmallows
$ lyrics-search astronomy --musixmatch --spotify
```

Here's what happens:

1. MusixMatch API is queried for song lyrics containing "astronomy"
1. If the results match the following conditions, they are filtered out:
    * Title/album/artist contains one or more "banned" words (e.g. karaoke, tribute to, etc.)
    * Lyrics are in a non-allowed language (defaults to allowing only English)
    * Artist name contains the query string. This is because _lots_ of lyrics contain "artist - album - title" as their first line (or elsewhere), resulting in false-positives. Obviously we lose a few songs where an artist named a song after themselves, but that's fine
1. Results are scored via a very crude algorithm:
    * If the song title contains the query, +1 point
    * A "lyrics score" is derived via: `num_instances_of_query_in_lyrics / len_of_lyrics`
    * Those two factors are added together, and that's the score
    * Results are sorted in descending order based on score
1. Duplicates are removed
1. Track album/artist/title fields are "cleaned" to increases chances of matching against Spotify. Some examples:
    * Things in brackets -- e.g. () [] {} -- are removed. These bits are often not the same between various DBs, which causes false negatives
    * Everything after an instance of "feat." in a song title is dropped
1. Spotify API is used to match all of our cleaned results to Spotify tracks
1. Private Spotify playlist is created with the matched tracks. A description is automatically generated.

## Usage

This package **is not usable out-of-the-box**! You will need to apply for developer accounts for [MusixMatch](https://developer.musixmatch.com) and [Spotify](https://developer.spotify.com) in order for it to work.

Once you've done that, you'll need to set a few environmental variables (or create a `.env` file from [`.env.example`](./.env.example)).

But once you've done that, usage is pretty simple. Installation via `pip` should give you a wrapper script that just works:

```sh
$ lyrics-search --help
```

You can execute it via (that's pretty much all the wrapper does):

```sh
$ python -m lyrics_search --help
```

## Development

### Caching

Caches are generated at various stages of the pipeline, to avoid excessive API hits. So, if you've already run `--musixmatch` for a given query, you can leave it out of future queries. For example:

```sh
# Create a playlist for test_query. WILL hit the API
$ lyrics-search test_query --musixmatch
# Make some tweaks to the filters, cleaning functions, etc.
# Will NOT hit the API, until the cache file is deleted
$ lyrics-search test_query
```

### Backends

A "backend" is some sort of lyrics search API. Currently there is only one supported: [MusixMatch](https://developer.musixmatch.com). You will need to apply for an API key in order to use this backend. This backend depends on the `MUSIXMATCH_API_KEY` environmental variable.

### Frontends

A "frontend" is some sort of music playback service. Currently there is only one supported: [Spotify](https://developer.spotify.com). You will need to apply for an API key in order to use this frontend. This frontend depends on the `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`, and `SPOTIFY_USER_ID` environmental variables.

### Environmental Variables

See [`.env.example`](./.env.example) for details on what environmental variables are used and what their values should be.

### Dependencies

Dependencies are handled by Poetry:

```sh
$ poetry install
```

### Build

Building is handled by Poetry:

```sh
$ poetry build
```
