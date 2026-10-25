"""Build the committed LLM recordings in ``data/cache/demo/`` by running the REAL Reader/Drafter code paths.

    uv run python -m llm.recordings            # hand-written outputs (no API key needed; provenance "hand-written")
    uv run python -m llm.recordings --live     # real calls (needs ANTHROPIC_API_KEY; counts against LLM_CAP_USD)

Each recording's cache key comes from the same prompt builders the tests and the server use, so a prompt change
makes the offline tests fail with ``offline_miss`` until this script is re-run. ``data/cache/demo/INDEX.json`` maps
each key to a human label.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
from pydantic import BaseModel

from llm.client import (
    DEFAULT_CACHE_DIR,
    DEMO_CACHE_DIR,
    AnthropicBackend,
    LlmClient,
    LlmRequest,
    RawResponse,
    ScriptedBackend,
)

AUTHORED_AT = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)   # when the hand-written recordings were written


@dataclass
class Recording:
    label: str
    role: str
    run: Callable[[Any], Any]          # run(component built on the given client) -> anything
    output: Any                        # hand-written structured output (dict) or text (str)
    schema: type[BaseModel] | None


def hand_response(output: Any, schema: type[BaseModel] | None) -> RawResponse:
    if schema is not None:
        parsed = schema.model_validate(output).model_dump(mode="json")
        text = orjson.dumps(parsed).decode()
    else:
        parsed, text = None, str(output)
    return RawResponse(model="claude-opus-5-5", request_id="hand-written", message_id="hand-written",
                       stop_reason="end_turn", stop_details=None, text=text, parsed=parsed,
                       usage={"input_tokens": 0, "output_tokens": 0}, fallback=False)


def reader_recordings() -> Iterator[Recording]:
    from llm.demo_inputs import READER_DOCS
    from llm.reader import SCHEMAS, Reader, ReaderContext

    for doc in READER_DOCS:
        schema = SCHEMAS[doc.source.kind]
        yield Recording(doc.label, "reader",
                        # no 8 s server budget while recording: a live call that times out would record nothing
                        lambda client, d=doc: Reader(client, timeout_s=None).read(d.source,
                                                                                   ReaderContext(**(d.context or {}))),
                        doc.output, schema)


def drafter_recordings() -> Iterator[Recording]:
    try:
        from llm.demo_drafts import DRAFTER_RECORDINGS  # type: ignore[import-not-found]  (F6, another agent)
    except ImportError:
        return iter(())
    return iter(DRAFTER_RECORDINGS())


PERSONA_OUTPUTS = {   # question id (contracts/fixtures/api/questions.json) → the persona's hand-written answer
    "Q-1": {"option": "Pay €600 cash; the voucher stays as goodwill",
            "ruling": "No signed acceptance, no offset: pay €600 cash; the voucher stays as goodwill."},
    "Q-2": {"option": "Extraordinary if no aircraft within 3 h of STD and the earliest reroute was offered",
            "ruling": "A return sector of a storm-cancelled rotation is extraordinary only if no aircraft and crew "
                      "could operate it within 3 h of STD, and passengers were offered the earliest reroute on any "
                      "carrier (C-74/19)."},
    "Q-3": {"option": "Keep the expected tail until the six-year limitation",
            "ruling": "Never release the tail. At M12 keep (ultimate − M12 rate) × entitlement until the six-year "
                      "limitation."},
}


def demo_questions() -> list[Any]:
    from contracts.models import Question
    path = DEMO_CACHE_DIR.parents[2] / "contracts" / "fixtures" / "api" / "questions.json"
    return [Question.model_validate(q) for q in orjson.loads(path.read_bytes())]


def persona_recordings() -> Iterator[Recording]:
    from llm.personas import PersonaAnswer, PersonaBench
    for q in demo_questions():
        if q.id in PERSONA_OUTPUTS:
            yield Recording(f"persona_{q.id}", "persona", lambda client, q=q: PersonaBench(client).answer(q),
                            PERSONA_OUTPUTS[q.id], PersonaAnswer)


def all_recordings() -> list[Recording]:
    return [*reader_recordings(), *drafter_recordings(), *persona_recordings()]


def record(dest: Path = DEMO_CACHE_DIR, *, live: bool = False, only: str | None = None) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for rec in all_recordings():
        if only and only not in rec.label:
            continue
        keys: list[str] = []

        def respond(req: LlmRequest, r: Recording = rec) -> RawResponse:
            return hand_response(r.output, r.schema)

        backend = AnthropicBackend() if live else ScriptedBackend(respond, provenance="hand-written")
        client = LlmClient(mode="live", cache_dir=dest, read_dirs=[], backend=backend,
                           clock=(lambda: datetime.now(UTC)) if live else (lambda: AUTHORED_AT),
                           spend_dir=DEFAULT_CACHE_DIR)          # the spend ledger never lands in the demo dir
        def spy(*a: Any, _call: Any = client.call, _keys: list[str] = keys, **k: Any) -> Any:
            parsed, record_ = _call(*a, **k)
            _keys.append(record_.prompt_hash)
            return parsed, record_

        client.call = spy  # type: ignore[method-assign]
        rec.run(client)
        if not keys:
            if live:     # a refusal, timeout or unusable live answer: keep going, report it, record the rest
                print(f"recording {rec.label!r}: no usable live answer; not recorded", file=sys.stderr)
                continue
            raise RuntimeError(f"recording {rec.label!r} made no successful LLM call (bad hand-written output?)")
        for k in keys:
            prev = index.get(k, {}).get("label")
            index[k] = {"label": f"{prev} + {rec.label}" if prev and prev != rec.label else rec.label,
                        "role": rec.role, "provenance": "live" if live else "hand-written"}
    path = dest / "INDEX.json"
    old: dict[str, Any] = orjson.loads(path.read_bytes()) if (only and path.exists()) else {}
    old.update(index)
    dest.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(old, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")
    return index


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="call the API instead of writing hand-written outputs")
    ap.add_argument("--only", help="only recordings whose label contains this")
    ap.add_argument("--dest", type=Path, default=DEMO_CACHE_DIR)
    args = ap.parse_args(argv)
    idx = record(args.dest, live=args.live, only=args.only)
    print(f"wrote {len(idx)} recordings to {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
