import logging
import os
from collections import OrderedDict

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from tqdm import tqdm

from lyrics_search.utils import chunks, yes_no_prompt

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


def spotify_add_tracks_to_playlist(playlist_id, track_ids):
    # Spotify won't allow us to add more than 100 tracks at a time
    track_chunks = chunks(track_ids, 100)
    for i, track_chunk in enumerate(track_chunks, 1):
        USER_SPOTIFY.user_playlist_add_tracks(
            user=SPOTIFY_USER_ID, playlist_id=playlist_id, tracks=track_chunk
        )


def spotify_delete_existing_playlists(playlist_name, no_input=False):
    playlists = get_spotify_user_playlists()
    existing_playlists = [
        playlist for playlist in playlists if playlist_name == playlist["name"]
    ]
    if existing_playlists and not no_input:
        print("The following playlists already exist with the same name:")
        for p in existing_playlists:
            print(f"  {p['name']} ({p['id']}): {p['tracks']['total']} tracks")
        if not yes_no_prompt(
            "Do you want to delete all of the above playlists and create a new one?"
        ):
            return False

    for playlist in existing_playlists:
        USER_SPOTIFY.user_playlist_unfollow(SPOTIFY_USER_ID, playlist["id"])
        LOGGER.debug(f"Deleted playlist {playlist['name']} ({playlist['id']})")


def create_spotify_playlist(query, playlist_name, track_ids):
    """Create Spotify playlist of given name, with given tracks."""

    if len(track_ids) == 0:
        raise ValueError(
            f"Refusing to create empty Spotify playlist '{playlist_name}'. "
            "No changes have been made."
        )

    do_continue = True
    do_continue = spotify_delete_existing_playlists(playlist_name)

    if do_continue:
        create_playlist_result = USER_SPOTIFY.user_playlist_create(
            SPOTIFY_USER_ID,
            name=playlist_name,
            public=False,
            description=create_playlist_description(query),
        )
        tqdm.write(f"Created playlist {playlist_name}")
        spotify_add_tracks_to_playlist(create_playlist_result["id"], track_ids)
        tqdm.write(
            f"Successfully created playlist {playlist_name} and exported "
            f"{len(to_add)}/{len(track_infos)} tracks "
        )


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
    results = SPOTIPY.search(q=query, type="track", limit=50)
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


def export(query, playlist_name, track_infos, create_playlist=True):
    results = OrderedDict()
    to_add = {}
    # Create a set of each unique artist/track name pair. Use the "cleaned" track name (this
    # strips out things in parentheses, for example). This avoid unnecessecary duplicate queries
    # to spotify. NOTE: This obviously assumes that a given track title is unique per artist, which
    # is not true. However, it is prefereable doing it this way vs. getting a bunch of duplicate
    # results for the much more common case of the same song existing on multiple albums per artist
    to_query = {
        (track_info["clean_artist"], track_info["clean_track"]): track_info
        for track_info in track_infos
    }
    to_query = sorted(to_query.items(), key=lambda x: x[1]["score"], reverse=True)
    for (artist, track), track_info in tqdm(to_query, unit="track"):
        # TODO: Filter for song names that closely match our query!!!
        item = search_spotify_for_track(artist, track)
        if item:
            to_add[item["id"]] = item

            formatted_item = {
                "artists": [artist["name"] for artist in item["artists"]],
                "id": item["id"],
                "name": item["name"],
            }
        else:
            formatted_item = None
        results[track_info["track_id"]] = {
            "musixmatch": track_info,
            "spotify": formatted_item,
        }

    if create_playlist:
        create_spotify_playlist(
            query=query,
            playlist_name=playlist_name,
            track_ids=list(to_add.keys()),
        )

    else:
        LOGGER.debug(f"Skipping creation of Spotify playlist '{playlist_name}'")

    return to_add, results


def create_playlist_description(query):
    repo_url = os.getenv("LR_REPO_URL", "<none>")
    return (
        f"{query} playlist! Created via an automated script; author does not endorse contents. "
        f"Sorted in rough order of {query}-ness. "
        f"See {repo_url} for more details."
    )
