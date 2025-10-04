"""
Pointer-Gap Scheme Simulation (m = 5)
-------------------------------------
Implements the pointer-gap protocol ensuring perfect OTP secrecy
and ≥ (m-1)d = 4d wasted pads at termination.
"""

import random
import pandas as pd


def simulate_pointer_gap(n=200, d=3, seed=None, max_steps=10000):
    """
    Simulate the pointer-gap scheme for m=5 parties.

    Args:
        n (int): total number of pads (indices 1..n)
        d (int): safety gap / max in-flight messages per sender
        seed (int): RNG seed for reproducibility
        max_steps (int): safety cap on iterations

    Returns:
        dict with:
          - frontiers
          - used indices
          - wasted pad counts
          - event trace (pandas DataFrame)
    """
    if seed is not None:
        random.seed(seed)

    m = 5
    frontiers = [0, d, 2 * d, 3 * d, n + 1]
    direction_up = [True, True, True, True, False]  # P1..P4 ↑, P5 ↓

    def next_index_for(i):
        return frontiers[i] + 1 if direction_up[i] else frontiers[i] - 1

    inflight = []
    inflight_counts = [0] * m
    used_indices = set()
    trace = []
    step = 0

    def gap_ok_to_advance(i):
        if i == 0:
            return (frontiers[1] - (frontiers[0] + 1)) >= d
        if i == 1:
            return (frontiers[2] - (frontiers[1] + 1)) >= d
        if i == 2:
            return (frontiers[3] - (frontiers[2] + 1)) >= d
        if i == 3:
            return (frontiers[4] - (frontiers[3] + 1)) >= d
        if i == 4:
            return ((frontiers[4] - 1) - frontiers[3]) >= d

    def try_send(i):
        nonlocal inflight, inflight_counts, used_indices
        if inflight_counts[i] >= d:
            return False, "inflight_limit"

        if not gap_ok_to_advance(i):
            return False, "gap_violation"

        idx = next_index_for(i)

        if idx < 1 or idx > n:
            return False, "out_of_range"

        frontiers[i] = idx
        inflight.append({"sender": i, "index": idx, "created_step": step})
        inflight_counts[i] += 1
        used_indices.add(idx)
        trace.append(
            {
                "step": step,
                "action": "send",
                "sender": i + 1,
                "index": idx,
                "frontiers": frontiers.copy(),
            }
        )

        return True, "sent"

    def deliver_one():
        nonlocal inflight, inflight_counts
        if not inflight:
            return False

        i = random.randrange(len(inflight))
        msg = inflight.pop(i)
        s, idx = msg["sender"], msg["index"]
        inflight_counts[s] -= 1

        if direction_up[s]:
            frontiers[s] = max(frontiers[s], idx)
        else:
            frontiers[s] = min(frontiers[s], idx)

        trace.append(
            {
                "step": step,
                "action": "deliver",
                "sender": s + 1,
                "index": idx,
                "frontiers": frontiers.copy(),
            }
        )

        return True

    for step in range(1, max_steps + 1):
        made_progress = False
        # deliver up to 3 random messages
        deliver_count = random.randint(0, min(3, len(inflight)))
        for _ in range(deliver_count):
            if deliver_one():
                made_progress = True

        # attempt sends
        order = list(range(m))
        random.shuffle(order)
        for i in order:
            while True:
                ok, _ = try_send(i)
                if ok:
                    made_progress = True
                else:
                    break

        # possibly deliver one more to unblock
        if not made_progress and inflight:
            deliver_one()

        # termination check
        can_any_send = any(
            (
                inflight_counts[i] < d
                and gap_ok_to_advance(i)
                and 1 <= next_index_for(i) <= n
            )
            for i in range(m)
        )

        if not made_progress and not can_any_send:
            break

    wasted_gap_values = [
        frontiers[1] - frontiers[0],
        frontiers[2] - frontiers[1],
        frontiers[3] - frontiers[2],
        frontiers[4] - frontiers[3],
    ]

    wasted_total = sum(wasted_gap_values)

    return {
        "n": n,
        "d": d,
        "final_frontiers": frontiers,
        "used_indices_count": len(used_indices),
        "wasted_gap_values": wasted_gap_values,
        "wasted_total": wasted_total,
        "trace": pd.DataFrame(trace),
    }


if __name__ == "__main__":
    res = simulate_pointer_gap(n=200, d=5, seed=42, max_steps=10000)
    print("Final frontiers:", res["final_frontiers"])
    print("Used indices:", res["used_indices_count"])
    print("Wasted gaps:", res["wasted_gap_values"])
    print("Total wasted pads:", res["wasted_total"], f"(≥ 4d = {4*res['d']})")
    print()
    print(res["trace"])
