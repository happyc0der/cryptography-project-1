# test_protocol.py
import pandas as pd
from main import PointerGapProtocol


def _trace_iter(df):  # keep chronological order
    return df.reset_index(drop=True).iterrows()


def test_protocol_rules():
    n, d, m = 200, 5, 5
    sim = PointerGapProtocol(n=n, d=d, m=m, seed=123)
    res = sim.run(list(range(m)))

    # validate used indices and waste calculation is correct
    sent_actions = res["trace"][res["trace"]["action"] == "send"]
    sent_indices = sent_actions["index"].tolist()
    used = set(sent_indices)

    for index in used:
        assert 1 <= index <= n
    assert len(used) == res["used_indices_count"]
    assert res["wasted_pads"] == n - res["used_indices_count"]

    # check minimum gap between frontiers
    for _, row in _trace_iter(res["trace"]):
        f = row["frontiers"]
        for i in range(len(f) - 1):
            assert f[i + 1] - f[i] >= d

    # in-flight messages never exceed capacity d per sender
    inflight = [0] * sim.m
    for _, row in _trace_iter(res["trace"]):
        s = int(row["sender"]) - 1

        if row["action"] == "send":
            inflight[s] += 1
        else:
            inflight[s] -= 1
            assert inflight[s] >= 0
        for c in inflight:
            assert c <= d

    # frontiers move monotonically in correct directions
    last = [None] * sim.m
    for _, row in _trace_iter(res["trace"]):
        f = row["frontiers"]
        s = int(row["sender"]) - 1
        cur, prev = f[s], last[s]
        if prev is not None:
            if sim.direction_up[s]:
                assert cur >= prev
            else:
                assert cur <= prev
        last[s] = cur


# verify protocol produces identical results with the same random seed
def test_reproducibility_with_seed():
    n, d, m, seed = 200, 5, 5, 999
    r1 = PointerGapProtocol(n, d, m, seed).run(list(range(m)))
    r2 = PointerGapProtocol(n, d, m, seed).run(list(range(m)))
    assert r1["final_frontiers"] == r2["final_frontiers"]
    assert r1["used_indices_count"] == r2["used_indices_count"]
    assert r1["wasted_gap_values"] == r2["wasted_gap_values"]
    assert r1["wasted_total"] == r2["wasted_total"]
    assert r1["wasted_pads"] == r2["wasted_pads"]
    pd.testing.assert_frame_equal(
        r1["trace"].reset_index(drop=True), r2["trace"].reset_index(drop=True)
    )
