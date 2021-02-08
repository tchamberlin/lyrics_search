import argparse
import logging
import os
import re
import sys
from pathlib import Path

from fuzzywuzzy import fuzz
from tqdm import tqdm
from unidecode import unidecode

from lyrics_search.apis import spotify
from lyrics_search.contractions import expand_contraction
from lyrics_search.defaults import (
    DEFAULT_PER_WORD_HARD_RESULT_LIMIT,
    DEFAULT_PER_WORD_SOFT_RESULT_LIMIT,
    DEFAULT_RESULTS_PATH,
)
from lyrics_search.handlers import TqdmLoggingHandler
from lyrics_search.utils import load_json, save_json

LOGGER = logging.getLogger(__name__)


def create_playlist_description():
    repo_url = os.getenv("LR_REPO_URL", "<none>")
    return (
        f"Created via an automated script; author does not endorse song contents. "
        f"See {repo_url} for more details."
    )


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("query")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--allow-explicit", action="store_true")
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--no-normalize-query", action="store_true")
    parser.add_argument(
        "--max-tracks-per-word",
        type=int,
        default=5,
        help="The maximum number of tracks that will be found for each word in "
        "the query (bail out of search after this number is found)",
    )
    parser.add_argument(
        "--per-word-soft-result-limit",
        type=int,
        default=DEFAULT_PER_WORD_SOFT_RESULT_LIMIT,
        help="Once this number of results has been analyzed, "
        "bail out if we have found at least 1 match",
    )
    parser.add_argument(
        "--per-word-hard-result-limit",
        type=int,
        default=DEFAULT_PER_WORD_HARD_RESULT_LIMIT,
        help="Once this number of results has been analyzed, "
        "bail out regardless of whether any matches have been found",
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
    parser.add_argument("--playlist-name")
    parser.add_argument(
        "--create-playlist",
        action="store_true",
        help="If given, create Spotify playlist from results",
    )
    return parser.parse_args()


def do_query_spotify(
    query,
    max_matches=5,
    per_word_soft_result_limit=DEFAULT_PER_WORD_SOFT_RESULT_LIMIT,
    per_word_hard_result_limit=DEFAULT_PER_WORD_HARD_RESULT_LIMIT,
    allow_explicit=False,
):
    cleaned_query = query.lower()
    output = DEFAULT_RESULTS_PATH / f"spotify_{cleaned_query}_search_results.json"
    if output.exists():
        results = load_json(output)
    else:
        LOGGER.debug(f"Searching spotify for {query!r}")
        results = spotify.spotify_deep_search_lazy(query)

    exact_output = (
        DEFAULT_RESULTS_PATH / f"spotify_{cleaned_query}_exact_search_results.json"
    )

    if exact_output.exists():
        ret = load_json(exact_output)

    else:
        exact_matches = {}
        actual_results = []
        closest_match = None
        for i, result in enumerate(results):
            cleaned_result_name = unidecode(result["name"].lower())
            if i and i % 1000 == 0:
                LOGGER.info(
                    f"Found {len(exact_matches)}; closest match to {query!r} "
                    f"so far: {closest_match}; total results analyzed: {i}"
                )

            actual_results.append(result)
            raw_ratio = fuzz.ratio(result["name"], query)
            cleaned_ratio = fuzz.ratio(cleaned_result_name, cleaned_query)
            if not closest_match or closest_match[0] < cleaned_ratio:
                closest_match = (cleaned_ratio, result["name"])

            # TODO: add relaxed/fuzzy comparison as a second pass if the first doesn't find anything?
            if cleaned_query == cleaned_result_name:
                if not allow_explicit and result["explicit"]:
                    LOGGER.info(
                        f"Skipping {result['name']} ({result['id']}); it is explicit and "
                        "that's not allowed right now"
                    )
                    continue
                key = (
                    tuple(sorted(a["name"] for a in result["artists"])),
                    result["name"],
                )
                exact_matches[key] = (raw_ratio, cleaned_ratio, result)
                if len(exact_matches) >= max_matches:
                    LOGGER.debug(
                        f"Found {len(exact_matches)} exact matches; bailing out!"
                    )
                    break

                elif exact_matches and len(exact_matches) > per_word_soft_result_limit:
                    LOGGER.debug(
                        f"Hit {per_word_soft_result_limit=} tracks analyzed; "
                        f"bailing out with {len(exact_matches)} exact matches!"
                    )
                    break

                elif len(actual_results) > per_word_hard_result_limit:
                    LOGGER.debug(
                        f"Hit {per_word_hard_result_limit=} tracks analyzed; "
                        f"bailing out with {len(exact_matches)} exact matches!"
                    )
                    break
            _s = sorted(
                exact_matches.values(),
                # key=lambda result: result["popularity"],
                key=lambda result: (result[0], result[1], result[-1]["popularity"]),
                reverse=True,
            )
            ret = [m[-1] for m in _s]

            save_json(ret, exact_output)

        save_json(actual_results, output)
    return ret


def write_db(results, db_path=DEFAULT_RESULTS_PATH / "db.json"):
    if db_path.exists():
        db = load_json(db_path)
    else:
        db = {}

    db.update(
        {
            word: [
                {
                    "artists": [
                        {k: a[k] for k in ["id", "name"]} for a in track["artists"]
                    ],
                    "album": {k: track["album"][k] for k in ["id", "name"]},
                    "id": track["id"],
                    "name": track["name"],
                }
                for track in tracks
            ]
            for word, tracks in results.items()
        }
    )
    save_json(db, db_path)


_INTER_WORD_PUNCTUATION = r"[\"\'#\\()*+,\-/:<=>@\[\]^_`{|}~]+"
PUNCTUATION_TO_KEEP_REGEX = re.compile(r"[;!\.\?\$\%\&]")
INTER_WORD_PUNCTUATION = re.compile(_INTER_WORD_PUNCTUATION)
INTER_WORD_PUNCTUATION_LEFT_REGEX = re.compile(r"\s+" + _INTER_WORD_PUNCTUATION)
INTER_WORD_PUNCTUATION_RIGHT_REGEX = re.compile(_INTER_WORD_PUNCTUATION + r"\s+")
WHITESPACE_REGEX = re.compile(r"\s+")


def normalize_query(to_strip, decode=True):
    decoded = unidecode(to_strip) if decode else to_strip
    if len(to_strip) > 1:
        no_tail = decoded[:-1] + INTER_WORD_PUNCTUATION.sub("", decoded[-1])
    else:
        no_tail = decoded
    left = INTER_WORD_PUNCTUATION_LEFT_REGEX.sub(" ", no_tail)
    right = INTER_WORD_PUNCTUATION_RIGHT_REGEX.sub(" ", left)
    # TODO: We don't actually want to do this in all cases, just when we can't find a hyphenated word!
    no_punc = right.replace("-", " ")
    # Add a space before all "allowed" punctuation in order to make them separate "words"
    yes_punc = PUNCTUATION_TO_KEEP_REGEX.sub(r" \g<0>", no_punc)
    normalized = " ".join(
        expand_contraction(word) for word in WHITESPACE_REGEX.split(yes_punc)
    ).strip()
    return normalized


def do_playlister(
    query,
    playlist_name,
    output_path,
    no_create_playlist,
    allow_spotify=True,
    max_matches=5,
    per_word_soft_result_limit=DEFAULT_PER_WORD_SOFT_RESULT_LIMIT,
    per_word_hard_result_limit=DEFAULT_PER_WORD_HARD_RESULT_LIMIT,
    do_normalize_query=True,
    allow_explicit=False,
):
    db_path = DEFAULT_RESULTS_PATH / "db.json"
    try:
        db = load_json(db_path)
    except FileNotFoundError:
        LOGGER.info("No DB")
        db = {}

    results = []
    found = {}
    if do_normalize_query:
        cleaned_query = normalize_query(query)
        if query != cleaned_query:
            LOGGER.warning(f"Normalized {query!r} to {cleaned_query!r}")
    else:
        LOGGER.debug("Skipping query normalization")
        cleaned_query = query

    words = re.split(r"\s+", cleaned_query)
    for word in tqdm(words, unit="word"):
        cleaned_word = word.lower()
        # LOGGER.info(
        #     f"Query tracks exactly named {cleaned_word!r}"
        #     f"{f'(originally {word!r})' if cleaned_word != word else ''}"
        # )
        # First try to get the word from our DB (should hopefully contain lots of common words)
        if cleaned_word in db:
            found[word] = db[cleaned_word]
        # If we can't...
        else:
            # ...and we are allowed to query spotify, do so
            if allow_spotify:
                found[word] = do_query_spotify(
                    word,
                    max_matches=max_matches,
                    per_word_soft_result_limit=per_word_soft_result_limit,
                    per_word_hard_result_limit=per_word_hard_result_limit,
                    allow_explicit=allow_explicit,
                )
            # ...and we are NOT allowed to query spotify, set null
            else:
                LOGGER.warning(
                    f"Word {cleaned_word!r} not in DB and not allowed to query Spotify!"
                )
                found[word] = None

        results.append((word, found[word]))

    playlist = []
    missing = []
    for word, word_results in results:
        tqdm.write(f"{word!r} results:")
        # TODO: allow user selection!
        if word_results:
            playlist.append((word_results[0]["id"], word_results[0]["name"]))
        else:
            missing.append(word)
        for result in word_results:
            tqdm.write(f"  {spotify.format_item(result)}")
    if not playlist_name:
        playlist_name = query

    write_db(found)

    if missing:
        raise ValueError(
            f"No results for the following words (cannot proceed): {missing!r}"
        )
    if not no_create_playlist:
        spotify.create_spotify_playlist(
            query=query,
            playlist_name=playlist_name,
            track_ids=[track_id for track_id, __ in playlist],
            replace_existing=True,
            description=create_playlist_description(),
        )

    print("Final playlist:")
    print(" ".join([name for __, name in playlist]))


def init_logging(level=logging.DEBUG):
    root_logger = logging.getLogger(__name__.split(".")[0])
    root_logger.setLevel(level)
    # create console handler and set level to debug
    console_handler = TqdmLoggingHandler()
    console_handler.setLevel(level)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def main():
    args = parse_args()
    if args.verbosity == 3:
        init_logging(logging.DEBUG)
    elif args.verbosity > 1:
        init_logging(logging.INFO)
    else:
        init_logging(logging.WARNING)

    try:
        do_playlister(
            query=args.query,
            playlist_name=args.playlist_name,
            output_path=args.output,
            no_create_playlist=not args.create_playlist,
            max_matches=args.max_tracks_per_word,
            per_word_soft_result_limit=args.per_word_soft_result_limit,
            per_word_hard_result_limit=args.per_word_hard_result_limit,
            do_normalize_query=not args.no_normalize_query,
            allow_explicit=args.allow_explicit,
        )
    except Exception as error:
        if args.verbosity > 1:
            raise
        else:
            print(f"ERROR: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
