import logging
import math
import os

import requests
from tqdm import tqdm

from lyrics_search.defaults import (
    DEFAULT_ALLOWED_LANGUAGES,
    DEFAULT_BANNED_WORDS,
    DEFAULT_RESULTS_PATH,
)
from lyrics_search.filters import (
    artist_name_contains_query,
    contains_banned_words,
    lyrics_are_not_in_allowed_language,
    title_contains_query,
)
from lyrics_search.normalize import (
    LYRICS_CRUFT_REGEX,
    WHITESPACE_REGEX,
    clean_track_field,
)
from lyrics_search.utils import load_json, normalize_query, save_json

LOGGER = logging.getLogger(__name__)

TRACK_API_URL = "http://api.musixmatch.com/ws/1.1/track.search"
LYRIC_API_URL = "http://api.musixmatch.com/ws/1.1/track.lyrics.get"
MUSIXMATCH_API_KEY = os.getenv("MUSIXMATCH_API_KEY")
if not MUSIXMATCH_API_KEY:
    raise ValueError("MUSIXMATCH_API_KEY must be set in env!")


def get_track_list_filename(normalized_query):
    return f"musixmatch_{normalized_query}_track_list.json"


def get_track_info_filename(normalized_query):
    return f"musixmatch_{normalized_query}_track_info.json"


def gen_lyrics_snippet(query, cleaned_lyrics):
    lyrics_word_list = [w.lower() for w in WHITESPACE_REGEX.split(cleaned_lyrics) if w]
    # TODO: Use word regex to do the counting here; don't trust this (doesn't
    # handle contractions etc.)
    len_lyrics_word_list = len(lyrics_word_list)
    lyrics_snippet = "<EMPTY>"
    if len_lyrics_word_list > 0:
        try:
            query_index = lyrics_word_list.index(query)
        except ValueError:
            LOGGER.debug("Failed to find query in lyrics_word_list")
            lyrics_snippet = "<MISSING>"
        else:
            lyrics_word_list[query_index] = lyrics_word_list[query_index].upper()
            start = start_ if (start_ := query_index - 5) > 0 else 0
            end = (
                end_
                if (end_ := query_index + 5) < len_lyrics_word_list
                else len_lyrics_word_list
            )
            lyrics_snippet = " ".join(lyrics_word_list[start:end])

    return lyrics_snippet


def get_track_info(query, track, get_lyrics=False):
    """Given a MusixMatch track dict, return a track_info dict.

    track_info is our attempt at a standardized (API agnostic) representation of a track

    If get_lyrics is True, fetch lyrics for each track and populate some attitional values in
    the track_info
    """

    track_info = {
        "artist": track["track"]["artist_name"],
        "album": track["track"]["album_name"],
        "track": track["track"]["track_name"],
        "track_id": int(track["track"]["track_id"]),
    }
    if not track_info["album"]:
        track_info["album"] = ""

    track_info["cleaned_track"] = clean_track_field(track_info["track"])
    track_info["cleaned_artist"] = clean_track_field(track_info["artist"])
    track_info["cleaned_album"] = clean_track_field(track_info["album"])
    if get_lyrics:
        lyrics = get_lyrics_for_track(track_info["track_id"])
        track_info["lyrics"] = lyrics
        cleaned_lyrics = LYRICS_CRUFT_REGEX.sub("", track_info["lyrics"])
        track_info["cleaned_lyrics"] = cleaned_lyrics
        track_info["lyrics_snippet"] = gen_lyrics_snippet(query, cleaned_lyrics)
        # TODO: use regex!
        track_info["num_query_references"] = lyrics.lower().count(query)
        track_info["score"] = get_score(query, track_info)
    else:
        track_info["lyrics"] = ""
        track_info["cleaned_lyrics"] = ""
        track_info["lyrics_snippet"] = ""
        track_info["num_query_references"] = 0
        track_info["score"] = 0

    return track_info


def get_lyrics_for_track(track_id):
    """Given a MusixMatch track ID, fetch and return its lyrics."""

    # TODO: handle error case
    response = requests.get(
        LYRIC_API_URL, params={"track_id": track_id, "apikey": MUSIXMATCH_API_KEY}
    )
    lyrics_response_dict = response.json()
    # TODO: handle error case
    status_code = lyrics_response_dict["message"]["header"]["status_code"]
    if status_code != 200:
        # TODO: We should probably do something about this :)
        LOGGER.error(f"Failed to query {response.url} ({status_code=})")
        return None

    # TODO: handle error case
    lyrics = lyrics_response_dict["message"]["body"]["lyrics"]["lyrics_body"]
    return lyrics


def get_track_infos_from_track_list(query, track_list, get_lyrics=False):
    track_infos = []
    for track in tqdm(track_list, unit="track"):
        track_info = get_track_info(query, track, get_lyrics=get_lyrics)
        if track_info:
            track_infos.append(track_info)

    track_infos = sorted(track_infos, key=lambda x: x["score"], reverse=True)
    return track_infos


def get_track_results_page(query, page, page_size):
    query_dict = {
        "q_lyrics": query,
        "q_track": query,
        # "f_has_lyrics": True,
        "page": page,
        "page_size": page_size,
        "apikey": MUSIXMATCH_API_KEY,
        "s_artist_rating": "DESC",
    }
    response = requests.get(TRACK_API_URL, params=query_dict)
    response_dict = response.json()
    header = response_dict["message"]["header"]
    if (status_code := int(header["status_code"])) != 200:
        raise ValueError(
            f"MusixMatch API responded with {status_code=}! Used API key {query_dict['apikey']=}. "
            "See https://developer.musixmatch.com/documentation/status-codes"
        )
    num_available = int(header["available"])

    body = response_dict["message"]["body"]
    track_list = body["track_list"]
    return track_list, num_available


def get_score(query, track_info):
    track = track_info["track"]
    lyrics = track_info["lyrics"]
    num_query_references = int(track_info["num_query_references"])

    score = 0
    if num_query_references > 0:
        score += (num_query_references * len(query)) / len(lyrics)

    # TODO: Similarity comparison also!
    if query.lower() in track.lower():
        score += 1

    return score


def get_tracks_for_query(
    query,
    page=1,
    page_size=100,
    max_pages=50,
    output_path=DEFAULT_RESULTS_PATH,
):
    track_list_for_page, num_available = get_track_results_page(query, page, page_size)
    num_pages = math.ceil(num_available / page_size)
    tqdm.write(f"There are {num_available} tracks available across {num_pages} pages")
    actual_num_pages = num_pages
    if max_pages and max_pages < actual_num_pages:
        tqdm.write(f"Capped max pages at {max_pages=}")
        actual_num_pages = max_pages

    # Set the first page's results as the start of our full track_list
    track_list = track_list_for_page
    for current_page in tqdm(range(2, actual_num_pages + 1), unit="page"):
        try:
            track_list_for_page, __ = get_track_results_page(
                query, current_page, page_size
            )
        except ValueError:
            LOGGER.exception("uh oh")
            continue

        tqdm.write(
            f"Found {len(track_list_for_page)} tracks in iteration "
            f"{current_page}/{actual_num_pages}"
        )
        track_list.extend(track_list_for_page)

    track_list_path = output_path / get_track_list_filename(normalize_query(query))
    save_json(track_list, track_list_path)

    return track_list


def search_api(
    query,
    page=1,
    page_size=100,
    max_pages=50,
    output_path=DEFAULT_RESULTS_PATH,
    get_lyrics=False,
):
    """Search MusixMatch for given lyrics query.

    First, get a list of all the tracks that contain the query If
    get_lyrics is True, a second step is performed: a lyrics snippet is
    retrieved for every returned track
    """

    track_list_path = output_path / get_track_list_filename(normalize_query(query))
    if track_list_path.exists():
        track_list = load_json(track_list_path)
    else:
        track_list = get_tracks_for_query(
            query,
            page=page,
            page_size=page_size,
            max_pages=max_pages,
            output_path=output_path,
        )

    track_infos = get_track_infos_from_track_list(
        query, track_list, get_lyrics=get_lyrics
    )
    return track_infos


def search_and_filter(
    query,
    page=1,
    page_size=100,
    max_pages=50,
    require_title_contains_query=True,
    output_path=DEFAULT_RESULTS_PATH,
    languages=DEFAULT_ALLOWED_LANGUAGES,
    banned_words=DEFAULT_BANNED_WORDS,
    get_lyrics=False,
):
    normalized_query = normalize_query(query)
    musixmatch_search_results_json_path = (
        output_path / f"{normalized_query}_musixmatch_search_results.json"
    )
    if not musixmatch_search_results_json_path.exists():
        LOGGER.info(f"Searching MusixMatch for '{query}'...")
        track_infos = search_api(
            query,
            max_pages=max_pages,
            page_size=page_size,
            output_path=output_path,
            get_lyrics=get_lyrics,
        )
        save_json(track_infos, musixmatch_search_results_json_path)
    else:
        LOGGER.info(
            "Skipping MusixMatch search; results are cached at "
            f"'{musixmatch_search_results_json_path}'"
        )
        track_infos = load_json(musixmatch_search_results_json_path)

    filtered_track_infos = filter_track_infos(
        query,
        track_infos,
        require_title_contains_query=require_title_contains_query,
        banned_words=banned_words,
        languages=languages,
    )

    return remove_duplicates(query, filtered_track_infos)


def filter_track_infos(
    query,
    track_infos,
    no_query_in_title=False,
    require_title_contains_query=True,
    languages=DEFAULT_ALLOWED_LANGUAGES,
    banned_words=DEFAULT_BANNED_WORDS,
):
    filtered_track_infos = []
    for track_info in track_infos:
        track_name = track_info["track"].lower()
        album_name = track_info["album"].lower()
        artist_name = track_info["artist"].lower()
        lyrics = track_info["cleaned_lyrics"].lower()

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

        if no_query_in_title:
            filters["title_contains_query"] = title_contains_query(
                query.lower(), track_name
            )

        if require_title_contains_query:
            filters["title_does_not_contain_query"] = not title_contains_query(
                query.lower(), track_name
            )

        # If no filters are True, then they have all passed
        if not any(filters.values()):
            filtered_track_infos.append(track_info)
        # If any are true, we just log why it was filtered
        else:
            LOGGER.debug(
                f"Filtered out artist:'{artist_name}' track:'{track_name}' due to: "
                f"{[k for k, v in filters.items() if v]}"
            )

    return filtered_track_infos


def remove_duplicates(query, track_infos):
    compressed = {}
    for track_info in track_infos:
        key = (track_info["artist"], track_info["cleaned_track"])
        if key in compressed:
            LOGGER.debug(f"Overwriting {compressed[key]=} with {track_info=}")

        compressed[key] = track_info

    LOGGER.info(f"De-dup'd {len(track_infos)=} to {len(compressed)=}")

    return sorted(compressed.values(), key=lambda x: x["score"], reverse=True)
