"""Logging in the style of scripts/lib.sh: `[HH:MM:SS] message` on stderr."""
import sys
import time


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)
