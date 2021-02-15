import json
import logging

LOGGER = logging.getLogger(__name__)


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def save_json(data, path):
    path.parent.mkdir(exist_ok=True)
    LOGGER.debug(f"Saving JSON to '{str(path)}'")
    with open(path, "w") as file:
        json.dump(data, file, indent=2)


def load_json(path):
    LOGGER.debug(f"Loading JSON from '{str(path)}'")
    with open(path) as file:
        return json.load(file)


# TODO: re.sub
def normalize_query(query):
    return query.replace(" ", "_")


# TODO: untested
def yes_no_prompt(prompt, default_yes=False):
    choices = "([y]/n) " if default_yes else "(y/[n])"
    response = input(f"{prompt} {choices}").strip().lower()
    if response in ["y", "yes"] or (not response and default_yes):
        return True
    elif response in ["n", "no"] or (not response and not default_yes):
        return False
    return yes_no_prompt(prompt, default_yes)


def choices_prompt(prompt, choices, choice_type=int):
    response = choice_type(input(f"{prompt.strip()} ").strip())
    if response not in choices:
        return choices_prompt(prompt, choices, choice_type)

    return response


def order_by_key(iterable_of_dicts, order_by):
    if order_by.startswith("-"):
        reverse = True
        order_by = order_by[1:]
    else:
        reverse = False

    return sorted(iterable_of_dicts, key=lambda item: item[order_by], reverse=reverse)


def load_word_list(path):
    with open(path) as file:
        contents = file.read()
    return contents.splitlines()


def slicer(iterable, size):
    for i in range(0, len(iterable) - size + 1):
        yield (iterable[:i], iterable[i + 1 : i + size + 1], iterable[i + size + 1 :])


def words_to_phrases(words):
    phrases = []
    for i, num in enumerate(words, 0):
        for window in slicer(words, i):
            phrases.append(window)
    return phrases
