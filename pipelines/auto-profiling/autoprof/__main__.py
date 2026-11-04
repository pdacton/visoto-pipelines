"""python -m autoprof {resolve,fetch,profile,emit,report}"""
import argparse
import sys

from .config import Config

STAGES = ["resolve", "fetch", "profile", "emit", "report"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoprof", description=__doc__)
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("--only", help="profile: comma-separated group ids")
    args = ap.parse_args(argv)
    cfg = Config.load()
    if args.stage == "resolve":
        from . import resolve
        resolve.run(cfg)
    elif args.stage == "fetch":
        from . import fetch
        fetch.run(cfg)
    elif args.stage == "profile":
        from . import profile
        profile.run(cfg, only=set(args.only.split(",")) if args.only else None)
    elif args.stage == "emit":
        from . import emit
        emit.run(cfg)
    elif args.stage == "report":
        from . import report
        report.run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
