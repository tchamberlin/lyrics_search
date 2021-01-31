import argparse
import logging
import re
import sys
from pathlib import Path

from tqdm import tqdm

from lyrics_search.backends import musixmatch
from lyrics_search.defaults import DEFAULT_ALLOWED_LANGUAGES, DEFAULT_RESULTS_PATH
from lyrics_search.frontends import spotify
from lyrics_search.handlers import TqdmLoggingHandler
from lyrics_search.utils import normalize_query, save_json

LOGGER = logging.getLogger(__name__)
PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("query")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Instead of just pulling the first 2000 results, try to get _all_ search results "
        "via a convoluted series of more specific 'sub'-searches",
    )
    parser.add_argument("-v", "--verbosity", choices=[0, 1, 2, 3], type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Defaults to {DEFAULT_RESULTS_PATH}/<normalized_query>",
    )
    parser.add_argument(
        "--max-playlist-tracks",
        type=int,
        help="Maximum number of tracks in output playlist",
        default=1000,
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=DEFAULT_ALLOWED_LANGUAGES,
        help="One or more Unicode CLDR language codes (e.g. 'en es' for English and Spanish) "
        "to allow in lyrics (https://github.com/unicode-cldr/cldr-localenames-modern/blob/"
        "master/main/en/languages.json)",
    )
    parser.add_argument("--name")
    parser.add_argument("--max-musixmatch-pages", type=int, default=100)
    parser.add_argument("--max-musixmatch-page-size", type=int, default=100)
    parser.add_argument("--musixmatch", action="store_true")
    parser.add_argument("--spotify", action="store_true")
    # parser.add_argument(
    #     "--allow-duplicate-filenames",
    #     action="store_true",
    #     help="By default, this tool will overwrite existing playlists of the same name",
    # )
    parser.add_argument(
        "--no-create-playlist",
        action="store_true",
        help="If given, no Spotify playlist will be created",
    )
    return parser.parse_args()


def do_lyrics_search(
    query,
    name,
    output_path,
    do_musixmatch,
    do_spotify,
    max_playlist_tracks,
    max_musixmatch_pages,
    max_musixmatch_page_size,
    languages,
    no_create_playlist,
    fast,
    deep,
):
    results_dict = {}
    normalized_query = normalize_query(query)
    output_path = (
        output_path if output_path else DEFAULT_RESULTS_PATH / normalized_query
    )
    all_track_infos = None
    if do_musixmatch:
        all_track_infos = musixmatch.search_and_filter(
            query,
            page=1,
            page_size=100,
            max_pages=50,
            output_path=DEFAULT_RESULTS_PATH,
        )
        musixmatch_results = musixmatch.filter_track_infos(
            query, all_track_infos, languages=languages
        )
    elif do_spotify:
        spotify_results = spotify.search_and_filter(
            query, output_path, fast=fast, deep=deep
        )
        tqdm.write(f"{len(spotify_results)=}")
    else:
        raise ValueError("nope")

    playlist_name = name if name else f"{normalized_query}_raw"
    spotify_json_path = output_path / f"{normalized_query}_spotify.json"
    if not spotify_json_path.exists() and not spotify:
        raise ValueError(
            f"Failed to find Spotify results cache ({str(spotify_json_path)}), and --spotify"
            " was not given! You must provide --spotify in order to create this file"
        )
    if spotify:
        if spotify_results:
            save_json(
                [spotify.format_item(item) for item in spotify_results],
                output_path / f"{normalized_query}_spotify_playlist.json",
            )
            if not no_create_playlist:
                track_ids = [r["id"] for r in spotify_results]
                spotify.create_spotify_playlist(
                    query=query,
                    playlist_name=playlist_name,
                    track_ids=track_ids[:max_playlist_tracks]
                    if max_playlist_tracks
                    else track_ids,
                    replace_existing=True,
                )
            else:
                print(
                    f"Not creating playlist '{playlist_name}' ({len(spotify_results)} tracks)"
                )
                # for item in spotify_results:
                #     print(spotify.format_item(item))
        elif track_infos:
            spotify_json, results = spotify.export(
                query=query,
                # track_infos=track_infos,
                spotify_results=spotify_results,
                playlist_name=playlist_name,
                create_playlist=not no_create_playlist,
            )
            save_json(spotify_json, spotify_json_path)
            results_json_path = output_path / f"{normalized_query}_final.json"
            results_dict["results"] = results
            save_json(results_dict, results_json_path)
        else:
            tqdm.write("No tracks found; nothing to export to Spotify")
            sys.exit(1)


def main():
    args = parse_args()
    if args.verbosity == 3:
        init_logging(logging.DEBUG)
    elif args.verbosity > 1:
        init_logging(logging.INFO)
    else:
        init_logging(logging.WARNING)

    try:
        do_lyrics_search(
            query=args.query,
            name=args.name,
            output_path=args.output,
            do_musixmatch=args.musixmatch,
            do_spotify=args.spotify,
            max_playlist_tracks=args.max_playlist_tracks,
            max_musixmatch_pages=args.max_musixmatch_pages,
            max_musixmatch_page_size=args.max_musixmatch_page_size,
            languages=args.languages,
            no_create_playlist=args.no_create_playlist,
            fast=not args.debug,
            deep=args.deep,
        )
    except Exception as error:
        if args.verbosity > 1:
            raise
        else:
            print(f"ERROR: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()


def init_logging(level=logging.DEBUG):
    root_logger = logging.getLogger(__name__.split(".")[0])
    root_logger.setLevel(level)
    # create console handler and set level to debug
    console_handler = TqdmLoggingHandler()
    console_handler.setLevel(level)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
