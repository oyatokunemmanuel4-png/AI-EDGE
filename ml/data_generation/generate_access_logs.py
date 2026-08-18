from __future__ import annotations

import argparse

from toget_data.synthetic_access import generate_access_events, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic access-plane events.")
    parser.add_argument("--events", type=int, default=1000, help="Number of events to generate.")
    parser.add_argument("--anomaly-rate", type=float, default=0.08, help="Injected anomaly rate.")
    parser.add_argument("--seed", type=int, default=740, help="Random seed.")
    parser.add_argument(
        "--output",
        default="data/raw/access/synthetic_access_events.jsonl",
        help="Output JSONL path.",
    )
    args = parser.parse_args()

    events = generate_access_events(args.events, anomaly_rate=args.anomaly_rate, seed=args.seed)
    output_path = write_jsonl(events, args.output)
    anomalies = sum(event.is_anomaly for event in events)
    print(f"Wrote {len(events)} events to {output_path} ({anomalies} injected anomalies).")


if __name__ == "__main__":
    main()
