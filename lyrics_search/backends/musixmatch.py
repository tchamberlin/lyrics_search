import logging
import os
import re

import requests
from tqdm import tqdm

from lyrics_search.defaults import DEFAULT_RESULTS_PATH
from lyrics_search.utils import load_json, normalize_query, save_json

LOGGER = logging.getLogger(__name__)

PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")

TRACK_API_URL = "http://api.musixmatch.com/ws/1.1/track.search"
LYRIC_API_URL = "http://api.musixmatch.com/ws/1.1/track.lyrics.get"
MUSIXMATCH_API_KEY = os.getenv("MUSIXMATCH_API_KEY")
if not MUSIXMATCH_API_KEY:
    raise ValueError("MUSIXMATCH_API_KEY must be set in env!")


def get_track_list_filename(normalized_query):
    return f"musixmatch_{normalized_query}_track_list.json"


def get_track_info_filename(normalized_query):
    return f"musixmatch_{normalized_query}_track_info.json"


def get_lyrics_for_track(query, track):
    track_id = int(track["track"]["track_id"])
    response = requests.get(
        LYRIC_API_URL, params={"track_id": track_id, "apikey": MUSIXMATCH_API_KEY}
    )
    lyrics_response_dict = response.json()
    status_code = lyrics_response_dict["message"]["header"]["status_code"]
    if status_code != 200:
        raise ValueError(f"Failed to query {response.url} ({status_code=})")

    lyrics = lyrics_response_dict["message"]["body"]["lyrics"]["lyrics_body"]
    num_query_references = lyrics.lower().count(query)
    track_info = {
        "artist": track["track"]["artist_name"],
        "album": track["track"]["album_name"],
        "track": track["track"]["track_name"],
        "track_id": track_id,
        "lyrics": lyrics,
        "num_query_references": num_query_references,
    }
    track_info["score"] = get_score(query, track_info)
    track = track_info["track"]
    clean_track = PARENTHETICAL_REGEX.sub("", track).strip()
    track_info["clean_track"] = clean_track
    if track != clean_track:
        tqdm.write(f"Cleaned {track=} to {clean_track=}")

    clean_lyrics = LYRICS_CRUFT_REGEX.sub("", track_info["lyrics"])
    track_info["clean_lyrics"] = clean_lyrics
    lyrics_word_list = [w.lower() for w in WHITESPACE_REGEX.split(clean_lyrics) if w]
    len_lyrics_word_list = len(lyrics_word_list)
    if len_lyrics_word_list > 0:
        try:
            query_index = lyrics_word_list.index(query)
        except ValueError:
            LOGGER.exception(
                "Failed to find query in lyrics_word_list; need to fix WHITESPACE_REGEX"
            )
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

    return track_info


def get_lyrics(query, track_list):
    track_infos = []
    for track in track_list:
        track_info = get_lyrics_for_track(query, track)
        if track_info:
            track_infos.append(track_info)

    track_infos = sorted(track_infos, key=lambda x: x["score"], reverse=True)
    return track_infos


def get_track_results_page(query, page, page_size):
    query_dict = {
        "q_lyrics": query,
        "f_has_lyrics": True,
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


def get_track_list(
    query,
    page=1,
    page_size=100,
    max_pages=50,
    output_path=DEFAULT_RESULTS_PATH,
):
    track_list_for_page, num_available = get_track_results_page(query, page, page_size)
    num_pages = (num_available // page_size) + 1
    tqdm.write(f"There are {num_available} tracks available across {num_pages} pages")
    actual_num_pages = num_pages
    if max_pages and max_pages < actual_num_pages:
        tqdm.write(f"Capped max pages at {max_pages=}")
        actual_num_pages = max_pages

    # Set the first page's results as the start of our full track_list
    track_list = track_list_for_page
    for current_page in tqdm(range(2, actual_num_pages + 1), unit="page"):
        track_list_for_page, __ = get_track_results_page(query, current_page, page_size)

        tqdm.write(
            f"Found {len(track_list_for_page)} tracks in iteration "
            f"{current_page}/{actual_num_pages}"
        )
        track_list.extend(track_list_for_page)

    track_list_path = output_path / get_track_list_filename(normalize_query(query))
    save_json(track_list, track_list_path)

    return track_list


def search_lyrics(
    query,
    page=1,
    page_size=100,
    max_pages=50,
    output_path=DEFAULT_RESULTS_PATH,
    do_filter=True,
):

    track_list_path = output_path / get_track_list_filename(normalize_query(query))
    if track_list_path.exists():
        track_list = load_json(track_list_path)
    else:
        track_list = get_track_list(
            query,
            page=page,
            page_size=page_size,
            max_pages=max_pages,
            output_path=output_path,
        )

    track_infos = get_lyrics(query, track_list)
    return track_infos
