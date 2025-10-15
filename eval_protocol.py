# eval_protocol.py
import time
import random
import statistics as stats
import pandas as pd
from main import PointerGapProtocol


# Run the protocol with random message delivery and sending, return wasted pads and total sends
def run_with_random_scheduler(n, d, m, active_senders, seed=None, max_steps=200000):
    if seed is not None:
        random.seed(seed)

    sim = PointerGapProtocol(n=n, d=d, m=m, seed=seed)
    send_count = 0
    step = 0

    while step < max_steps:
        step += 1
        made_progress = False

        # Random (0 to 3) deliveries
        deliver_count = random.randint(0, min(3, len(sim.inflight)))
        for _ in range(deliver_count):
            if sim.deliver_one():
                made_progress = True

        # Pick 1 active sender at random and attempt 1 send
        choice = random.choice(active_senders)
        if sim.try_send(choice):
            made_progress = True
            send_count += 1

        # Stop only if no progress, nobody can send, and nothing left to deliver
        can_any_send = any(
            sim.inflight_counts[i] < sim.d
            and sim.gap_ok_to_advance(i)
            and 1 <= sim.next_index_for(i) <= sim.n
            for i in active_senders
        )
        if not made_progress and not can_any_send and len(sim.inflight) == 0:
            break

    wasted_pads = n - len(sim.used_indices)
    return wasted_pads, send_count


# Compare protocol performance across different sender counts against baseline efficiency
def evaluate(n=5000, d=5, m_chosen=5, trials=200, seed=2025, max_steps=200000):
    rng = random.Random(seed)
    scenarios = {f"S.{x}": list(range(x)) for x in range(1, m_chosen + 1)}
    baseline = ((m_chosen - 1) / m_chosen) * n

    rows = []
    for name, senders in scenarios.items():
        x = len(senders)
        wastes, per_send_times = [], []

        for _ in range(trials):
            trial_seed = rng.randrange(10**9)
            t0 = time.perf_counter()
            # Run with exactly x parties; scheduler delivers 0 to 3 then attempts 1 send per tick
            wasted, sends = run_with_random_scheduler(
                n=n,
                d=d,
                m=x,
                active_senders=senders,
                seed=trial_seed,
                max_steps=max_steps,
            )
            t1 = time.perf_counter()

            wastes.append(wasted)
            per_send_times.append((t1 - t0) / max(sends, 1))  # average time per send

        avg_waste = stats.mean(wastes)
        max_waste = max(wastes)
        avg_time_per_send = stats.mean(per_send_times)

        rows.append(
            {
                "scenario": name,
                "x": x,
                "avg_wasted_pads": round(avg_waste, 2),  # waste pads for report
                "max_wasted_pads": int(max_waste),  # worst case
                "assignment_baseline": round(
                    baseline, 2
                ),  # ((m_chosen-1)/m_chosen) * n
                "meets_baseline?": avg_waste < baseline,  # requirement check
                "avg_time_per_send_seconds": avg_time_per_send,  # runtime per message
            }
        )

    # Output results
    df = pd.DataFrame(rows)
    df.to_csv("summary.csv", index=False)
    print("\n=== Summary ===")
    print(df.to_string(index=False))
    print("\nSaved to: summary.csv")
    return df


if __name__ == "__main__":
    evaluate(n=5000, d=5, m_chosen=5, trials=200, seed=2025)
