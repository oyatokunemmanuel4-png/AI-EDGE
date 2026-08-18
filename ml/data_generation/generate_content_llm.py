"""Generate a labelled governance-document dataset using the Anthropic API.

Higher-quality, more realistic alternative to scripts/generate_content_docs.py
(which stays as the offline/CI fallback). Requires ANTHROPIC_API_KEY in the
environment and the `llm` extra installed (`pip install -e ".[llm]"`).

Examples:
  # Train split
  python scripts/generate_content_llm.py --count 3000 --seed 42 \
      --out data/raw/content/generated_train.jsonl
      
      
      
      
  # Test split, de-duplicated against train (avoids leakage)
  python scripts/generate_content_llm.py --count 750 --seed 7 \
      --out data/raw/content/generated_test.jsonl \
      --dedupe-against data/raw/content/generated_train.jsonl

Model defaults to claude-sonnet-5 (good quality/cost for generation). For the
cheapest runs, `--model claude-haiku-4-5` is perfectly adequate for synthesizing
documents.

Shows live per-call progress, and on Ctrl+C it saves whatever has been generated
so far (partial output) instead of losing the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path

from toget_data.synthetic_content_llm import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    build_prompt,
    build_records,
    dedupe,
    plan_specs,
)


def _supports_effort(model: str) -> bool:
    """effort is unsupported on Haiku 4.5, Sonnet 4.5/4.0, and Claude 3.x."""
    m = model.lower()
    return not any(s in m for s in ("haiku", "sonnet-4-5", "sonnet-4-0", "claude-3"))


def _load_seen(path: Path):
    """Preload dedup sets from an existing JSONL (for cross-split dedup)."""
    from toget_data.synthetic_content_llm import _normalise, _opening_signature

    seen_norm: set[str] = set()
    seen_sig: set[str] = set()
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                text = json.loads(line)["text"]
                seen_norm.add(_normalise(text))
                seen_sig.add(_opening_signature(text))
    return seen_norm, seen_sig


async def _generate(args) -> None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY
    specs = plan_specs(
        args.count, per_call=args.per_call, hard_fraction=args.hard_fraction, seed=args.seed
    )
    print(f"model={args.model} calls={len(specs)} target={args.count} "
          f"concurrency={args.concurrency}")

    sem = asyncio.Semaphore(args.concurrency)
    by_label: dict[str, list[str]] = defaultdict(list)
    stats = {"refusals": 0, "errors": 0}

    # Structured outputs work on all current models; `effort` only on some.
    output_config: dict = {"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}}
    if _supports_effort(args.model):
        output_config["effort"] = "low"

    async def run(spec):
        async with sem:
            try:
                resp = await client.messages.create(
                    model=args.model,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": build_prompt(spec)}],
                    output_config=output_config,
                )
            except Exception as exc:  # noqa: BLE001 - record any per-call API/network error
                return spec.label, [], "error", str(exc)
            if resp.stop_reason == "refusal":
                return spec.label, [], "refusal", ""
            text = next((b.text for b in resp.content if b.type == "text"), "")
            try:
                docs = json.loads(text)["documents"]
            except (json.JSONDecodeError, KeyError, TypeError):
                return spec.label, [], "error", "could not parse response JSON"
            texts = [d["text"] for d in docs if isinstance(d, dict) and d.get("text")]
            return spec.label, texts, "ok", ""

    # Run with live progress, and write whatever we have even on Ctrl+C.
    print(f"generating {len(specs)} calls (progress below; Ctrl+C keeps partial output)\n", flush=True)
    tasks = [asyncio.create_task(run(s)) for s in specs]
    completed = 0
    try:
        for fut in asyncio.as_completed(tasks):
            label, texts, status, detail = await fut
            completed += 1
            if status == "error":
                stats["errors"] += 1
            elif status == "refusal":
                stats["refusals"] += 1
            by_label[label].extend(texts)
            total_docs = sum(len(v) for v in by_label.values())
            flag = "" if status == "ok" else f"  <{status}: {detail}>"
            print(f"[{completed:>4}/{len(specs)}] {label:<9} +{len(texts):>2} docs | "
                  f"total={total_docs} refusals={stats['refusals']} errors={stats['errors']}{flag}",
                  flush=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n! interrupted — cancelling remaining calls and saving partial output...", flush=True)
        for t in tasks:
            t.cancel()

    _finalize(by_label, args, stats)


def _finalize(by_label: dict[str, list[str]], args, stats: dict[str, int]) -> None:
    print(f"\nraw generated: { {k: len(v) for k, v in by_label.items()} } "
          f"(refusals={stats['refusals']}, errors={stats['errors']})", flush=True)

    # Dedup within run + against an existing split, sharing the seen sets.
    seen_norm, seen_sig = _load_seen(Path(args.dedupe_against)) if args.dedupe_against else (set(), set())
    deduped = {
        label: dedupe(texts, seen_norm=seen_norm, seen_sig=seen_sig)
        for label, texts in by_label.items()
    }

    if not args.no_balance and deduped:
        floor = min((len(v) for v in deduped.values() if v), default=0)
        deduped = {k: v[:floor] for k, v in deduped.items()}

    labelled = [(label, text) for label, texts in deduped.items() for text in texts]
    records = build_records(labelled, seed_tag=str(args.seed))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n")

    print(f"final: {dict(Counter(r['label'] for r in records))} -> {len(records)} docs at {out}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM-generated governance-document dataset.")
    ap.add_argument("--count", type=int, default=3000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--per-call", type=int, default=10)
    ap.add_argument("--hard-fraction", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=740)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--dedupe-against", default=None, help="Existing JSONL to dedupe against.")
    ap.add_argument("--no-balance", action="store_true", help="Skip trimming classes to equal size.")
    args = ap.parse_args()

    asyncio.run(_generate(args))


if __name__ == "__main__":
    main()
