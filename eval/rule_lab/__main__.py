"""Print evidence, or start the optional isolated viewer."""

import argparse

import orjson

from eval.rule_lab.runner import PRESETS, run_lab


def main() -> int:
    parser = argparse.ArgumentParser(description="StormCheck rule-specific regression evidence (offline).")
    parser.add_argument("--preset", choices=list(PRESETS), default="scoped")
    parser.add_argument("--check", action="store_true", help="Exit 1 when the candidate is blocked.")
    parser.add_argument("--serve", action="store_true", help="Open a separate localhost viewer.")
    parser.add_argument("--port", type=int, default=4186)
    args = parser.parse_args()
    if args.serve:
        import uvicorn

        uvicorn.run("eval.rule_lab.app:app", host="127.0.0.1", port=args.port)
        return 0
    report = run_lab(args.preset)
    print(orjson.dumps(report, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode())
    return int(args.check and report["verdict"] == "blocked")


if __name__ == "__main__":
    raise SystemExit(main())
