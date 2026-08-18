"""CLI to generate a synthetic labelled governance-document dataset."""

from __future__ import annotations

import argparse

from ml.toget_data.synthetic_content import generate_content_documents, write_jsonl


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic content-plane documents.")
    ap.add_argument("--count", type=int, default=2000, help="Number of documents.")
    ap.add_argument("--seed", type=int, default=740, help="Random seed.")
    ap.add_argument("--output", required=True, help="Output JSONL path.")
    args = ap.parse_args()

    docs = generate_content_documents(args.count, seed=args.seed)
    path = write_jsonl(docs, args.output)
    print(f"Wrote {len(docs)} documents to {path}")


if __name__ == "__main__":
    main()
