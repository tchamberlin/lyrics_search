from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

from lyrics_search.apis import musixmatch, spotify
