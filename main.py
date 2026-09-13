"""Walk-through demo of the chunk-reserve protocol.

    python main.py            # m = 5
    python main.py --m 9
"""

from __future__ import annotations

import argparse

from protocol import ChunkReserveProtocol, GrantProtocol, StaticPartitionProtocol
from simulation import Network, Schedule, run


def trace(n: int, d: int, m: int, steps: int = 14) -> None:
    """Hand-drive a few rounds so the reserve map can be watched moving."""
    proto = ChunkReserveProtocol(n, d, m)
    net = Network(d)
    print(
        f"n={n} pads, d={d}, m={m} parties -> "
        f"{proto.layout.count} chunks of c=d={proto.layout.c} pads\n"
    )
    print(f"{'event':<38}{'reserve map (chunk per party)':<34}pads used")
    print("-" * 86)
    print(f"{'initial':<38}{str(proto.views[0].reserve):<34}-")

    used: list[int] = []
    sender_cycle = [0, 0, 1, 0, 2, 0, 0, 1, 0, 0, 3, 0, 0, 4]
    for i in range(steps):
        j = sender_cycle[i % len(sender_cycle)]
        if net.has_room(j) and proto.can_send(j):
            msg = proto.send(j)
            net.inject(msg)
            used.append(msg.pad)
            label = f"party {j} sends on pad {msg.pad}"
            print(f"{label:<38}{str(proto.views[0].reserve):<34}{len(used)}")
        if len(net.inflight) >= d:
            # Oldest first, so a reserve advance is visible in the next row.
            done = net.inflight.pop(0)
            proto.deliver(done)
            label = f"  network delivers party {done.sender}'s pad {done.pad}"
            print(f"{label:<38}{str(proto.views[0].reserve):<34}{len(used)}")

    print(
        "\nA party's reserve moves only when one of its own messages lands, and the\n"
        "new reserve is always a chunk nobody has been given before - so the map\n"
        "stays a partition and no pad can be used twice."
    )


def compare(n: int, d: int, m: int) -> None:
    print(f"\n\nOne party does all the talking (n={n}, d={d}, m={m})")
    print("-" * 86)
    print(f"{'protocol':<20}{'wasted pads':>14}{'messages sent':>16}{'times blocked':>16}")
    for cls in (ChunkReserveProtocol, GrantProtocol, StaticPartitionProtocol):
        result = run(
            cls(n, d, m),
            schedule=Schedule("single", m),
            delivery="adversarial",
            pressure="lazy",
            seed=0,
        )
        print(
            f"{result.protocol:<20}{result.wasted:>14}{result.sends:>16}"
            f"{result.blocked:>16}"
        )
    print(
        f"\nchunk-reserve leaves exactly (m-1)*d = {(m - 1) * d} pads unused: one chunk\n"
        f"held by each of the {m - 1} silent parties, which is the least any protocol\n"
        "can leave if those parties must stay able to speak without asking first."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--d", type=int, default=3)
    ap.add_argument("--m", type=int, default=5, choices=[5, 9])
    args = ap.parse_args()
    trace(args.n, args.d, args.m)
    compare(args.n, args.d, args.m)


if __name__ == "__main__":
    main()
