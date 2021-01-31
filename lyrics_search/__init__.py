from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

from lyrics_search.backends import musixmatch
from lyrics_search.frontends import spotify
