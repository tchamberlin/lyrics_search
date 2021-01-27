# Lyrics Search

A CLI tool to generate playlists of songs whose lyrics contain a given query.

## How it Works

`$ lyrics-search astronomy --musixmatch --spotify`:

1. MusixMatch API is queried for song lyrics containing "astronomy"
1. If the results match the following conditions, they are filtered out:
    * Lyrics do not contain query
    * Title/album/artist contains one or more "banned" words (e.g. karaoke, tribute to, etc.)
    * Lyrics are in a non-allowed language (defaults to allowing only English)
    * Artist name contains the query string. This is because _lots_ of lyrics contain "artist - album - title" as their first line (or elsewhere), resulting in false-positives. Obviously we lose a few songs where an artist named a song after themselves, but that's fine
1. Duplicates are removed
1. Spotify API is used to match all of our results to Spotify tracks
1. Spotify playlist is created with the matched tracks

## Usage

This package **is not usable out-of-the-box**! You will need to apply for developer accounts for [MusixMatch](https://developer.musixmatch.com) and [Spotify](https://developer.spotify.com) in order for it to work.

But if you've done that, usage is pretty simple. Installation via `pip` should give you a wrapper script that just works:

```sh
lyrics-search --help
```

You can execute it via (that's all the wrapper does):

```sh
python -m lyrics_search --help
```

## Development

### Backends

A "backend" is some sort of lyrics search API. Currently there is only one supported: [MusixMatch](https://developer.musixmatch.com). You will need to apply for an API key in order to use this backend. This backend depends on the `MUSIXMATCH_API_KEY` environmental variable.

### Frontends

A "frontend" is some sort of music playback service. Currently there is only one supported: [Spotify](https://developer.spotify.com). You will need to apply for an API key in order to use this frontend. This frontend depends on the `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`, and `SPOTIFY_USER_ID` environmental variables.

### Environmental Variables

See [`.env.example`](./.env.example) for details on what environmental variables are used and what their values should be.
