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


def yes_no_prompt(prompt, default_yes=False):
    choices = "([y]/n) " if default_yes else "(y/[n])"
    response = input(f"{prompt} {choices}").strip().lower()
    return response in ["y", "yes"] or (not response and default_yes)
