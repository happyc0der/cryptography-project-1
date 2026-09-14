"""Network model, message schedules and the simulation driver.

The point of this module is to be *unkind* to the protocols in
:mod:`protocol`: messages are held back for as long as the ``d`` bound allows,
the sending order is arbitrary, and every pad handed out is checked against
every pad handed out before it.  A protocol that keeps perfect secrecy only
because the simulator happened to deliver things promptly will be caught here.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from protocol import DATA, BaseProtocol, Message, PadReuseError

# --- delivery policies -------------------------------------------------------
# Each takes the in-flight list (oldest first) and returns the index to deliver.
# They share one signature so DELIVERY_POLICIES can be indexed by name; the
# deterministic ones ignore `rng`.
DeliveryPolicy = Callable[[list[Message], random.Random], int]


def deliver_random(inflight: list[Message], rng: random.Random) -> int:
    return rng.randrange(len(inflight))


def deliver_fifo(inflight: list[Message], rng: random.Random) -> int:
    return 0


def deliver_lifo(inflight: list[Message], rng: random.Random) -> int:
    return len(inflight) - 1


def deliver_adversarial(inflight: list[Message], rng: random.Random) -> int:
    """Hold back each party's *oldest* message for as long as possible.

    That is the message a party is waiting on: in the chunk-reserve protocol it
    is the one that advances the sender's reserve, and in the pointer protocol
    it is the one that moves the pointer the other party is watching.  So we
    deliver the newest message of whichever party has the most in flight.
    """
    busiest = max(
        {msg.sender for msg in inflight},
        key=lambda s: (sum(1 for m in inflight if m.sender == s), -s),
    )
    return max(i for i, msg in enumerate(inflight) if msg.sender == busiest)


DELIVERY_POLICIES: dict[str, DeliveryPolicy] = {
    "random": deliver_random,
    "fifo": deliver_fifo,
    "lifo": deliver_lifo,
    "adversarial": deliver_adversarial,
}


# --- who talks next ----------------------------------------------------------


class Schedule:
    """Picks the next party to attempt a send.

    ``active`` lets a run model the case where only some of the parties ever
    have anything to say - the situation that sinks the static partition.
    """

    def __init__(self, kind: str, m: int, active: list[int] | None = None) -> None:
        self.kind = kind
        self.m = m
        self.active = list(range(m)) if active is None else list(active)
        if kind == "single" and active is None:
            # Only party 0 ever talks - that is the whole point of this one,
            # and it also tells the driver whose exhaustion ends the run.
            self.active = [0]
        self._cursor = 0
        self._burst_party = self.active[0]
        self._burst_left = 0
        self._spoken: set[int] = set()  # one_shot: who has already spoken

    def live(self) -> list[int]:
        """Parties this schedule might still pick.

        The driver stops when none of these can send.  It is not the same as
        ``active``: under ``one_shot`` the silent parties still *hold* usable
        pads, they are simply never asked again, and testing them would keep
        the run alive forever.
        """
        if self.kind == "one_shot":
            unspoken = [k for k in self.active[1:] if k not in self._spoken]
            return [self.active[0], *unspoken]
        return self.active

    def on_sent(self, j: int) -> None:
        """Told when a pick actually resulted in a send.

        Only ``one_shot`` needs this.  Advancing on the *pick* would let a
        party be skipped whenever the network happened to be full, which would
        make the worst-case construction depend on delivery luck.
        """
        if self.kind == "one_shot":
            self._spoken.add(j)

    def pick(self, rng: random.Random, d: int) -> int:
        if self.kind == "single":
            return self.active[0]
        if self.kind == "one_shot":
            # The worst case for waste: every party but the first sends exactly
            # one message and then falls silent, stranding the rest of the chunk
            # it opened *and* the fresh reserve that send earned it.  The first
            # party then drains the supply.
            for k in self.active[1:]:
                if k not in self._spoken:
                    return k
            return self.active[0]
        if self.kind == "round_robin":
            self._cursor = (self._cursor + 1) % len(self.active)
            return self.active[self._cursor]
        if self.kind == "uniform":
            return rng.choice(self.active)
        if self.kind == "skewed":
            if len(self.active) > 1 and rng.random() < 0.8:
                return self.active[0]
            return rng.choice(self.active)
        if self.kind == "bursty":
            if self._burst_left <= 0:
                self._burst_party = rng.choice(self.active)
                self._burst_left = rng.randint(1, d + 3)
            self._burst_left -= 1
            return self._burst_party
        raise ValueError(f"unknown schedule {self.kind!r}")


SCHEDULES = ["single", "round_robin", "uniform", "skewed", "bursty", "one_shot"]


# --- the network -------------------------------------------------------------


class Network:
    """Holds undelivered messages, enforcing the ``d`` bound.

    ``bound_mode`` picks between the two readings in the handout: ``"global"``
    caps the total number of undelivered messages (the wording of the m-party
    question), ``"per_party"`` caps each sender separately (the wording of the
    two-party warm-up).  The protocols here are correct under both.
    """

    def __init__(self, d: int, bound_mode: str = "global") -> None:
        if d < 1:
            raise ValueError("d must be at least 1")
        if bound_mode not in ("global", "per_party"):
            raise ValueError(f"unknown bound mode {bound_mode!r}")
        self.d = d
        self.bound_mode = bound_mode
        self.inflight: list[Message] = []

    def has_room(self, sender: int) -> bool:
        if self.bound_mode == "global":
            return len(self.inflight) < self.d
        return sum(1 for m in self.inflight if m.sender == sender) < self.d

    def inject(self, msg: Message) -> None:
        assert self.has_room(msg.sender), "network bound violated"
        self.inflight.append(msg)

    def pop(self, policy: DeliveryPolicy, rng: random.Random) -> Message | None:
        if not self.inflight:
            return None
        return self.inflight.pop(policy(self.inflight, rng))


# --- results -----------------------------------------------------------------


@dataclass
class Result:
    protocol: str
    n: int
    d: int
    m: int
    schedule: str
    delivery: str
    pressure: str
    sends: int
    used: int
    wasted: int
    steps: int
    blocked: int = 0
    per_party_sends: list[int] = field(default_factory=list)
    breakdown: dict[str, int] = field(default_factory=dict)
    views_agree: bool = True

    @property
    def utilisation(self) -> float:
        return self.used / self.n


def run(
    proto: BaseProtocol,
    *,
    schedule: Schedule,
    delivery: str = "random",
    pressure: str = "eager",
    bound_mode: str = "global",
    seed: int | None = None,
    max_steps: int = 2_000_000,
) -> Result:
    """Drive ``proto`` until no active party can send another message.

    Every pad is recorded in ``used``; handing out a pad twice raises
    :class:`PadReuseError`, which is the perfect-secrecy check.

    ``pressure`` controls how hard the network is pushed.  ``"eager"`` delivers a
    few messages every step, the way a healthy network behaves.  ``"lazy"``
    delivers nothing until a party is actually starved of network capacity, so
    the undelivered backlog sits at the full ``d`` the whole run - the worst case
    the protocol has to survive, and the setting that exposes a chunk size that
    is too small.
    """
    rng = random.Random(seed)
    net = Network(proto.d, bound_mode)
    policy = DELIVERY_POLICIES[delivery]
    used: set[int] = set()
    pending: list[Message] = []  # control traffic waiting for a network slot
    per_party = [0] * proto.m
    sends = 0
    steps = 0
    idle = 0
    blocked = 0

    def record(msg: Message) -> None:
        if msg.kind != DATA or msg.pad is None:
            return
        if msg.pad in used:
            raise PadReuseError(
                f"{proto.name}: party {msg.sender} reused pad {msg.pad}"
            )
        if not 1 <= msg.pad <= proto.n:
            raise PadReuseError(f"{proto.name}: pad {msg.pad} out of range")
        used.add(msg.pad)

    def pump_control() -> bool:
        moved = False
        proto.tick()
        pending.extend(proto.take_control_messages())
        while pending and net.has_room(pending[0].sender):
            net.inject(pending.pop(0))
            moved = True
        return moved

    def drain() -> None:
        """Deliver everything and let the protocol settle."""
        for _ in range(10_000):
            while net.inflight:
                msg = net.pop(policy, rng)
                assert msg is not None
                proto.deliver(msg)
            if not pump_control():
                return

    while steps < max_steps:
        steps += 1
        busy = pump_control()

        if pressure == "eager":
            for _ in range(rng.randint(0, 3)):
                msg = net.pop(policy, rng)
                if msg is None:
                    break
                proto.deliver(msg)
                busy = True

        j = schedule.pick(rng, proto.d)
        if pressure == "lazy" and not net.has_room(j):
            # Deliver the bare minimum needed to free a slot, and nothing more.
            msg = net.pop(policy, rng)
            if msg is not None:
                proto.deliver(msg)
                busy = True
        if net.has_room(j) and not proto.can_send(j) and proto.has_spare_capacity():
            # The party wanted to talk, the network had room, and unallocated
            # pads still existed - so it is blocked purely waiting on a
            # delivery.  A wait-free protocol never lands here.
            blocked += 1
        if net.has_room(j) and proto.can_send(j):
            msg = proto.send(j)
            record(msg)
            net.inject(msg)
            schedule.on_sent(j)
            per_party[j] += 1
            sends += 1
            busy = True

        idle = 0 if busy else idle + 1
        if idle > 3:
            drain()
            if not any(proto.can_send(k) for k in schedule.live()):
                break
            idle = 0

    views = getattr(proto, "views", None)
    agree = True
    if views is not None:
        agree = all(v.reserve == views[0].reserve for v in views)

    return Result(
        protocol=proto.name,
        n=proto.n,
        d=proto.d,
        m=proto.m,
        schedule=schedule.kind,
        delivery=delivery,
        pressure=pressure,
        sends=sends,
        used=len(used),
        wasted=proto.n - len(used),
        steps=steps,
        blocked=blocked,
        per_party_sends=per_party,
        breakdown=proto.waste_breakdown(),
        views_agree=agree,
    )
