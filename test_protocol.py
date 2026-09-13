"""Correctness tests.

The headline property - no pad is ever used twice - is checked by
``simulation.run`` itself: it records every pad handed out and raises
:class:`PadReuseError` on a repeat.  So the secrecy tests below simply run the
protocol under every combination of send schedule, delivery order and network
pressure we can think of, including the ones designed to keep each party's view
as stale as the ``d`` bound allows.

Run with:  python -m pytest -q
"""

from __future__ import annotations

import itertools

import pytest

from protocol import (
    BaseProtocol,
    ChunkReserveProtocol,
    GrantProtocol,
    Message,
    PadReuseError,
    StaticPartitionProtocol,
    TwoPartyPointerProtocol,
)
from simulation import DELIVERY_POLICIES, SCHEDULES, Schedule, run

DELIVERIES = sorted(DELIVERY_POLICIES)
PRESSURES = ["eager", "lazy"]
N = 2000

ALL_CONDITIONS = list(itertools.product(SCHEDULES, DELIVERIES, PRESSURES))


# --- perfect secrecy ---------------------------------------------------------


@pytest.mark.parametrize("m", [5, 9])
@pytest.mark.parametrize("schedule,delivery,pressure", ALL_CONDITIONS)
def test_no_pad_is_used_twice(m, schedule, delivery, pressure):
    """The whole point of the exercise, under every condition we can generate."""
    for seed in range(3):
        proto = ChunkReserveProtocol(N, d=5, m=m)
        result = run(
            proto,
            schedule=Schedule(schedule, m),
            delivery=delivery,
            pressure=pressure,
            seed=seed,
        )
        assert result.used + result.wasted == N
        assert result.used == result.sends


@pytest.mark.parametrize("d", [1, 2, 5, 17])
@pytest.mark.parametrize("bound_mode", ["global", "per_party"])
def test_secrecy_holds_for_both_readings_of_d(d, bound_mode):
    """`d` is capped globally in the m-party question, per party in the warm-up."""
    for seed in range(3):
        proto = ChunkReserveProtocol(N, d=d, m=5)
        run(
            proto,
            schedule=Schedule("bursty", 5),
            delivery="adversarial",
            pressure="lazy",
            bound_mode=bound_mode,
            seed=seed,
        )


def test_reserves_stay_exclusive_and_are_never_reissued():
    """Safety comes from the reserve map being a partition; check it directly."""
    owner_of_chunk: dict[int, int] = {}
    ever_reserved: set[int] = set(range(5))  # the initial reserve map

    class Audited(ChunkReserveProtocol):
        def send(self, j):
            msg = super().send(j)
            chunk = self.layout.chunk_of(msg.pad)
            assert owner_of_chunk.setdefault(chunk, j) == j, (
                f"chunk {chunk} used by parties {owner_of_chunk[chunk]} and {j}"
            )
            return msg

        def observe(self, j, msg):
            super().observe(j, msg)
            live = [r for r in self.views[j].reserve if r is not None]
            assert len(live) == len(set(live)), "two parties hold the same reserve"
            for r in live:
                ever_reserved.add(r)

    proto = Audited(N, d=5, m=5)
    run(
        proto,
        schedule=Schedule("skewed", 5),
        delivery="adversarial",
        pressure="lazy",
        seed=0,
    )
    # Every chunk anyone drew a pad from had been reserved for exactly one party.
    assert set(owner_of_chunk) <= ever_reserved


# --- the communication model matters -----------------------------------------


def test_all_parties_derive_the_same_reserve_map_in_the_broadcast_model():
    proto = ChunkReserveProtocol(N, d=5, m=5)
    result = run(proto, schedule=Schedule("uniform", 5), delivery="random", seed=0)
    assert result.views_agree
    assert all(v.reserve == proto.views[0].reserve for v in proto.views)


def test_without_delivery_feedback_the_ledger_splits_but_stays_safe():
    """A sender that cannot see its own delivery cannot advance its own reserve.

    The protocol does not become unsafe - it becomes useless, which is why the
    no-feedback model needs :class:`GrantProtocol` instead.
    """
    proto = ChunkReserveProtocol(N, d=5, m=5, sender_observes_delivery=False)
    result = run(proto, schedule=Schedule("uniform", 5), delivery="random", seed=0)
    assert not result.views_agree
    assert result.wasted > N // 2  # stalls almost immediately


# --- wait-freedom ------------------------------------------------------------


@pytest.mark.parametrize("d", [2, 5, 9])
def test_chunk_size_d_is_wait_free_and_d_minus_one_is_not(d):
    """`blocked` counts: wanted to send, had network room, pads left, could not."""
    for delivery in DELIVERIES:
        ok = run(
            ChunkReserveProtocol(N, d=d, m=5, chunk_size=d),
            schedule=Schedule("single", 5),
            delivery=delivery,
            pressure="lazy",
            seed=0,
        )
        assert ok.blocked == 0, f"c=d stalled under {delivery}"

    stalls = max(
        run(
            ChunkReserveProtocol(N, d=d, m=5, chunk_size=d - 1),
            schedule=Schedule("single", 5),
            delivery=delivery,
            pressure="lazy",
            seed=0,
        ).blocked
        for delivery in DELIVERIES
    )
    assert stalls > 0, "c = d-1 should be able to strand a party"


@pytest.mark.parametrize("schedule", SCHEDULES)
def test_never_blocked_under_any_schedule(schedule):
    result = run(
        ChunkReserveProtocol(N, d=5, m=5),
        schedule=Schedule(schedule, 5),
        delivery="adversarial",
        pressure="lazy",
        seed=1,
    )
    assert result.blocked == 0


# --- waste -------------------------------------------------------------------


@pytest.mark.parametrize("m", [5, 9])
@pytest.mark.parametrize("d", [1, 2, 5, 11])
@pytest.mark.parametrize("schedule,delivery,pressure", ALL_CONDITIONS[::3])
def test_waste_never_exceeds_the_proved_bound(m, d, schedule, delivery, pressure):
    proto = ChunkReserveProtocol(N, d=d, m=m)
    result = run(
        proto,
        schedule=Schedule(schedule, m),
        delivery=delivery,
        pressure=pressure,
        seed=2,
    )
    assert result.wasted <= proto.waste_bound()


@pytest.mark.parametrize("n", [2_000, 20_000, 200_000])
def test_waste_does_not_grow_with_n(n):
    """The bound is O(m*d) with no n in it; confirm the simulation agrees."""
    proto = ChunkReserveProtocol(n, d=5, m=5)
    result = run(proto, schedule=Schedule("single", 5), delivery="random", seed=0)
    assert result.wasted <= 5 * (2 * 5 - 1)


def test_beats_the_static_partition_when_one_party_does_the_talking():
    kwargs = dict(schedule=Schedule("single", 5), delivery="random", seed=0)
    ours = run(ChunkReserveProtocol(N, d=5, m=5), **kwargs)
    theirs = run(
        StaticPartitionProtocol(N, d=5, m=5),
        schedule=Schedule("single", 5),
        delivery="random",
        seed=0,
    )
    assert theirs.wasted == pytest.approx(N * 4 / 5, rel=0.01)
    assert ours.wasted < theirs.wasted / 50


# --- the two-party protocol from the problem statement -----------------------


def test_the_handout_guard_admits_a_collision_and_the_fixed_one_does_not():
    """`i2 - i1 - 1 >= d` is off by one.  Smallest counterexample: n=4, d=1.

    Bob uses pad 4 (delivered) then pad 3 (still in flight).  Alice still sees
    i2 = 4, so the handout's check lets her walk all the way to pad 3 - the pad
    Bob is already using.
    """
    handout = TwoPartyPointerProtocol(4, 1, handout_guard=True)
    bob_seen = handout.send(1)
    handout.deliver(bob_seen)
    bob_hidden = handout.send(1)
    alice = []
    while handout.can_send(0):
        alice.append(handout.send(0).pad)
    assert bob_hidden.pad in alice, "expected the off-by-one to collide"

    fixed = TwoPartyPointerProtocol(4, 1)
    fixed.deliver(fixed.send(1))
    hidden = fixed.send(1)
    safe = []
    while fixed.can_send(0):
        safe.append(fixed.send(0).pad)
    assert hidden.pad not in safe


@pytest.mark.parametrize("d", [1, 3, 8])
@pytest.mark.parametrize("delivery", DELIVERIES)
def test_two_party_reference_is_safe_and_wastes_at_most_d(d, delivery):
    result = run(
        TwoPartyPointerProtocol(N, d),
        schedule=Schedule("uniform", 2),
        delivery=delivery,
        pressure="lazy",
        seed=0,
    )
    assert result.wasted <= d


# --- the no-feedback alternative ---------------------------------------------


@pytest.mark.parametrize("schedule", SCHEDULES)
@pytest.mark.parametrize("delivery", DELIVERIES)
def test_grant_protocol_is_safe_without_delivery_feedback(schedule, delivery):
    proto = GrantProtocol(N, d=5, m=5)
    assert proto.sender_observes_delivery is False
    run(
        proto,
        schedule=Schedule(schedule, 5),
        delivery=delivery,
        pressure="lazy",
        seed=0,
    )


def test_grant_protocol_rebalances_but_has_to_wait_for_it():
    """It matches chunk-reserve on waste and loses on stalling."""
    grant = run(
        GrantProtocol(N, d=5, m=5),
        schedule=Schedule("single", 5),
        delivery="adversarial",
        pressure="lazy",
        seed=0,
    )
    reserve = run(
        ChunkReserveProtocol(N, d=5, m=5),
        schedule=Schedule("single", 5),
        delivery="adversarial",
        pressure="lazy",
        seed=0,
    )
    assert grant.wasted < N // 4  # it does steal work, unlike the static split
    assert grant.blocked > 0  # but the hand-off costs a round trip
    assert reserve.blocked == 0


# --- housekeeping ------------------------------------------------------------


def test_runs_are_reproducible():
    def once():
        return run(
            ChunkReserveProtocol(N, d=5, m=5),
            schedule=Schedule("bursty", 5),
            delivery="random",
            seed=1234,
        )

    a, b = once(), once()
    assert (a.sends, a.used, a.wasted, a.per_party_sends) == (
        b.sends,
        b.used,
        b.wasted,
        b.per_party_sends,
    )


def test_pad_reuse_is_actually_detected():
    """Guard the guard: a protocol that reuses a pad must fail the secrecy check."""

    class AlwaysPadOne(BaseProtocol):
        name = "deliberately-broken"

        def can_send(self, j):
            return True

        def send(self, j):
            return Message(sender=j, pad=1)

        def observe(self, j, msg):
            return

    with pytest.raises(PadReuseError):
        run(
            AlwaysPadOne(N, d=5, m=5),
            schedule=Schedule("round_robin", 5),
            delivery="random",
            seed=0,
        )
