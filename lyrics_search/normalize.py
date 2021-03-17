import logging
import re

LOGGER = logging.getLogger(__name__)

PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")


def clean_track(track):
    """Clean the given track name.

    1. Remove parenthetical statements (e.g. remove bracketed text from "track name [cover by foo]")
    2. Remove featured artists from track name (e.g. "feat. FOO")
    """

    clean_track = PARENTHETICAL_REGEX.sub("", track).strip()
    try:
        feat_start = clean_track.lower().index("feat.")
    except ValueError:
        pass
    else:
        clean_track = clean_track[:feat_start].strip()

    if track != clean_track:
        LOGGER.debug(f"Cleaned {track=} to {clean_track=}")

    return clean_track
