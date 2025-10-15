import random
import pandas as pd


class PointerGapProtocol:
    def __init__(self, n, d, m=5, seed=None):
        self.n = n
        self.d = d
        self.m = m
        self.seed = seed
        if seed is not None:
            random.seed(seed)

        # First m - 1 pointers start at multiples of d and move up
        # Last pointer starts at n + 1 and moves down
        if m < 2:
            # Single sender case: one up pointer, with a right boundary at n + 1
            self.frontiers = [0, n + 1]
            self.direction_up = [True, False]
            self.m = 2
        else:
            self.frontiers = [i * d for i in range(m - 1)] + [n + 1]
            self.direction_up = [True] * (m - 1) + [False]

        self.inflight = []
        self.inflight_counts = [0] * m
        self.used_indices = set()
        self.trace = []
        self.step = 0

    def gap_ok_to_advance(self, i):
        if i < self.m - 1:
            return (self.frontiers[i + 1] - (self.frontiers[i] + 1)) >= self.d
        else:
            return ((self.frontiers[i] - 1) - self.frontiers[i - 1]) >= self.d

    def next_index_for(self, i):
        return self.frontiers[i] + 1 if self.direction_up[i] else self.frontiers[i] - 1

    def try_send(self, i):
        if self.inflight_counts[i] >= self.d:
            return False

        if not self.gap_ok_to_advance(i):
            return False

        idx = self.next_index_for(i)
        if idx < 1 or idx > self.n:
            return False

        self.frontiers[i] = idx
        self.inflight.append({"sender": i, "index": idx, "step": self.step})
        self.inflight_counts[i] += 1
        self.used_indices.add(idx)
        self.trace.append(
            {
                "step": self.step,
                "action": "send",
                "sender": i + 1,
                "index": idx,
                "frontiers": self.frontiers.copy(),
            }
        )

        return True

    def deliver_one(self):
        if not self.inflight:
            return False

        i = random.randrange(len(self.inflight))
        msg = self.inflight.pop(i)
        s, idx = msg["sender"], msg["index"]

        self.inflight_counts[s] -= 1

        if self.direction_up[s]:
            self.frontiers[s] = max(self.frontiers[s], idx)
        else:
            self.frontiers[s] = min(self.frontiers[s], idx)

        self.trace.append(
            {
                "step": self.step,
                "action": "deliver",
                "sender": s + 1,
                "index": idx,
                "frontiers": self.frontiers.copy(),
            }
        )

        return True

    def run(self, scenario_senders, max_steps=10000):
        senders = scenario_senders
        while self.step < max_steps:
            self.step += 1
            made_progress = False

            # Deliver some messages
            deliver_count = random.randint(0, min(3, len(self.inflight)))
            for _ in range(deliver_count):
                if self.deliver_one():
                    made_progress = True

            # Attempt sends
            random.shuffle(senders)
            for i in senders:
                while self.try_send(i):
                    made_progress = True

            # Terminate if no progress
            can_any_send = any(
                self.inflight_counts[i] < self.d
                and self.gap_ok_to_advance(i)
                and 1 <= self.next_index_for(i) <= self.n
                for i in senders
            )

            if not made_progress and not can_any_send:
                break

        # Compute gaps
        wasted_gap_values = [
            self.frontiers[j + 1] - self.frontiers[j] for j in range(self.m - 1)
        ]

        wasted_total = sum(wasted_gap_values)
        wasted_pads = self.n - len(self.used_indices)

        return {
            "final_frontiers": self.frontiers,
            "used_indices_count": len(self.used_indices),
            "wasted_gap_values": wasted_gap_values,
            "wasted_total": wasted_total,
            "wasted_pads": wasted_pads,
            "trace": pd.DataFrame(self.trace),
        }


# Example testing
if __name__ == "__main__":
    n, d = 200, 5
    scenarios = {
        "S.1": [0],
        "S.2": [0, 1],
        "S.3": [0, 1, 2],
        "S.4": [0, 1, 2, 3],
        "S.5": [0, 1, 2, 3, 4],
    }
    for name, senders in scenarios.items():
        sim = PointerGapProtocol(n=n, d=d, seed=42)
        result = sim.run(senders)
        print(
            f"{name} -> Wasted pads: {result['wasted_pads']}, Gaps: {result['wasted_gap_values']}"
        )
