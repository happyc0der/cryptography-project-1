"""Evaluation: how many pads does each protocol waste, and when does it stall?

Every row aggregates over delivery orders, network pressure and seeds, and
reports the *worst* case as well as the average - a protocol that is only frugal
on a well-behaved network has not solved the problem.

    python eval_protocol.py                # default grid, writes summary.csv
    python eval_protocol.py --n 20000 --seeds 5
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time

from protocol import (
    BaseProtocol,
    ChunkReserveProtocol,
    GrantProtocol,
    StaticPartitionProtocol,
)
from simulation import SCHEDULES, Schedule, run

PROTOCOLS = {
    "chunk-reserve": ChunkReserveProtocol,
    "grant": GrantProtocol,
    "static-partition": StaticPartitionProtocol,
}
DELIVERIES = ["random", "adversarial"]
PRESSURES = ["eager", "lazy"]

# `us_per_send` is deliberately not written to the CSV: it is wall-clock and so
# differs on every run and every machine, which would make the committed
# summary.csv show a spurious diff each time anyone runs the evaluation. Every
# column below is a deterministic function of (protocol, m, d, n, schedule), so
# re-running the grid reproduces the file byte for byte. The timing is reported
# on stdout instead, where a machine-dependent number belongs.
FIELDS = [
    "protocol",
    "m",
    "d",
    "n",
    "schedule",
    "avg_wasted",
    "max_wasted",
    "proved_bound",
    "max_blocked",
    "avg_sends",
]


def measure(
    cls: type[BaseProtocol],
    *,
    n: int,
    d: int,
    m: int,
    schedule: str,
    seeds: int,
) -> dict[str, object]:
    """Run one cell of the grid over every delivery order and pressure."""
    wastes, blocks, sends, per_send = [], [], [], []
    bound = None
    for delivery in DELIVERIES:
        for pressure in PRESSURES:
            for seed in range(seeds):
                proto = cls(n, d, m)
                bound = getattr(proto, "waste_bound", lambda: None)()
                start = time.perf_counter()
                result = run(
                    proto,
                    schedule=Schedule(schedule, m),
                    delivery=delivery,
                    pressure=pressure,
                    seed=seed,
                )
                elapsed = time.perf_counter() - start
                wastes.append(result.wasted)
                blocks.append(result.blocked)
                sends.append(result.sends)
                per_send.append(1e6 * elapsed / max(result.sends, 1))
    return {
        "protocol": cls.__name__,
        "m": m,
        "d": d,
        "n": n,
        "schedule": schedule,
        "avg_wasted": round(statistics.mean(wastes), 1),
        "max_wasted": max(wastes),
        "proved_bound": bound if bound is not None else "",
        "max_blocked": max(blocks),
        "avg_sends": round(statistics.mean(sends), 1),
        "us_per_send": round(statistics.mean(per_send), 2),
    }


def table(rows: list[dict[str, object]], columns: list[str], title: str) -> None:
    print(f"\n{title}")
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    line = "  ".join(c.ljust(widths[c]) for c in columns)
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in columns))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default="summary.csv")
    args = ap.parse_args()

    rows = []
    for name, cls in PROTOCOLS.items():
        for m in (5, 9):
            for d in (1, 2, 5, 10, 20):
                for schedule in SCHEDULES:
                    row = measure(
                        cls,
                        n=args.n,
                        d=d,
                        m=m,
                        schedule=schedule,
                        seeds=args.seeds,
                    )
                    row["protocol"] = name
                    rows.append(row)

    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # --- headline: the case the static partition cannot handle ---------------
    focus = [
        r
        for r in rows
        if r["m"] == 5 and r["d"] == 5 and r["schedule"] in ("single", "skewed")
    ]
    table(
        focus,
        [
            "protocol",
            "schedule",
            "avg_wasted",
            "max_wasted",
            "proved_bound",
            "max_blocked",
            "avg_sends",
        ],
        f"m = 5, d = 5, n = {args.n}: one party (or mostly one) does the talking",
    )

    # --- waste vs d, worst case over every schedule --------------------------
    worst_by_d = []
    for name in PROTOCOLS:
        for d in (1, 2, 5, 10, 20):
            cells = [
                r for r in rows if r["protocol"] == name and r["m"] == 5 and r["d"] == d
            ]
            worst_by_d.append(
                {
                    "protocol": name,
                    "d": d,
                    "worst_wasted": max(c["max_wasted"] for c in cells),
                    "proved_bound": cells[0]["proved_bound"],
                    "worst_blocked": max(c["max_blocked"] for c in cells),
                }
            )
    table(
        worst_by_d,
        ["protocol", "d", "worst_wasted", "proved_bound", "worst_blocked"],
        f"m = 5, n = {args.n}: worst case over every schedule, "
        "delivery order and pressure",
    )

    # --- the point of the design: waste does not grow with n -----------------
    scaling = []
    for n in (args.n, args.n * 4, args.n * 16):
        # one_shot, not single: the flatness claim should be made about the
        # worst case, not a mild one.
        cell = measure(
            ChunkReserveProtocol, n=n, d=5, m=5, schedule="one_shot", seeds=1
        )
        cell["protocol"] = "chunk-reserve"
        scaling.append(cell)
    table(
        scaling,
        ["protocol", "n", "max_wasted", "proved_bound", "avg_sends"],
        "chunk-reserve, m = 5, d = 5: waste is flat in n",
    )

    slowest = max(rows, key=lambda r: r["us_per_send"])
    print(
        f"\nThroughput: {statistics.mean([r['us_per_send'] for r in rows]):.1f} us "
        f"per message on average, {slowest['us_per_send']:.1f} us at worst "
        f"({slowest['protocol']}, m={slowest['m']}, d={slowest['d']}). "
        "Machine-dependent, so it is not written to the CSV."
    )
    print(f"Full grid ({len(rows)} rows) written to {args.out}")


if __name__ == "__main__":
    main()
