"""python -m cmatch {codes,slots,registry,confirm,link-values,link-concepts,emit,report}"""
import argparse
import importlib
import sys

from .config import Config

STAGES = {  # stage → module with run(cfg, **options)
    "codes": "lindas", "slots": "slots", "registry": "seed", "confirm": "confirm",
    "link-values": "linkvalues", "link-concepts": "concepts", "emit": "emit", "report": "report", "tune": "tune",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cmatch", description=__doc__)
    ap.add_argument("stage", choices=list(STAGES))
    ap.add_argument("--force", action="store_true", help="codes: refetch every list")
    args = ap.parse_args(argv)
    cfg = Config.load()
    module = importlib.import_module(f".{STAGES[args.stage]}", __package__)
    if args.stage == "codes":
        module.run(cfg, force=args.force)
    else:
        module.run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
