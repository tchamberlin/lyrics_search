import logging

from tqdm import tqdm

from lyrics_search.apis import musixmatch, spotify
from lyrics_search.defaults import DEFAULT_RESULTS_PATH
from lyrics_search.utils import load_json, normalize_query, save_json

LOGGER = logging.getLogger(__name__)


def do_lyrics_search(
    query,
    playlist_name,
    output_path,
    frontends,
    backends,
    max_playlist_tracks,
    languages,
    create_playlist,
    fast,
    deep,
    no_query_in_title,
    require_title_contains_query,
):
    unsupported_backends = set(backends).difference({"musixmatch", "spotify"})
    if unsupported_backends:
        raise NotImplementedError(f"Unsupported backends: {unsupported_backends}")

    normalized_query = normalize_query(query)
    output_path = (
        output_path if output_path else DEFAULT_RESULTS_PATH / normalized_query
    )
    LOGGER.info(f"Writing output to {output_path}")
    if "musixmatch" in backends:
        musixmatch_results = musixmatch.search_and_filter(
            query,
            page=1,
            page_size=100,
            max_pages=50,
            require_title_contains_query=require_title_contains_query,
            output_path=output_path,
            # TODO: Do we need a separate arg for this? Currently used for Spotify too
            get_lyrics=deep,
        )
    spotify_results = []
    if "spotify" in backends:
        spotify_results = spotify.search_and_filter(
            query, output_path, fast=fast, deep=deep
        )
        tqdm.write(f"{len(spotify_results)=}")

    spotify_json_path = output_path / f"{normalized_query}_spotify.json"
    if not spotify_json_path.exists() and not spotify:
        raise ValueError(
            f"Failed to find Spotify results cache ({str(spotify_json_path)}), and --spotify"
            " was not given! You must provide --spotify in order to create this file"
        )
    if "spotify" in frontends:
        playlist_name = playlist_name if playlist_name else f"{normalized_query}_raw"
        musixmatch_to_spotify_results_path = (
            output_path / f"{normalized_query}_musixmatch_to_spotify.json"
        )
        if "musixmatch" in backends:
            if musixmatch_to_spotify_results_path.exists():
                LOGGER.info(
                    f"Found MusixMatch->Spotify cache file {musixmatch_to_spotify_results_path}; "
                    "skipping queries"
                )
                musixmatch_to_spotify_results = load_json(
                    musixmatch_to_spotify_results_path
                )
            else:
                LOGGER.info(
                    f"Looking for {len(musixmatch_results)} MusixMatch results in Spotify"
                )
                (
                    musixmatch_to_spotify_results,
                    missing_tracks,
                ) = spotify.query_spotify_from_track_infos(
                    track_infos=musixmatch_results,
                )
                save_json(
                    musixmatch_to_spotify_results, musixmatch_to_spotify_results_path
                )
                num_musixmatch_to_spotify_results = len(musixmatch_to_spotify_results)
                num_musixmatch_results = len(musixmatch_results)
                ratio_found = (
                    num_musixmatch_to_spotify_results / num_musixmatch_results
                    if num_musixmatch_results
                    else 0
                )
                LOGGER.info(
                    f"Found {num_musixmatch_to_spotify_results}/{num_musixmatch_results} tracks "
                    f"in Spotify ({ratio_found:.0%})"
                )
                save_json(
                    missing_tracks,
                    (
                        output_path
                        / f"{normalized_query}_musixmatch_tracks_not_in_spotify.json"
                    ),
                )
            spotify_results.extend(musixmatch_to_spotify_results)

        track_ids = []
        spotify_results = sorted(
            spotify_results, key=lambda x: x["popularity"], reverse=True
        )
        # Now we "bin" the results into 3 bins
        # 1. Exact matches
        for sr in [
            _sr
            for _sr in spotify_results
            if normalized_query.lower() == _sr["name"].lower()
        ]:
            if sr["id"] not in track_ids:
                track_ids.append(sr["id"])

        # 2. Substring matches
        for sr in [
            _sr
            for _sr in spotify_results
            if normalized_query.lower() in _sr["name"].lower()
        ]:
            if sr["id"] not in track_ids:
                track_ids.append(sr["id"])

        # 3. No match in title at all (but is in lyrics, presumably)
        for sr in [
            _sr
            for _sr in spotify_results
            if normalized_query.lower() not in _sr["name"].lower()
        ]:
            if sr["id"] not in track_ids:
                track_ids.append(sr["id"])

        if create_playlist:
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
