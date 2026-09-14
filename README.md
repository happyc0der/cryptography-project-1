# Perfect-secrecy pad allocation for m parties

[![tests](https://github.com/happyc0der/cryptography-project-1/actions/workflows/tests.yml/badge.svg)](https://github.com/happyc0der/cryptography-project-1/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)

NYU CS6903/4783, Project 1. Chosen party count: **m = 5** (everything is general
in `m`; `m = 9` is reported alongside).

📄 **[Full report](https://claude.ai/code/artifact/e789cfb6-54c4-4d0c-8fbf-ca5e43caa5d3)**
— the protocol, the proofs, the two defects found in the handout's own two-party
protocol, and the evaluation. This README is the short version.

## The problem

`m` parties share `n` random `L`-bit one-time pads `k_1..k_n`. Every message is
broadcast to the other `m-1` parties, and the network hands a message to all of
them at the same instant — but different messages take different times, and at
any moment at most `d` messages are undelivered. Each party sends whenever it
wants; nobody takes turns and nobody negotiates first.

Two things to get right:

1. **Perfect secrecy** — no pad is ever used twice, by the same party or by two
   different ones. A repeat destroys the one-time-pad guarantee outright: XOR the
   two ciphertexts and the pad drops out, leaving `m1 ⊕ m2`.
2. **Few wasted pads** — when nobody can safely send any more, the number of
   never-used pads should be small. The two-party protocol in the handout wastes
   `d`. We want something comparably tight, not something that scales with `n`.

The tension is that a party must decide *locally* which pad to use, while its
picture of what everyone else has used is up to `d` messages out of date.

## Why the obvious answers fail

**Split the pads into `m` fixed slices.** Trivially secret, needs no
coordination — and useless. A party can only spend its own slice, so if one party
does the talking it wastes `(m-1)/m` of everything: **4000 of 5000 pads** at
`m = 5`. This is the baseline in `StaticPartitionProtocol`, and it is what the
first version of this repo did.

**Run `m` pointers up the line, each keeping a `d` gap from the next.** Only the
top pointer has room; everyone else jams against their neighbour immediately.

**Everyone takes "the lowest unused pad".** Two parties pick the same pad while
both messages are in flight. Adding a per-party offset to break the tie only
works if the offset is a fixed residue class — which is the static partition
again. You cannot break ties with a rule that is both local and non-static.

What makes it work is the thing the handout hands you for free: because delivery
is simultaneous to everyone, **the delivered history is common knowledge**.
Parties disagree about the last `d` messages, but they agree perfectly about
everything before that — so an allocation rule replayed over the delivered
history gives every party the same answer.

## The protocol: chunk-reserve

Group the pads into chunks of `c = d` pads. Every party owns two chunks:

* a **current** chunk it is drawing pads from — private, nobody else knows how
  far along it is;
* a **reserve** chunk — public, and the same in everyone's book.

Initially party `j` has current = reserve = chunk `j`. Messages carry what they
carried in the two-party protocol: the ciphertext and the pad index. The entire
coordination rule is one line, replayed by every party over the delivered
sequence:

> When a delivered message from party `j` uses a pad inside `reserve[j]`, set
> `reserve[j]` to the next chunk that has never been assigned to anyone.

A party spends its current chunk in order; when it runs out it moves into its
reserve. That is the whole protocol — no requests, no grants, no acknowledgements,
no extra round trips.

```
initial                               reserve map [0, 1, 2, 3, 4]
party 0 sends on pad 1                            [0, 1, 2, 3, 4]
party 1 sends on pad 4                            [0, 1, 2, 3, 4]
  network delivers party 0's pad 1                [5, 1, 2, 3, 4]   <- party 0 gets a new reserve
party 0 sends on pad 3                            [5, 1, 2, 3, 4]
  network delivers party 1's pad 4                [5, 6, 2, 3, 4]   <- party 1 gets a new reserve
party 0 sends on pad 16                           [5, 6, 2, 3, 4]   <- party 0 has moved into chunk 5
```

`python main.py` prints this trace.

### Perfect secrecy

The reserve map is a partition of the chunk space. The initial reserves `0..m-1`
are distinct, and every reassignment takes a chunk that has never been assigned,
so no chunk is ever given to two parties. A party only ever draws pads from a
chunk that was its own reserve. Therefore no pad is used twice.

Note what the argument does *not* use: no assumption about timing, delivery
order, or how stale anyone's view is. Staleness costs throughput, never secrecy.

### Wait-freedom

*A party that the network will accept a message from can always send one.*

A party allowed to put another message on the network has at most `d-1` of its
own messages undelivered. If its current chunk still has pads, it sends. If not,
it has already sent `c = d` messages from that chunk, so at least
`c - (d-1) = 1` of them has been delivered — and that delivery advanced its
reserve. Either way it has a pad.

`c = d` is exactly the threshold. At `c = d-1` a party can have its whole chunk in
flight with nothing delivered and be stuck waiting;
`test_chunk_size_d_is_wait_free_and_d_minus_one_is_not` demonstrates both sides.
The argument only uses "at most `d` undelivered", so it holds whether that bound
is read globally (the `m`-party question) or per party (the two-party warm-up).

### Wasted pads

When the chunks run out, each party holds at most one untouched reserve (`c`
pads) and one partly spent current chunk (`c-1` unused), giving a worst case of

```
waste  <=  m * (2d - 1)  +  (n mod c)
```

**There is no `n` in that bound.** Measured waste is tighter still: exactly
`(m-1) * d` when `m-1` parties stay quiet — one chunk per silent party — and `0`
when everyone talks.

`(m-1) * d` is also the best possible. The handout's two-party lower bound
applied to each silent party: if a party must be able to send `d` messages
without asking anyone first, it has to be holding `d` pads that nobody else may
touch. With `m-1` parties quiet that is `(m-1) * d` pads out of reach. **So the
protocol is optimal in this case, not merely good.**

## Results

`python eval_protocol.py` — 150 grid cells, each the worst case over 4 delivery
orders × 2 network pressures × 3 seeds. Full output in `summary.csv`.

`m = 5`, `d = 5`, `n = 5000`:

| | wasted: one party talks | wasted: mostly one | blocked: one party talks | blocked: mostly one |
|---|---|---|---|---|
| **chunk-reserve** | **20** | **0** | **0** | **0** |
| grant | 20 | 0 | 16 | 625 |
| static-partition | 4000 | 0 | 8 | 22042 |

"Blocked" counts the times a party wanted to send, the network had room, unused
pads existed, and the protocol still could not give it one.

Worst case over every schedule, delivery order and pressure, `m = 5`, `n = 5000`:

| d | chunk-reserve | proved bound | static-partition |
|---|---|---|---|
| 1 | 4 | 5 | 4000 |
| 2 | 8 | 15 | 4000 |
| 5 | 20 | 45 | 4000 |
| 10 | 40 | 95 | 4000 |
| 20 | 80 | 195 | 4000 |

Waste tracks `(m-1)*d` and ignores `n` entirely:

| n | wasted | messages sent |
|---|---|---|
| 5 000 | 20 | 4 980 |
| 20 000 | 20 | 19 980 |
| 80 000 | 20 | 79 980 |

At `m = 9` the same pattern holds with `(m-1)*d = 8d`: 8 wasted at `d = 1`, 160 at
`d = 20`. Throughput is about 3–4 µs per message, dominated by the simulator
rather than the protocol — the protocol itself is a couple of integer
comparisons per send.

## Two notes on the handout's two-party protocol

**The gap check is off by one.** The handout guards with `i2 - i1 - 1 >= d`.
Alice knows Bob's pointer only as of the last delivery, and Bob may have advanced
`d` further, so her pad `i1 + 1` is safe only when `i1 + 1 < i2 - d`, i.e.
`i2 - i1 - 1 >= d + 1`. Smallest counterexample, with `n = 4`, `d = 1`: Bob uses
pad 4 (delivered), then pad 3 (still in flight). Alice still sees `i2 = 4`, the
handout's check passes all the way to `i1 = 2`, and she takes pad 3 — the pad Bob
is using. `TwoPartyPointerProtocol(..., handout_guard=True)` reproduces it and
`test_the_handout_guard_admits_a_collision_and_the_fixed_one_does_not` pins it
down.

**A pointer view has to be folded monotonically.** The handout bounds how many
messages are outstanding, not how long any one takes, so deliveries can arrive
out of order. Taking the newest arrival at face value lets Alice's view of Bob's
pointer move *backwards*, which produces a real collision under LIFO delivery —
the adversarial delivery policy in `simulation.py` found this. Each pointer only
moves one way, so each party folds its observations with `min`/`max`.

## The communication model, and a protocol that does not need it

Chunk-reserve needs the delivered history to be common knowledge: a party's
reserve advances when *its own* message lands, so it has to see that event. That
is the normal semantics of a broadcast medium, and it is what
`sender_observes_delivery=True` (the default) models.

If a sender gets no feedback at all about its own messages, that rule is not
computable — the new reserve depends on how many other parties opened chunks
first, and a sender cannot place its own deliveries in that order. Chunk-reserve
stays *safe* in that model but stalls almost immediately
(`test_without_delivery_feedback_the_ledger_splits_but_stays_safe`).

`GrantProtocol` is the fallback for that weaker model. Chunk `C` starts owned by
party `C % m`; a party running low broadcasts a request; a party with spare
chunks gives some away and drops them from its own pool *at send time*, before
the grant is even in the air. Safety needs no timing argument at all — a chunk is
only ever used by its owner, and ownership moves only when the owner unilaterally
gives it up. It matches chunk-reserve on waste, and the cost shows up in the
`times blocked` column: rebalancing takes a round trip, so parties stall waiting
for grants. Chunk-reserve never stalls.

## Files

| file | contents |
|---|---|
| `protocol.py` | `ChunkReserveProtocol` (the answer), `GrantProtocol`, `StaticPartitionProtocol`, `TwoPartyPointerProtocol` |
| `simulation.py` | network with the `d` bound, delivery adversaries, send schedules, the driver and the pad-reuse check |
| `main.py` | annotated trace plus the head-to-head comparison |
| `eval_protocol.py` | the grid; writes `summary.csv` |
| `test_protocol.py` | 251 tests — see `testing.md` |
| `summary.csv` | the full 150-cell grid, regenerated by `eval_protocol.py` and checked in CI |
| `testing.md` | what each test pins down, and how secrecy is checked |
| `pyproject.toml` | ruff lint and format configuration |
| `requirements.txt` / `requirements-dev.txt` | `pytest`; plus `ruff` for development |
| `.github/workflows/tests.yml` | tests on Python 3.11–3.13, lint, and the `summary.csv` check |

## Running it

Python 3.11 or newer, one dependency (`pytest`).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py           # annotated trace + head-to-head comparison
.venv/bin/python eval_protocol.py  # the grid; writes summary.csv
.venv/bin/python -m pytest -q      # 251 tests, about 4 seconds
```

Both scripts take flags:

```bash
python main.py --m 9 --d 5              # 9 parties, 5 undelivered messages
python eval_protocol.py --n 20000 --seeds 5 --out my_grid.csv
```

## Running your own simulation

`simulation.run` drives any protocol against a hostile network and returns a
`Result`. A run ends when no active party can send another message.

```python
from protocol import ChunkReserveProtocol
from simulation import Schedule, run

result = run(
    ChunkReserveProtocol(n=5000, d=5, m=5),
    schedule=Schedule("single", m=5),  # only party 0 ever talks
    delivery="adversarial",  # hold back the message each party waits on
    pressure="lazy",  # keep the backlog pinned at the full d
    seed=0,
)
print(result.wasted, result.sends, result.blocked)  # -> 20 4980 0
```

The four knobs, from most to least forgiving:

| knob | values | what it varies |
|---|---|---|
| `schedule` | `single`, `round_robin`, `uniform`, `skewed`, `bursty` | who talks, and how unevenly |
| `delivery` | `random`, `fifo`, `lifo`, `adversarial` | which undelivered message the network hands over next |
| `pressure` | `eager`, `lazy` | `lazy` delivers nothing until a party is starved, so the backlog sits at `d` all run |
| `bound_mode` | `global`, `per_party` | whether `d` caps total undelivered messages or each sender's |

`delivery="adversarial"` with `pressure="lazy"` is the worst case and the setting
the headline numbers use. `Schedule(kind, m, active=[0, 2])` restricts who talks
to an explicit subset.

Fields on `Result`: `wasted`, `used`, `sends`, `per_party_sends`, `steps`,
`blocked` (times a party wanted to send, the network had room, unused pads
existed, and the protocol could not produce one — always `0` for chunk-reserve),
`views_agree` (whether every party's reserve map matched, i.e. the broadcast
assumption held) and `breakdown` (where the leftover pads went).

Swap in `GrantProtocol`, `StaticPartitionProtocol` or `TwoPartyPointerProtocol`
for the first argument — they share the interface. Every pad handed out is
checked against every pad before it, so a run that completes is a proof of no
reuse for that schedule; a violation raises `PadReuseError`.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .          # lint
.venv/bin/ruff format .         # format
```

CI runs the tests on Python 3.11–3.13, lints, checks formatting, and verifies
that `summary.csv` still matches what `eval_protocol.py` produces — every column
in it is a deterministic function of the grid parameters, so a protocol change
that was never re-evaluated fails the build.
