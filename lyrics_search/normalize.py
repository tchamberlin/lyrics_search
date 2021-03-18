import logging
import re

LOGGER = logging.getLogger(__name__)

PARENTHETICAL_REGEX = re.compile(r"(\[.*\])?(\{.*\})?(\<.*\>)?(\(.*\))?")
WHITESPACE_REGEX = re.compile(r"[^\w#\'\"]")
LYRICS_CRUFT_REGEX = re.compile(r"\*+.*\*+\s+\(\d+\)")


def clean_track_field(value):
    """Clean the given track name.

    1. Remove parenthetical statements (e.g. remove bracketed text from "track name [cover by foo]")
    2. Remove featured artists from track name (e.g. "feat. FOO")
    """

    clean_value = PARENTHETICAL_REGEX.sub("", value).strip()
    try:
        feat_start = clean_value.lower().index("feat.")
    except ValueError:
        pass
    else:
        clean_value = clean_value[:feat_start].strip()

    if value != clean_value:
        LOGGER.debug(f"Cleaned {value=} to {clean_value=}")

    return clean_value
