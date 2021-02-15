import logging
import re

from tqdm import tqdm

from lyrics_search.apis import musixmatch, spotify
from lyrics_search.defaults import DEFAULT_RESULTS_PATH
from lyrics_search.utils import normalize_query

LOGGER = logging.getLogger(__name__)
PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")


def do_lyrics_search(
    query,
    playlist_name,
    output_path,
    frontends,
    backend,
    max_playlist_tracks,
    languages,
    no_create_playlist,
    fast,
    deep,
    no_query_in_title,
):
    normalized_query = normalize_query(query)
    output_path = (
        output_path if output_path else DEFAULT_RESULTS_PATH / normalized_query
    )
    all_track_infos = None
    if backend == "musixmatch":
        all_track_infos = musixmatch.search_and_filter(
            query,
            page=1,
            page_size=100,
            max_pages=50,
            output_path=DEFAULT_RESULTS_PATH,
        )
        musixmatch_results = musixmatch.filter_track_infos(
            query,
            all_track_infos,
            languages=languages,
            no_query_in_title=no_query_in_title,
        )
    elif backend == "spotify":
        spotify_results = spotify.search_and_filter(
            query, output_path, fast=fast, deep=deep
        )
        tqdm.write(f"{len(spotify_results)=}")
    else:
        raise NotImplementedError(f"Unsupported backend: '{backend}'")

    spotify_json_path = output_path / f"{normalized_query}_spotify.json"
    if not spotify_json_path.exists() and not spotify:
        raise ValueError(
            f"Failed to find Spotify results cache ({str(spotify_json_path)}), and --spotify"
            " was not given! You must provide --spotify in order to create this file"
        )
    if "spotify" in frontends:
        playlist_name = playlist_name if playlist_name else f"{normalized_query}_raw"
        if backend == "musixmatch":
            spotify_results = spotify.query_spotify_from_track_infos(
                track_infos=musixmatch_results,
            )

        track_ids = [r["id"] for r in spotify_results]
        if not no_create_playlist:
            spotify.create_spotify_playlist(
                query=query,
                playlist_name=playlist_name,
                track_ids=track_ids[:max_playlist_tracks]
                if max_playlist_tracks
                else track_ids,
                replace_existing=True,
            )
        else:
            LOGGER.info(
                f"Not creating playlist '{playlist_name}' ({len(spotify_results)} tracks)"
            )
