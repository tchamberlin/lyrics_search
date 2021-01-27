import argparse
import logging
import re
import sys
from pathlib import Path

from tqdm import tqdm

from lyrics_search.backends import musixmatch
from lyrics_search.defaults import (
    DEFAULT_ALLOWED_LANGUAGES,
    DEFAULT_BANNED_WORDS,
    DEFAULT_RESULTS_PATH,
)
from lyrics_search.filters import (
    artist_name_contains_query,
    contains_banned_words,
    lyrics_are_not_in_allowed_language,
)
from lyrics_search.frontends import spotify
from lyrics_search.handlers import TqdmLoggingHandler
from lyrics_search.utils import load_json, normalize_query, save_json

LOGGER = logging.getLogger(__name__)
PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")


def remove_duplicates(query, track_infos):
    compressed = {}
    for track_info in track_infos:
        key = (track_info["artist"], track_info["clean_track"])
        if key in compressed:
            LOGGER.warning(f"Overwriting {compressed[key]=} with {track_info=}")

        compressed[key] = track_info

    LOGGER.debug(f"De-dup'd {len(track_infos)=} to {len(compressed)=}")

    return sorted(compressed.values(), key=lambda x: x["score"], reverse=True)


def filter_track_infos(
    query,
    track_infos,
    languages=DEFAULT_ALLOWED_LANGUAGES,
    banned_words=DEFAULT_BANNED_WORDS,
):
    filtered_track_infos = []
    for track_info in track_infos:
        track = track_info["track"]
        clean_track = PARENTHETICAL_REGEX.sub("", track).strip()
        try:
            feat_start = clean_track.lower().index("feat.")
        except ValueError:
            pass
        else:
            clean_track = clean_track[:feat_start].strip()

        track_info["clean_track"] = clean_track
        if track != clean_track:
            LOGGER.debug(f"Cleaned {track=} to {clean_track=}")

        artist = track_info["artist"]
        clean_artist = PARENTHETICAL_REGEX.sub("", artist).strip()
        try:
            feat_start = clean_artist.lower().index("feat.")
        except ValueError:
            pass
        else:
            clean_artist = clean_artist[:feat_start].strip()

        track_info["clean_artist"] = clean_artist
        if artist != clean_artist:
            LOGGER.debug(f"Cleaned {artist=} to {clean_artist=}")

        clean_lyrics = LYRICS_CRUFT_REGEX.sub("", track_info["lyrics"])
        track_info["clean_lyrics"] = clean_lyrics
        if clean_lyrics:
            lyrics_word_list = [
                w.lower() for w in WHITESPACE_REGEX.split(clean_lyrics) if w
            ]
            len_lyrics_word_list = len(lyrics_word_list)
            try:
                query_index = lyrics_word_list.index(query)
            except ValueError:
                # LOGGER.exception(
                #     "Failed to find query in lyrics_word_list; need to fix WHITESPACE_REGEX"
                # )
                track_info["lyrics_snippet"] = "<ERROR>"
            else:
                lyrics_word_list[query_index] = lyrics_word_list[query_index].upper()
                start = start_ if (start_ := query_index - 5) > 0 else 0
                end = (
                    end_
                    if (end_ := query_index + 5) < len_lyrics_word_list
                    else len_lyrics_word_list
                )
                track_info["lyrics_snippet"] = " ".join(lyrics_word_list[start:end])
        else:
            track_info["lyrics_snippet"] = ""

        track_name = track_info["track"].lower()
        album_name = track_info["album"].lower()
        artist_name = track_info["artist"].lower()
        lyrics = track_info["clean_lyrics"].lower()

        filters = {
            "contains_banned_words": contains_banned_words(
                track_name, artist_name, album_name, banned_words
            ),
            "lyrics_are_not_in_allowed_language": lyrics_are_not_in_allowed_language(
                lyrics, languages
            ),
            "artist_name_contains_query": artist_name_contains_query(
                query, artist_name
            ),
        }

        if not any(filters.values()):
            filtered_track_infos.append(track_info)
        else:
            LOGGER.info(
                f"Filtered out '{artist_name}' '{track_name}' due to:\n"
                f"{[k for k, v in filters.items() if v]}"
            )

    return filtered_track_infos


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("query")
    parser.add_argument("-v", "--verbosity", choices=[0, 1, 2, 3], type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Defaults to {DEFAULT_RESULTS_PATH}/<normalized_query>",
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
    max_musixmatch_pages,
    max_musixmatch_page_size,
    languages,
    no_create_playlist,
):
    results_dict = {}
    normalized_query = normalize_query(query)
    output_path = (
        output_path if output_path else DEFAULT_RESULTS_PATH / normalized_query
    )
    musixmatch_raw_json_path = output_path / f"{normalized_query}_musixmatch_raw.json"
    if do_musixmatch:
        musixmatch_json = musixmatch.search_lyrics(
            query,
            max_pages=max_musixmatch_pages,
            page_size=max_musixmatch_page_size,
            output_path=output_path,
        )
        save_json(musixmatch_json, musixmatch_raw_json_path)

    results_dict["argv"] = " ".join(sys.argv)

    try:
        all_track_infos = load_json(musixmatch_raw_json_path)
    except FileNotFoundError as error:
        raise ValueError(
            f"MusixMatch cache file {musixmatch_raw_json_path} does not exist! "
            "Try again with --musixmatch option"
        ) from error

    if not all_track_infos:
        LOGGER.warning(
            f"Successfully loaded track infos from '{musixmatch_raw_json_path}', but it's an empty "
            "list. Consider deleting this file"
        )
    filtered_track_infos = filter_track_infos(
        query, all_track_infos, languages=languages
    )
    track_infos = remove_duplicates(query, filtered_track_infos)

    musixmatch_filtered_json_path = (
        output_path / f"{normalized_query}_musixmatch_filtered.json"
    )
    if track_infos:
        save_json(track_infos, musixmatch_filtered_json_path)

    LOGGER.debug(
        f"{len(all_track_infos)=}; {len(filtered_track_infos)=}; {len(track_infos)=}"
    )
    playlist_name = name if name else f"{normalized_query}_raw"
    spotify_json_path = output_path / f"{normalized_query}_spotify.json"
    if not spotify_json_path.exists() and not spotify:
        raise ValueError(
            f"Failed to find Spotify results cache ({str(spotify_json_path)}), and --spotify"
            " was not given! You must provide --spotify in order to create this file"
        )
    if spotify:
        if track_infos:
            spotify_json, results = spotify.export(
                query=query,
                track_infos=track_infos,
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

    spotify_json = load_json(spotify_json_path)


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
            max_musixmatch_pages=args.max_musixmatch_pages,
            max_musixmatch_page_size=args.max_musixmatch_page_size,
            languages=args.languages,
            no_create_playlist=args.no_create_playlist,
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
