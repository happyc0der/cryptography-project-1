# Testing

```bash
python -m pytest -q              # 310 tests, about 8 seconds
python -m pytest -q -k "pad or secrecy"   # just the pad-reuse tests
```

## How secrecy is checked

`simulation.run` records every pad handed out and raises `PadReuseError` the
moment one repeats, so any run that completes is a proof of no reuse for that
schedule. The tests then run the protocol under every combination we can build:

* **schedules** — `single`, `round_robin`, `uniform`, `skewed`, `bursty`,
  `one_shot` (every party but one speaks exactly once then falls silent — the
  worst case for waste, and the one the first five schedules all miss)
* **delivery orders** — `random`, `fifo`, `lifo`, `adversarial` (holds back each
  party's oldest message, the one it is waiting on, for as long as the `d` bound
  allows)
* **network pressure** — `eager` (a healthy network) and `lazy` (delivers nothing
  until a party is starved of capacity, so the backlog sits at the full `d` for
  the whole run)
* **both readings of `d`** — capped globally, and capped per party
* `m` ∈ {5, 9}, and `d` from 1 to 17, several seeds each

`test_pad_reuse_is_actually_detected` runs a deliberately broken protocol to
confirm the check fires, so a passing suite is not passing vacuously.

## What else is covered

| test | what it pins down |
|---|---|
| `test_reserves_stay_exclusive_and_are_never_reissued` | the reserve map really is a partition — the safety argument, checked directly rather than inferred from the absence of collisions |
| `test_chunk_size_d_is_wait_free_and_d_minus_one_is_not` | `c = d` is the exact threshold: `c = d` never blocks, `c = d-1` strands a party |
| `test_never_blocked_under_any_schedule` | no stalls under any schedule, with the network held at capacity |
| `test_waste_never_exceeds_the_proved_bound` | measured waste stays inside the bound across the grid |
| `test_the_waste_bound_is_tight` | the bound is reached exactly — it is the worst case, not a ceiling |
| `test_one_shot_is_the_worst_schedule_in_the_grid` | speaking once and stopping strands more than never speaking or never stopping |
| `test_waste_does_not_grow_with_n` | same waste at n = 2 000, 20 000 and 200 000 |
| `test_beats_the_static_partition_when_one_party_does_the_talking` | 50× less waste than the baseline |
| `test_the_handout_guard_admits_a_collision_and_the_fixed_one_does_not` | the off-by-one in the handout's two-party gap check, as a concrete collision |
| `test_without_delivery_feedback_the_ledger_splits_but_stays_safe` | chunk-reserve needs the broadcast model — it stalls without it, but never leaks |
| `test_grant_protocol_is_safe_without_delivery_feedback` | the fallback protocol is safe in the weaker model |
| `test_runs_are_reproducible` | same seed, same run |

## Performance

`python eval_protocol.py` writes `summary.csv` (180 cells, each the worst case
over 4 delivery orders × 2 pressures × 3 seeds) and prints the summary tables.
Takes about 40 seconds.
