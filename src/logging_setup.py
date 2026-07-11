"""
logging_setup.py — configure logging ONCE for the whole app.
Logs go to BOTH the screen and a file, with timestamps + severity levels.
"""
import logging
from config import LOG_LEVEL, LOG_FILE

def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    root.handlers.clear()                 # avoid duplicate logs if called twice

    # handler 1: the screen (console)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(console)

    # handler 2: a permanent log file
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(file_handler)

    # quiet down chatty third-party libraries
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

def get_logger(name):
    """Every module calls this to get its own named logger."""
    return logging.getLogger(name)