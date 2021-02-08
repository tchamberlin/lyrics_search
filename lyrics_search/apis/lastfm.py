import logging
import math
import os
import time

import requests
from tqdm import tqdm

LOGGER = logging.getLogger(__name__)
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")

LASTFM_PAGE_SIZE = 1000
LASTFM_API_TRACK_SEARCH_URL = r"http://ws.audioscrobbler.com/2.0/"
LASTFM_API_BASE_PARAMS = {
    "api_key": LASTFM_API_KEY,
    "format": "json",
    "limit": LASTFM_PAGE_SIZE,
}
LASTFM_API_BASE_HEADERS = {
    "User-Agent": "playlist-gen / 0.1 WIP",
}


def request_json(url=LASTFM_API_TRACK_SEARCH_URL, params=dict(), **kwargs):
    response = requests.get(url, params={**LASTFM_API_BASE_PARAMS, **params}, **kwargs)
    return response.json()


def search_tracks_exact(
    query,
    max_results=5000,
):
    limit = LASTFM_PAGE_SIZE
    all_items = []
    results = request_json(
        # TODO: better quoting
        params={"track": f'"{query}"', "method": "track.search"},
    )
    extracted = results["results"]["trackmatches"]["track"]
    all_items.extend(extracted)
    total = int(results["results"]["opensearch:totalResults"])
    num_pages = math.ceil(total / limit)
    LOGGER.warning(
        f"Total {total} results across {num_pages} pages of {limit} results each"
    )
    for track in extracted:
        yield track
    max_pages = math.ceil(max_results / limit)
    if num_pages > max_pages:
        LOGGER.debug(f"Limiting pages from {num_pages=} to {max_pages=}")
        num_pages = max_pages
    current_page = 2
    for page in tqdm(
        range(current_page, num_pages + 1), initial=1, unit="page", position=0
    ):
        time.sleep(0.1)
        LOGGER.warning(f"Fetching page {page}")
        results = request_json(
            # TODO: better quoting
            params={"track": query, "page": current_page, "method": "track.search"},
        )
        extracted = results["results"]["trackmatches"]["track"]
        all_items.extend(extracted)
        for track in extracted:
            yield track
        current_page += 1

    # return all_items


def format_track_dict(track_dict):
    return f"{track_dict['name']} - {track_dict['artist']} ({track_dict['listeners']})"
