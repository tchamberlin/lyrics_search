import argparse
import logging
import sys
from pathlib import Path

from lyrics_search.defaults import DEFAULT_ALLOWED_LANGUAGES, DEFAULT_RESULTS_PATH
from lyrics_search.handlers import TqdmLoggingHandler
from lyrics_search.lyrics_search import do_lyrics_search


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("query")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-query-in-title", action="store_true")
    parser.add_argument(
        "-f",
        "--frontends",
        choices=["spotify"],
        nargs="+",
        default=["spotify"],
        help="The service(s) into which you would like to export the resulting playlists",
    )
    parser.add_argument(
        "-b",
        "--backends",
        choices=["musixmatch", "spotify"],
        default=["musixmatch"],
        nargs="+",
        help="The service you would like to your query to be performed in",
    )
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
        "master/main/en/languages.json). Effects only the musixmatch backend",
    )
    parser.add_argument("--playlist-name")
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="If given, the track title will NOT be required to contain the query",
    )
    parser.add_argument(
        "--create-playlist",
        action="store_true",
        help="If given, no Spotify playlist will be created",
    )
    return parser.parse_args()


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
            playlist_name=args.playlist_name,
            output_path=args.output,
            backends=args.backends,
            frontends=args.frontends,
            max_playlist_tracks=args.max_playlist_tracks,
            languages=args.languages,
            create_playlist=args.create_playlist,
            fast=not args.debug,
            deep=args.deep,
            no_query_in_title=args.no_query_in_title,
            require_title_contains_query=not args.no_strict,
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
