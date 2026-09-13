"""Pad-allocation protocols for the m-party perfect-secrecy problem.

Setting (NYU CS6903/4783 Project 1)
-----------------------------------
``m`` parties share ``n`` random L-bit pads ``k_1..k_n``.  Every message is
broadcast: the network hands it to all the other ``m-1`` parties at the same
instant, though different messages may take different amounts of time, and at
any moment at most ``d`` messages are undelivered.

A protocol must decide, locally and with no extra round trips, *which pad* a
party uses for its next message.  Two requirements:

1. **Perfect secrecy** - no pad is ever used twice, by the same or by different
   parties.  This is a safety property and must hold under every schedule and
   every delivery order.
2. **Few wasted pads** - when the protocol can no longer make progress, the
   number of never-used pads should be small, and in particular should not grow
   with ``n``.

Communication model
-------------------
``sender_observes_delivery`` selects between two readings of the network:

``True`` (*broadcast model*, the default)
    Delivery is an event on a shared broadcast medium; every party, the sender
    included, observes the delivered sequence.  This is the usual semantics of
    an atomic/total-order broadcast and it makes the delivered history common
    knowledge.  :class:`ChunkReserveProtocol` needs exactly this.

``False`` (*no-feedback model*)
    The sender gets no indication of when its own message lands.  Each party
    then knows its own full history plus the delivered history of the others,
    which is the model the two-party protocol in the problem statement uses.
    :class:`GrantProtocol` is designed for it.

All protocols here expose the same small interface so that ``simulation.py`` can
drive them interchangeably.
"""

from __future__ import annotations

from dataclasses import dataclass

DATA = "data"
REQUEST = "request"
GRANT = "grant"


@dataclass(frozen=True)
class Message:
    """A broadcast message.

    ``pad`` is the 1-based index of the one-time pad used to encrypt it, which
    is the only thing the other parties need in order to decrypt.  Control
    messages (``REQUEST``/``GRANT``) carry no payload and consume no pad; they
    still occupy a slot in the network's in-flight budget.
    """

    sender: int
    pad: int | None = None
    kind: str = DATA
    chunks: tuple[int, ...] = ()  # GRANT: the chunks being handed over
    to: int | None = None  # GRANT: the new owner


class PadReuseError(AssertionError):
    """Raised when a pad would be used a second time - a secrecy violation."""


@dataclass
class ChunkLayout:
    """Splits pads ``1..n`` into ``n // c`` chunks of ``c`` pads.

    Any remainder is absorbed by the final chunk, so every chunk holds at least
    ``c`` pads and the chunks exactly tile ``1..n``.
    """

    n: int
    c: int

    def __post_init__(self) -> None:
        if self.c < 1:
            raise ValueError("chunk size must be >= 1")
        if self.n < self.c:
            raise ValueError("need at least one full chunk of pads")
        self.count = self.n // self.c

    def chunk_of(self, pad: int) -> int:
        """Chunk holding ``pad`` (1-based pad index, 0-based chunk index)."""
        return min((pad - 1) // self.c, self.count - 1)

    def first_pad(self, chunk: int) -> int:
        return chunk * self.c + 1

    def size(self, chunk: int) -> int:
        return self.c if chunk < self.count - 1 else self.n - self.c * (self.count - 1)


class BaseProtocol:
    """Common plumbing: party bookkeeping and delivery fan-out."""

    name = "base"

    def __init__(
        self, n: int, d: int, m: int, *, sender_observes_delivery: bool = True
    ) -> None:
        if m < 2:
            raise ValueError("need at least two parties")
        if d < 0:
            raise ValueError("d must be non-negative")
        self.n = n
        self.d = d
        self.m = m
        self.sender_observes_delivery = sender_observes_delivery
        self._outbox: list[Message] = []

    # --- interface used by the simulator -------------------------------------
    def can_send(self, j: int) -> bool:
        raise NotImplementedError

    def send(self, j: int) -> Message:
        raise NotImplementedError

    def deliver(self, msg: Message) -> None:
        for j in range(self.m):
            if j == msg.sender and not self.sender_observes_delivery:
                continue
            self.observe(j, msg)

    def observe(self, j: int, msg: Message) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        """Give the protocol a chance to queue control traffic."""

    def take_control_messages(self) -> list[Message]:
        """Control traffic the protocol wants to emit, oldest first."""
        out, self._outbox = self._outbox, []
        return out

    def has_spare_capacity(self) -> bool:
        """True while pads remain that the protocol has not yet allocated.

        Used to state wait-freedom precisely: a party may only be unable to
        send once this is False.  A party blocked while this is True is
        waiting on the network, which is the failure the chunk size rules out.
        """
        return True

    def waste_breakdown(self) -> dict[str, int]:
        """Per-protocol explanation of the pads left over (for the write-up)."""
        return {}


# ---------------------------------------------------------------------------
# The main protocol
# ---------------------------------------------------------------------------


@dataclass
class _Ledger:
    """One party's copy of the state derived from the delivered history.

    In the broadcast model every party observes the same delivered sequence, so
    all ``m`` copies are always identical - ``simulation.py`` asserts this.  The
    copies are kept separate anyway so that the no-feedback model can be
    simulated faithfully (there the sender's copy falls behind, which is exactly
    why this protocol needs the broadcast model).
    """

    reserve: list[int | None]
    next_chunk: int


@dataclass
class _Cursor:
    """A party's private position: nobody else can see this."""

    current: int
    pos: int = 0


class ChunkReserveProtocol(BaseProtocol):
    """Chunk-reserve allocation.  Waste is ``O(m*d)``, independent of ``n``.

    Pads are grouped into chunks of ``c = d`` pads.  Every party owns two
    chunks at a time: the ``current`` one it is drawing pads from (private
    state, nobody else knows how far along it is) and a ``reserve`` chunk that
    is public.  The ledger rule is a single line:

        when a delivered message from party ``j`` uses a pad inside
        ``reserve[j]``, set ``reserve[j]`` to the next never-assigned chunk.

    Replaying that rule over the delivered sequence gives every party the same
    reserve map, so the reserves partition the chunk space: a chunk is handed to
    exactly one party, ever.

    **Safety.**  A party draws pads only from a chunk that was its own reserve,
    reserves are pairwise distinct and no chunk is assigned twice, therefore no
    pad is ever used twice.  This holds for any schedule and any delivery order;
    no timing assumption is involved.

    **Wait-freedom.**  A party that is allowed to put another message on the
    network has at most ``d - 1`` of its own messages undelivered.  If its
    current chunk still has pads it can send.  Otherwise it has already sent
    ``c = d`` messages from that chunk, so at least ``c - (d - 1) = 1`` of them
    has been delivered and its reserve has therefore advanced.  Either way it can
    send: the protocol never makes a party wait on the network while unassigned
    chunks remain.  ``c = d`` is exactly the threshold - with ``c = d - 1`` a
    party can have its whole chunk in flight and be stuck, which
    ``test_protocol.py`` demonstrates.  The argument only uses "at most ``d``
    undelivered", so it holds whether that bound is read globally or per party.

    **Waste.**  When the chunks run out each party is holding at most one
    untouched reserve (``c`` pads) and one partly used current chunk (``c - 1``
    unused pads), so at most ``m * (2d - 1)`` pads are wasted, plus whatever the
    final chunk absorbed from ``n % c``.  An idle party's current chunk *is* its
    reserve, so it wastes only ``d``.  Crucially the bound does not mention
    ``n``: doubling the number of pads does not cost a single extra wasted pad.
    """

    name = "chunk-reserve"

    def __init__(
        self,
        n: int,
        d: int,
        m: int,
        *,
        chunk_size: int | None = None,
        sender_observes_delivery: bool = True,
    ) -> None:
        super().__init__(n, d, m, sender_observes_delivery=sender_observes_delivery)
        # c = d is the smallest chunk size that keeps the protocol wait-free;
        # `chunk_size` exists so the tests can show that c = d - 1 stalls.
        self.layout = ChunkLayout(n, chunk_size if chunk_size is not None else d)
        if self.layout.count < m:
            raise ValueError(
                f"n={n} gives only {self.layout.count} chunks of {self.layout.c}; "
                f"need at least m={m}"
            )
        self.views = [_Ledger(reserve=list(range(m)), next_chunk=m) for _ in range(m)]
        self.cursors = [_Cursor(current=j) for j in range(m)]

    # --- party actions -------------------------------------------------------
    def _next_chunk_for(self, j: int) -> int | None:
        """Chunk party ``j`` would draw its next pad from, or ``None`` if stuck."""
        cur = self.cursors[j]
        if cur.pos < self.layout.size(cur.current):
            return cur.current
        nxt = self.views[j].reserve[j]
        return None if nxt is None or nxt == cur.current else nxt

    def can_send(self, j: int) -> bool:
        return self._next_chunk_for(j) is not None

    def send(self, j: int) -> Message:
        chunk = self._next_chunk_for(j)
        if chunk is None:
            raise RuntimeError(f"party {j} has no pad available")
        cur = self.cursors[j]
        if chunk != cur.current:
            cur.current, cur.pos = chunk, 0
        pad = self.layout.first_pad(chunk) + cur.pos
        cur.pos += 1
        return Message(sender=j, pad=pad)

    def observe(self, j: int, msg: Message) -> None:
        if msg.kind != DATA or msg.pad is None:
            return
        view = self.views[j]
        chunk = self.layout.chunk_of(msg.pad)
        if view.reserve[msg.sender] != chunk:
            # A straggler from a chunk the sender has already opened; the rule
            # is idempotent, so there is nothing to do.
            return
        if view.next_chunk < self.layout.count:
            view.reserve[msg.sender] = view.next_chunk
            view.next_chunk += 1
        else:
            view.reserve[msg.sender] = None

    # --- reporting -----------------------------------------------------------
    def has_spare_capacity(self) -> bool:
        return self.views[0].next_chunk < self.layout.count

    def waste_bound(self) -> int:
        """Worst-case unused pads guaranteed by the analysis above."""
        tail = self.layout.size(self.layout.count - 1) - self.layout.c
        return self.m * (2 * self.layout.c - 1) + tail

    def waste_breakdown(self) -> dict[str, int]:
        held_reserves = {r for v in self.views for r in v.reserve if r is not None}
        in_current = sum(
            self.layout.size(cur.current) - cur.pos for cur in self.cursors
        )
        return {
            "chunks_assigned": min(self.views[0].next_chunk, self.layout.count),
            "chunks_total": self.layout.count,
            "untouched_reserves": len(
                held_reserves - {cur.current for cur in self.cursors}
            ),
            "pads_left_in_current_chunks": in_current,
        }


# ---------------------------------------------------------------------------
# Baselines and a no-feedback alternative
# ---------------------------------------------------------------------------


class StaticPartitionProtocol(BaseProtocol):
    """Split the pads into ``m`` fixed slices, one per party.

    Needs no coordination at all and is trivially secret, which is why it is the
    obvious first answer - but a party can only ever use its own slice, so a
    single talkative party wastes the other ``(m-1)/m`` of the pads.  It is here
    as the baseline that :class:`ChunkReserveProtocol` has to beat.
    """

    name = "static-partition"

    def __init__(
        self, n: int, d: int, m: int, *, sender_observes_delivery: bool = True
    ) -> None:
        super().__init__(n, d, m, sender_observes_delivery=sender_observes_delivery)
        self.bounds = [round(j * n / m) for j in range(m + 1)]
        self.next_pad = [self.bounds[j] + 1 for j in range(m)]

    def can_send(self, j: int) -> bool:
        return self.next_pad[j] <= self.bounds[j + 1]

    def send(self, j: int) -> Message:
        pad = self.next_pad[j]
        self.next_pad[j] += 1
        return Message(sender=j, pad=pad)

    def observe(self, j: int, msg: Message) -> None:
        return


class TwoPartyPointerProtocol(BaseProtocol):
    """The two-party protocol from the problem statement, with the gap fixed.

    Alice walks a pointer up from ``0``, Bob walks one down from ``n + 1``, and
    each ships its pointer along with the message.  Each party knows its own
    pointer exactly and the other's only as of the last delivery, so it has to
    assume the other has advanced by a further ``d``.

    The handout's guard is ``i2 - i1 - 1 >= d``, which is off by one: with
    ``d = 1``, ``i1 = a`` and ``i2 = a + 2`` the check passes and Alice takes pad
    ``a + 1``, while Bob's one undelivered message may already have used exactly
    that pad.  The correct guard, used here, is ``i2 - i1 - 1 >= d + 1``, and it
    wastes ``d + 1`` pads.  Only meaningful for ``m == 2``; it is the reference
    point the ``m``-party protocol generalises.
    """

    name = "two-party-pointer"

    def __init__(
        self,
        n: int,
        d: int,
        m: int = 2,
        *,
        handout_guard: bool = False,
        sender_observes_delivery: bool = False,
    ) -> None:
        if m != 2:
            raise ValueError("the pointer protocol is two-party only")
        super().__init__(n, d, 2, sender_observes_delivery=sender_observes_delivery)
        # handout_guard=True reproduces `i2 - i1 - 1 >= d` verbatim, which the
        # tests use to exhibit a real pad collision.
        self.margin = self.d if handout_guard else self.d + 1
        self.name = "two-party-pointer" + ("-handout" if handout_guard else "")
        # own[j] is j's own pointer; seen[j] is j's view of the other pointer.
        self.own = [0, n + 1]
        self.seen = [n + 1, 0]

    def can_send(self, j: int) -> bool:
        lo, hi = (self.own[0], self.seen[0]) if j == 0 else (self.seen[1], self.own[1])
        return hi - lo - 1 >= self.margin

    def send(self, j: int) -> Message:
        self.own[j] += 1 if j == 0 else -1
        return Message(sender=j, pad=self.own[j])

    def observe(self, j: int, msg: Message) -> None:
        if msg.sender == j or msg.pad is None:
            return
        # Messages may be delivered out of order - the handout only bounds how
        # many are outstanding, not how long any one of them takes.  Taking the
        # latest arrival at face value would let a party's view of the other
        # pointer move *backwards*, which is how a stale view turns into a pad
        # collision.  Each pointer only ever moves one way, so fold the
        # observations in that direction and the view stays sound.
        if j == 0:
            self.seen[0] = min(self.seen[0], msg.pad)  # Bob's pointer only falls
        else:
            self.seen[1] = max(self.seen[1], msg.pad)  # Alice's only rises


class GrantProtocol(BaseProtocol):
    """Static chunk ownership plus explicit, owner-serialised hand-offs.

    Built for the *no-feedback* model, where a party never learns when its own
    message was delivered.  :class:`ChunkReserveProtocol` cannot run there - a
    party's reserve advances on the delivery of its own message, and it cannot
    see that event - so ownership is moved a different way:

    * chunk ``C`` starts out owned by party ``C % m``;
    * a party running low broadcasts a ``REQUEST``;
    * on receiving one, a party with spare untouched chunks gives half of them
      away with a ``GRANT``, dropping them from its own pool *at send time*;
    * the recipient starts using them only once the ``GRANT`` is delivered.

    Safety is immediate and needs no timing argument: a chunk is only ever used
    by its owner, and ownership moves only when the owner unilaterally gives it
    up, so the window where a chunk is in flight belongs to nobody.  The price is
    that rebalancing costs a round trip, so a party can stall while a grant is
    in the air and slow delivery strands pads at quiet parties - the waste is
    schedule-dependent rather than bounded by ``O(m*d)``.
    """

    name = "grant"

    def __init__(
        self,
        n: int,
        d: int,
        m: int,
        *,
        chunk_size: int | None = None,
        sender_observes_delivery: bool = False,
    ) -> None:
        super().__init__(n, d, m, sender_observes_delivery=sender_observes_delivery)
        self.layout = ChunkLayout(n, chunk_size if chunk_size is not None else d)
        if self.layout.count < m:
            raise ValueError("need at least m chunks")
        # Untouched chunks each party owns, in its own view.  Only the owner's
        # own copy is authoritative for spending; the others are used to answer
        # requests and are kept in step by the delivered GRANT messages.
        self.pool: list[list[int]] = [
            sorted(c for c in range(self.layout.count) if c % m == j) for j in range(m)
        ]
        self.cursors: list[_Cursor | None] = [None] * m
        self.pending_request = [False] * m
        self.low_water = 2 * self.layout.c
        # Pads sitting in each pool, kept in step with `pool` so that `tick`
        # stays O(m) rather than O(number of chunks).
        self._pool_pads = [sum(self.layout.size(c) for c in pool) for pool in self.pool]

    # --- accounting ----------------------------------------------------------
    def _remaining(self, j: int) -> int:
        cur = self.cursors[j]
        left = 0 if cur is None else self.layout.size(cur.current) - cur.pos
        return left + self._pool_pads[j]

    def _take(self, j: int, chunks: list[int]) -> None:
        for c in chunks:
            self.pool[j].remove(c)
            self._pool_pads[j] -= self.layout.size(c)

    def _give(self, j: int, chunks: list[int]) -> None:
        self.pool[j] = sorted(self.pool[j] + chunks)
        self._pool_pads[j] += sum(self.layout.size(c) for c in chunks)

    def has_spare_capacity(self) -> bool:
        return any(self.pool)

    # --- party actions -------------------------------------------------------
    def can_send(self, j: int) -> bool:
        cur = self.cursors[j]
        return bool(self.pool[j]) or (
            cur is not None and cur.pos < self.layout.size(cur.current)
        )

    def send(self, j: int) -> Message:
        cur = self.cursors[j]
        if cur is None or cur.pos >= self.layout.size(cur.current):
            if not self.pool[j]:
                raise RuntimeError(f"party {j} has no pad available")
            cur = _Cursor(current=self.pool[j][0])
            self._take(j, [cur.current])
            self.cursors[j] = cur
        pad = self.layout.first_pad(cur.current) + cur.pos
        cur.pos += 1
        return Message(sender=j, pad=pad)

    def tick(self) -> None:
        for j in range(self.m):
            if self.cursors[j] is None:
                # Never spoken, so nothing to ask for.  It still holds one chunk
                # of its own, which is what it would start talking with.  Without
                # this, parties that have just given their pool away turn round
                # and ask for it back, and the chunks circulate among the quiet
                # parties instead of reaching the one that is actually talking.
                continue
            # One request per episode: it is cleared when a grant lands, so a
            # party that keeps spending keeps asking, and a party nobody can
            # help stops asking instead of flooding the network.
            if not self.pending_request[j] and self._remaining(j) <= self.low_water:
                self.pending_request[j] = True
                self._outbox.append(Message(sender=j, kind=REQUEST))

    def observe(self, j: int, msg: Message) -> None:
        if msg.kind == REQUEST:
            if j == msg.sender or len(self.pool[j]) < 2:
                return
            # A party that has never spoken can give away everything but one
            # chunk - it keeps that one so it can still answer if it ever wants
            # to.  A party that is itself talking gives away half.
            keep = 1 if self.cursors[j] is None else len(self.pool[j]) // 2
            give = self.pool[j][keep:]
            self._take(j, give)
            # The chunks leave our pool right now, before the grant is even in
            # the air, so we can never spend them afterwards.  That is what
            # makes the hand-off safe without any delivery feedback.
            self._outbox.append(
                Message(sender=j, kind=GRANT, chunks=tuple(give), to=msg.sender)
            )
        elif msg.kind == GRANT and msg.to == j:
            self._give(j, list(msg.chunks))
            self.pending_request[j] = False
