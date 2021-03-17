import logging
import math
import os
import re
import string
from collections import OrderedDict
from datetime import datetime

import spotipy
from fuzzywuzzy import fuzz
from spotipy.oauth2 import SpotifyClientCredentials
from tqdm import tqdm
from unidecode import unidecode

from lyrics_search.filters import contains_banned_word
from lyrics_search.normalize import PARENTHETICAL_REGEX
from lyrics_search.utils import (
    choices_prompt,
    chunks,
    load_json,
    normalize_query,
    order_by_key,
    save_json,
)

LOGGER = logging.getLogger(__name__)

SPOTIFY_USER_ID = os.getenv("SPOTIFY_USER_ID")
SPOTIPY = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials())

_token = spotipy.util.prompt_for_user_token(
    SPOTIFY_USER_ID, scope="playlist-modify-private playlist-read-private"
)
if not _token:
    raise ValueError(f"Failed to get token for {SPOTIFY_USER_ID}")

USER_SPOTIFY = spotipy.Spotify(auth=_token)
USER_SPOTIFY.trace = False

# Spotify won't allow us to add more than 100 tracks at a time
SPOTIFY_MAX_CHUNK_SIZE = 100
# Spotify search will return a max of 50 items at a time
SPOTIFY_API_SEARCH_LIMIT = 50
SPOTIFY_API_RESULTS_LIMIT = 1000


def spotify_add_tracks_to_playlist(playlist, track_ids, replace_existing=True):
    playlist_id = playlist["id"]
    if replace_existing:
        snapshot = USER_SPOTIFY.user_playlist_replace_tracks(
            user=SPOTIFY_USER_ID, playlist_id=playlist_id, tracks=[]
        )
        LOGGER.debug(
            f"Deleted all tracks in playlist {playlist['name']!r} ({playlist_id!r})"
        )
    track_chunks = chunks(track_ids, SPOTIFY_MAX_CHUNK_SIZE)
    for track_chunk in track_chunks:
        snapshot = USER_SPOTIFY.user_playlist_add_tracks(
            user=SPOTIFY_USER_ID, playlist_id=playlist_id, tracks=track_chunk
        )
        LOGGER.debug(
            f"Added {len(track_chunk)} tracks to playlist {playlist['name']!r}"
        )

    return snapshot


def delete_playlists(playlist_infos):
    for playlist in playlist_infos:
        USER_SPOTIFY.user_playlist_unfollow(SPOTIFY_USER_ID, playlist["id"])
        LOGGER.debug(f"Deleted playlist {playlist['name']} ({playlist['id']})")


def spotify_get_existing_playlist(playlist_name, no_input=False):
    playlists = get_spotify_user_playlists()
    existing_playlists = [
        playlist for playlist in playlists if playlist_name == playlist["name"]
    ]
    num_existing_playlists = len(existing_playlists)
    if num_existing_playlists > 1 and not no_input:
        print("The following playlists already exist with the same name:")
        choices = list(enumerate(existing_playlists, 1))
        for num, playlist in choices:
            print(
                f"  {num}) {playlist['name']} ({playlist['id']}): "
                f"{playlist['tracks']['total']} tracks"
            )

        choice = choices_prompt(
            "Which playlist would you like to use (will replace its entire "
            "contents with the new tracks)?",
            choices=[c for c in choices[0]],
        )
        # Choice is 1-indexed so we must subtract 1
        playlist = existing_playlists[choice - 1]
    elif num_existing_playlists == 1:
        LOGGER.debug(f"Exactly 1 existing playlist named {playlist_name}")
        playlist = existing_playlists[0]
    else:
        LOGGER.debug(f"No existing playlist(s) named {playlist_name}")
        playlist = None

    return playlist


def create_spotify_playlist(
    query, playlist_name, track_ids, replace_existing=True, description=None
):
    """Create Spotify playlist of given name, with given tracks."""

    if len(track_ids) == 0:
        raise ValueError(
            f"Refusing to create empty Spotify playlist '{playlist_name}'. "
            "No changes have been made."
        )

    if description is None:
        description = create_playlist_description(query)
    playlist = spotify_get_existing_playlist(playlist_name)

    if playlist is None:
        playlist = USER_SPOTIFY.user_playlist_create(
            SPOTIFY_USER_ID, name=playlist_name, public=False, description=description
        )

        tqdm.write(f"Creating playlist {playlist_name!r}")
    else:
        tqdm.write(f"Replacing existing playlist {playlist_name!r}")
        USER_SPOTIFY.user_playlist_change_details(
            SPOTIFY_USER_ID, playlist["id"], description=description
        )
    spotify_add_tracks_to_playlist(
        playlist, track_ids, replace_existing=replace_existing
    )
    return playlist["id"]


def get_spotify_user_playlists(limit=50):
    """Get all playlists from current Spotify user."""

    has_more = True
    offset = 0
    playlists = []
    while has_more:
        playlists_ = USER_SPOTIFY.current_user_playlists(limit=limit, offset=offset)
        has_more = bool(playlists_["next"])
        if has_more:
            offset += limit
        playlists.extend(playlists_["items"])

    return playlists


def search_spotify_for_track(artist, track):
    query = f"{artist} {track}"
    LOGGER.debug(f"Querying for {query}")
    results = SPOTIPY.search(q=query, limit=50)
    num_results = results["tracks"]["total"]
    LOGGER.debug(f"Found {num_results} results")

    item = None
    if num_results:
        if num_results == 1:
            item = results["tracks"]["items"][0]
            stub = "only track"
        elif num_results > 1:
            # TODO: Filter out live tracks, covers, etc.
            item = sorted(results["tracks"]["items"], key=lambda x: x["popularity"])[-1]
            stub = "most popular track"
        artists = [artist["name"] for artist in item["artists"]]
        LOGGER.debug(f"Added {stub} track '{item['name']}' by '{artists}' for {query=}")
    else:
        LOGGER.debug(f"Failed to find any results for {query=}")
    return item


def sort_playlist(playlist, key):
    """Sort the given Spotify `playlist` by `key`"""


def query_spotify_from_track_infos(track_infos, order_by=None):
    to_add = OrderedDict()
    # Create a set of each unique artist/track name pair. Use the "cleaned" track name (this
    # strips out things in parentheses, for example). This avoid unnecessecary duplicate queries
    # to spotify. NOTE: This obviously assumes that a given track title is unique per artist, which
    # is not true. However, it is prefereable doing it this way vs. getting a bunch of duplicate
    # results for the much more common case of the same song existing on multiple albums per artist
    to_query = {
        (track_info["clean_artist"], track_info["cleaned_track"]): track_info
        for track_info in track_infos
    }
    to_query = sorted(to_query.items(), key=lambda x: x[1]["score"], reverse=True)
    for (artist, track), track_info in tqdm(to_query, unit="track"):
        # TODO: Filter for song names that closely match our query!!!
        item = search_spotify_for_track(artist, track)
        if item:
            to_add[item["id"]] = item

    if order_by:
        ret = order_by_key(to_add.values(), order_by)
    else:
        ret = to_add
    return list(ret.values())


def create_playlist_description(query):
    repo_url = os.getenv("LR_REPO_URL", "<none>")
    return (
        f"{query} playlist! Created via an automated script; author does not endorse contents. "
        f"Sorted in rough order of {query}-ness. "
        f"See {repo_url} for more details."
    )


def spotify_deep_search(query):
    # TODO: Inefficient!
    initial_results = SPOTIPY.search(q=f"track:{query}", type="track", limit=1)
    all_results = []
    if initial_results["tracks"]["total"] > SPOTIFY_API_RESULTS_LIMIT:
        for year in tqdm(range(2010, datetime.now().year), unit="year", position=1):
            LOGGER.info(f"{year=}")
            for char in tqdm(string.ascii_lowercase, unit="char", position=2):
                LOGGER.info(f"{char=}")
                results = search_spotify(f"track:{query} year:{year} artist:{char}*")
                all_results.extend(results)

    return all_results


def spotify_deep_search_lazy(query):
    cleaned_query = unidecode(query)
    _query = (
        f"{query} OR {cleaned_query}"
        if query.lower() != cleaned_query.lower()
        else query
    )
    # TODO: Inefficient!
    initial_results = SPOTIPY.search(q=_query, type="track", limit=1)
    total_results = initial_results["tracks"]["total"]
    if total_results > SPOTIFY_API_RESULTS_LIMIT:
        for year in tqdm(
            reversed(range(2010, datetime.now().year)), unit="year", position=1
        ):
            LOGGER.info(f"{year=}")
            for char in tqdm(string.ascii_lowercase, unit="char", position=2):
                LOGGER.info(f"{char=}")

                results = search_spotify_lazy(
                    f"track:{_query} year:{year} artist:{char}*"
                )
                for result in results:
                    yield result

    else:
        for result in search_spotify_lazy(f"track:{query}"):
            yield result


def spotify_shallow_search(query):
    return search_spotify(f"track:{query}")


def search_spotify(
    query,
    type_="track",
    max_results=None,
    limit=SPOTIFY_API_SEARCH_LIMIT,
    **kwargs,
):
    all_items = []
    results = SPOTIPY.search(q=query, type=type_, limit=limit, **kwargs)
    all_items.extend(results["tracks"]["items"])
    total = results["tracks"]["total"]
    if max_results is not None and total > max_results:
        LOGGER.debug(f"Limiting results from {total=} to {max_results=}")
        total = max_results
    num_pages = math.ceil(total / limit)
    LOGGER.debug(
        f"Total {total} results across {num_pages} pages of {limit} results each"
    )
    max_pages = math.ceil(SPOTIFY_API_RESULTS_LIMIT / limit)
    if num_pages > max_pages:
        LOGGER.debug(f"Limiting pages from {num_pages=} to {max_pages=}")
        num_pages = max_pages
    offset = limit
    for page in tqdm(range(1, num_pages + 1), initial=1, unit="page", position=0):
        if offset >= SPOTIFY_API_RESULTS_LIMIT:
            LOGGER.warning(
                f"Reach Spotify API Offset limit of {SPOTIFY_API_RESULTS_LIMIT}; exiting"
            )
            break
        LOGGER.debug(f"Fetching page {page} ({offset=})")
        results = SPOTIPY.search(
            q=query, type=type_, offset=offset, limit=limit, **kwargs
        )
        all_items.extend(results["tracks"]["items"])
        offset = page * limit

    return all_items


def normalize_track_field(value):
    normalized = PARENTHETICAL_REGEX.sub("", value).strip().lower()
    try:
        feat_start = normalized.index("feat.")
    except ValueError:
        pass
    else:
        normalized = normalized[:feat_start].strip()

    if normalized != value:
        LOGGER.debug(f"Normalized value from {value=} to {normalized=}")
    return normalized


def filter_results(query, items, fast=True):
    filtered = []
    query = unidecode(query.lower())
    query_word_regex = re.compile(r"\b" + query + r"\b")
    for item in items:
        track = unidecode(item["name"]).lower()
        album = unidecode(item["album"]["name"]).lower()
        artists = [unidecode(a["name"]).lower() for a in item["artists"]]
        clean_track = normalize_track_field(track)

        track_contains_query = (
            bool(query_word_regex.match(clean_track))
            # TODO: Why was this here? seems bad
            # or fuzz.partial_token_sort_ratio(query, clean_track) > 85
        )
        filters = (
            (
                "banned_word_in_artist_field",
                [artist for artist in artists if contains_banned_word(artist)],
            ),
            ("banned_word_in_album_field", contains_banned_word(album)),
            ("banned_word_in_track_field", contains_banned_word(clean_track)),
            ("track_does_not_contain_query", not track_contains_query),
            (
                "artist_name_contains_query",
                (
                    # If the track name doesn't contain the query,
                    not track_contains_query
                    # AND one of the arists does, then evaluate to True
                    and any(artist for artist in artists if query in artist)
                ),
            ),
            (
                "album_name_contains_query",
                (
                    # If the track name doesn't contain the query,
                    not track_contains_query
                    # AND the album does, then evaluate to True
                    and query in album
                ),
            ),
            (
                "artist_name_fuzzy_matches_query",
                (
                    not track_contains_query
                    # AND one of the arists does, then evaluate to True
                    and any(
                        artist
                        for artist in artists
                        if fuzz.partial_token_sort_ratio(query, artist) > 85
                    )
                ),
            ),
            (
                "album_name_contains_query",
                (
                    # If the track name doesn't contain the query,
                    not track_contains_query
                    # AND the album does, then evaluate to True
                    and fuzz.partial_token_sort_ratio(query, album) > 85
                ),
            ),
        )

        if fast:
            do_add = not any(v for k, v in filters)
        else:
            filters = dict(filters)
            do_add = not any(filters.values())
            filters = filters.items()
        if do_add:
            filtered.append(item)
        else:
            LOGGER.info(
                f"Filtered out '{format_item(item)}' due to: "
                f"{[k for k, v in filters if v]}"
            )

    return filtered


def format_item(item):
    artists = ", ".join([a["name"] for a in item["artists"]])
    return f"{artists} | {item['album']['name']} | {item['name']}"


def gen_spotify_search_results_json_path(output_path, normalized_query):
    return output_path / f"{normalized_query}_spotify_search_results.json"


def search_and_filter(
    query, output_path, order_by="-popularity", fast=True, deep=False
):
    normalized_query = normalize_query(query)
    spotify_search_results_json_path = gen_spotify_search_results_json_path(
        output_path, normalized_query
    )

    if not spotify_search_results_json_path.exists():
        LOGGER.debug(f"Searching Spotify for {query!r}")
        if deep:
            spotify_search_results = spotify_deep_search(query)
        else:
            spotify_search_results = spotify_shallow_search(query)
        save_json(spotify_search_results, spotify_search_results_json_path)
    else:
        LOGGER.debug(
            "Skipping Spotify search; results are cached at "
            f"'{spotify_search_results_json_path}'"
        )
        spotify_search_results = load_json(spotify_search_results_json_path)

    filtered = filter_results(query, spotify_search_results, fast=fast)
    deduped = remove_duplicates(query, filtered)
    ordered = order_by_key(deduped, order_by)
    save_json(
        [format_item(item) for item in ordered],
        output_path / f"{normalized_query}_spotify_playlist.json",
    )
    return ordered


def remove_duplicates(query, items):
    compressed = {}
    for item in items:
        track = normalize_track_field(item["name"])
        # album = PARENTHETICAL_REGEX.sub("", item["album"]["name"]).strip().lower()
        artists = tuple(
            sorted((normalize_track_field(a["name"]) for a in item["artists"]))
        )

        key = (artists, track)
        existing = compressed.get(key, None)
        # If there is an existing track in `compressed`...
        if existing:
            do_add = False
            # If the existing album is a single (e.g. not a compilation),
            if existing["album"]["album_type"] == "single":
                # AND the new item is also a single, AND the new item is more popular, we add it
                if (
                    item["album"]["album_type"] == "single"
                    and item["popularity"] > existing["popularity"]
                ):
                    do_add = True
            # If it is NOT a single,
            else:
                # AND it is more popular than the existing one, we add it
                if item["popularity"] > existing["popularity"]:
                    do_add = True

            if do_add:
                LOGGER.debug(
                    f"Overwriting '{format_item(existing)}' (pop. {existing['popularity']}) "
                    f"with '{format_item(item)}' (pop. {item['popularity']})"
                )
                compressed[key] = item
        else:
            compressed[key] = item

    LOGGER.debug(f"De-dup'd {len(items)=} to {len(compressed)=}")
    return list(compressed.values())


def search_spotify_lazy(
    query,
    type_="track",
    max_results=None,
    limit=SPOTIFY_API_SEARCH_LIMIT,
    **kwargs,
):
    all_items = []
    results = SPOTIPY.search(q=query, type=type_, limit=limit, **kwargs)
    if results is None:
        raise ValueError("uh oh")
    for track in results["tracks"]["items"]:
        yield track
    all_items.extend(results["tracks"]["items"])
    total = results["tracks"]["total"]
    if max_results is not None and total > max_results:
        LOGGER.debug(f"Limiting results from {total=} to {max_results=}")
        total = max_results
    num_pages = math.ceil(total / limit)
    LOGGER.debug(
        f"Total {total} results across {num_pages} pages of {limit} results each"
    )
    max_pages = math.ceil(SPOTIFY_API_RESULTS_LIMIT / limit)
    if num_pages > max_pages:
        LOGGER.debug(f"Limiting pages from {num_pages=} to {max_pages=}")
        num_pages = max_pages
    offset = limit
    for page in tqdm(range(1, num_pages + 1), initial=1, unit="page", position=0):
        if offset >= SPOTIFY_API_RESULTS_LIMIT:
            LOGGER.warning(
                f"Reach Spotify API Offset limit of {SPOTIFY_API_RESULTS_LIMIT}; exiting"
            )
            break
        LOGGER.debug(f"Fetching page {page} ({offset=})")
        results = SPOTIPY.search(
            q=query, type=type_, offset=offset, limit=limit, **kwargs
        )
        for track in results["tracks"]["items"]:
            yield track
        all_items.extend(results["tracks"]["items"])
        offset = page * limit

    return all_items
