from pathlib import Path

DEFAULT_RESULTS_PATH = Path("./results")
DEFAULT_ALLOWED_LANGUAGES = ["en"]
DEFAULT_BANNED_WORDS = [
    "instrumental",
    "karaoke",
    "originally performed",
    "(live)",
    "(skit)",
    "live in",
    "live at",
    "in the style of",
    "tribute to",
    "remix",
]

DEFAULT_PER_WORD_SOFT_RESULT_LIMIT = 1000
DEFAULT_PER_WORD_HARD_RESULT_LIMIT = 10000
