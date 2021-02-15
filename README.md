# Playlist Sandbox

Utilities for generating playlist from a variety of criteria. So far, just two:

* `lyrics_search`: A module for generating playlists of songs that all contain a given word/phrase
* `playlister`: A module for generating a playlist based on a list of words

## `playlister`

A module for generating a playlist based on a list of words.

### Usage

To create a playlist from a given sentence, pass it as a positional argument:

```sh
$ python -m lyrics_search.playlister "this will create a playlist named test!" --create-playlist --playlist-name test
<snip>
Final playlist:
This Will Create A Playlist Named Test !
```

This has found a song for each word in the sentence (and the exclamation point) that exactly matches. Their actual titles are then recomposed into a playlist and printed out. So, here, we've found 7 songs, with titles: `["This", "Will", "Create", "A", "Playlist", "Named", "Test", "!"]`

Results are cached at several stages on-disk to avoid hitting the API more than necessary. None of that is distributed in the repo though.

### How it Works




## Lyrics Search

A CLI tool to generate playlists of songs whose lyrics contain a given query.

### How it Works

#### Lyrics Queries

Currently the only lyrics API "backend" is MusixMatch. It will be used by default.

```sh
# Generate a Spotify playlist of songs "about" astronomy
$ lyrics-search astronomy
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
1. Duplicates are removed. We consider any songs with identical artist/track names to be duplicates
1. Track album/artist/title fields are "cleaned" to increases chances of matching against Spotify. Some examples:
    * Things in brackets -- e.g. () [] {} -- are removed. These bits are often not the same between various DBs, which causes false negatives
    * Everything after an instance of "feat." in a song title is dropped
1. Spotify API is used to match all of our cleaned results to Spotify tracks
1. Private Spotify playlist is created with the matched tracks. A description is automatically generated.

#### Track Queries

Optionally you can use Spotify as an API "backend", too. In this mode, the query is performed on track titles instead of their lyrics. They will be ranked by descending popularity.

```sh
lyrics-search astronomy --backend spotify
```

1. Spotify is queried for song titles containing "astronomy". Note that by default, Spotify caps search results at 2000 tracks. See `--deep` option to work around that
1. Song titles are "cleaned" to remove "feat." and any parentheticals (this helps avoid false-positives coming from an artist name in a song title)
1. Results are filtered to ensure that the track contains the exact query, and the artist/album do not match the query
1. Duplicates are removed. We consider any songs with identical artist/track names to be duplicates
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
