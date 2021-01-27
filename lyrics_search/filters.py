import logging

import cld3

from .defaults import DEFAULT_ALLOWED_LANGUAGES, DEFAULT_BANNED_WORDS

LOGGER = logging.getLogger(__name__)


def lyrics_dont_contain_query(num_query_references):
    return num_query_references == 0


def contains_banned_words(
    track_name, artist_name, album_name, banned_words=DEFAULT_BANNED_WORDS
):
    ret = any(
        banned_word
        for banned_word in banned_words
        for field_value in [track_name, artist_name, album_name]
        if banned_word in field_value
    )
    # print("banned words", ret)
    return ret


def lyrics_are_not_in_allowed_language(lyrics, languages=DEFAULT_ALLOWED_LANGUAGES):
    language_probability = cld3.get_language(lyrics)
    # if language_probability:
    #     tqdm.write(
    #         f"cld3 thinks that {repr(lyrics[:50])} is {language_probability.language} "
    #         f"({language_probability.probability:.2%})"
    #     )
    # else:
    #     LOGGER.warning(f"cld3.get_language failed to detect language for {lyrics=}")
    return not (
        not language_probability
        or language_probability.language in languages
        or not language_probability.is_reliable
    )


def artist_name_contains_query(query, artist_name):
    return query in artist_name
