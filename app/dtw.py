"""Band-constrained dynamic time warping for beat-grid alignment.

The reference beat grid (R) is aligned against a performed track's onset
times (O).  The Sakoe-Chiba band |i - j| <= band keeps the search local so
that a beat can only be matched to an onset close in index space, while the
gap penalty controls how cheaply extra onsets (inserted beats) or missing
onsets (dropped beats) are absorbed.

This is a semi-global (unanchored) DTW: entry is free along the top row and
left column, and the path may end anywhere on the bottom row or right
column, so recordings that start late, start with ornaments, end early, or
carry trailing onsets all align without penalising those border gaps.  The
band still bounds how many border beats may be skipped, which prevents the
alignment from collapsing to an empty match.

Costs are in milliseconds:

* diagonal (match)      : |O[j] - R[i]|
* off-diagonal (skip)   : gap_penalty_ms
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


class AlignmentError(ValueError):
    """Raised when alignment is impossible (empty/non-ascending input)."""


_INF = float("inf")


@dataclass
class MatchPair:
    """One step of the warping path."""

    ref_index: int | None
    onset_index: int | None
    ref_time: float | None
    onset_time: float | None
    deviation_ms: float | None  # onset_time - ref_time for matched beats
    kind: str  # "match" | "missing_beat" | "inserted_beat"


@dataclass
class DeviationInterval:
    """A maximal run of consecutive matched beats sharing one bias label.

    kind is:
      * "rushed"   : the playing is consistently early (deviation < -threshold)
      * "dragging" : the playing is consistently late  (deviation >  threshold)
      * "steady"   : deviation stays within +/- threshold
    """

    kind: str
    ref_start_index: int
    ref_end_index: int
    start_time_ms: float
    end_time_ms: float
    mean_deviation_ms: float
    min_deviation_ms: float
    max_deviation_ms: float
    std_deviation_ms: float
    beat_count: int
    pairs: List[MatchPair]


@dataclass
class AlignmentResult:
    pairs: List[MatchPair]
    intervals: List[DeviationInterval]
    matched_beats: int
    missing_beats: int
    inserted_beats: int
    mean_deviation_ms: float
    std_deviation_ms: float
    total_cost: float
    band: int
    gap_penalty_ms: float


def align_beats(
    ref_times: Sequence[float],
    onset_times: Sequence[float],
    band: int = 2,
    gap_penalty_ms: float = 200.0,
    deviation_threshold_ms: float = 50.0,
) -> AlignmentResult:
    """Align onset times against the reference beat grid.

    Parameters
    ----------
    ref_times:
        Reference beat positions in milliseconds, strictly ascending.
    onset_times:
        Performed note onset positions in milliseconds, strictly ascending.
    band:
        Sakoe-Chiba band radius in beat indices; a reference beat ``i`` can
        only match onset ``j`` when ``|i - j| <= band``.
    gap_penalty_ms:
        Extra cost of an off-diagonal step (one dropped or inserted beat).
    deviation_threshold_ms:
        Absolute deviation (ms) above which a run is labelled rushed/dragging
        when building continuous deviation intervals.
    """
    if not ref_times:
        raise AlignmentError("reference beat grid must not be empty")
    if not onset_times:
        raise AlignmentError("onset list must not be empty")
    if list(ref_times) != sorted(ref_times) or len(set(ref_times)) != len(ref_times):
        raise AlignmentError("reference times must be strictly ascending")
    if list(onset_times) != sorted(onset_times) or len(set(onset_times)) != len(onset_times):
        raise AlignmentError("onset times must be strictly ascending")
    if band < 1:
        raise AlignmentError("band must be >= 1")

    n, m = len(ref_times), len(onset_times)

    # Accumulated cost grid, 1-indexed: dp[i][j] aligns ref[:i] with ons[:j].
    # Semi-global DTW: entry is free anywhere on the top row and left column
    # (the recording may start with missing beats or with inserted onsets),
    # and the best endpoint is chosen on the bottom row or right column (the
    # recording may end early or carry trailing onsets).
    dp: List[List[float]] = [[_INF] * (m + 1) for _ in range(n + 1)]
    back: List[List[int]] = [[0] * (m + 1) for _ in range(n + 1)]
    # back: 1 = diagonal (match), 2 = down (missing beat), 3 = right (inserted)
    for j in range(m + 1):
        dp[0][j] = 0.0
        back[0][j] = 3
    for i in range(n + 1):
        dp[i][0] = 0.0
        back[i][0] = 2
    back[0][0] = 0

    for i in range(1, n + 1):
        j_lo = max(1, i - band)
        j_hi = min(m, i + band)
        for j in range(j_lo, j_hi + 1):
            diag = dp[i - 1][j - 1] + abs(onset_times[j - 1] - ref_times[i - 1])
            down = dp[i - 1][j] + gap_penalty_ms  # missing beat
            right = dp[i][j - 1] + gap_penalty_ms  # inserted beat
            # Prefer the diagonal on ties so matches win over skips.
            if diag <= down and diag <= right:
                dp[i][j], back[i][j] = diag, 1
            elif down <= right:
                dp[i][j], back[i][j] = down, 2
            else:
                dp[i][j], back[i][j] = right, 3

    # Best endpoint: the path must cover the whole reference grid (bottom
    # row) or the whole onset sequence (right column) -- only one-sided
    # border gaps are accepted, not simultaneous heavy drops on both sides.
    endpoint_candidates: List[tuple[float, int, int]] = []
    for j in range(max(1, n - band), min(m, n + band) + 1):
        if dp[n][j] < _INF:
            endpoint_candidates.append((dp[n][j], n, j))
    for i in range(max(1, m - band), n + 1):
        if dp[i][m] < _INF:
            endpoint_candidates.append((dp[i][m], i, m))
    if not endpoint_candidates:
        raise AlignmentError("no alignment path inside the band; widen the band")
    _, ei, ej = min(endpoint_candidates, key=lambda c: (c[0], -c[1], -c[2]))

    # Backtrack.
    raw_steps: List[tuple[int, int]] = []
    i, j = ei, ej
    while i > 0 and j > 0:
        step = back[i][j]
        raw_steps.append((step, i - 1, j - 1))
        if step == 1:
            i, j = i - 1, j - 1
        elif step == 2:
            i = i - 1
        else:
            j = j - 1
    prefix_missing = i  # reference beats before the alignment start
    prefix_inserted = j  # onsets before the alignment start
    raw_steps.reverse()

    pairs: List[MatchPair] = []
    for oj in range(prefix_inserted):  # leading inserted onsets
        pairs.append(MatchPair(None, oj, None, onset_times[oj], None,
                               "inserted_beat"))
    for ri in range(prefix_missing):  # leading missing beats
        pairs.append(MatchPair(ri, None, ref_times[ri], None, None,
                               "missing_beat"))
    for step, ri, oj in raw_steps:
        if step == 1:
            dev = onset_times[oj] - ref_times[ri]
            pairs.append(
                MatchPair(ri, oj, ref_times[ri], onset_times[oj], dev, "match")
            )
        elif step == 2:
            pairs.append(MatchPair(ri, None, ref_times[ri], None, None,
                                   "missing_beat"))
        else:
            pairs.append(MatchPair(None, oj, None, onset_times[oj], None,
                                   "inserted_beat"))
    # Trailing uncovered beats/onsets (endpoint reached the other border early).
    for ri in range(ei, n):
        pairs.append(MatchPair(ri, None, ref_times[ri], None, None,
                               "missing_beat"))
    for oj in range(ej, m):
        pairs.append(MatchPair(None, oj, None, onset_times[oj], None,
                               "inserted_beat"))

    intervals = _build_intervals(
        pairs, deviation_threshold_ms
    )

    deviations = [p.deviation_ms for p in pairs if p.kind == "match"]
    matched = len(deviations)
    missing = sum(1 for p in pairs if p.kind == "missing_beat")
    inserted = sum(1 for p in pairs if p.kind == "inserted_beat")
    mean_dev = sum(deviations) / matched if matched else 0.0
    std_dev = (
        sum((d - mean_dev) ** 2 for d in deviations) / matched
        if matched
        else 0.0
    ) ** 0.5

    return AlignmentResult(
        pairs=pairs,
        intervals=intervals,
        matched_beats=matched,
        missing_beats=missing,
        inserted_beats=inserted,
        mean_deviation_ms=round(mean_dev, 3),
        std_deviation_ms=round(std_dev, 3),
        total_cost=round(dp[ei][ej], 3),
        band=band,
        gap_penalty_ms=gap_penalty_ms,
    )


def _build_intervals(
    pairs: Sequence[MatchPair], threshold: float
) -> List[DeviationInterval]:
    """Split the matched beats into maximal same-bias runs.

    Missing/inserted beats break a run; consecutive matched beats with the
    same label (rushed / steady / dragging) are merged into one interval.
    """
    intervals: List[DeviationInterval] = []
    run: List[MatchPair] = []

    def flush() -> None:
        if not run:
            return
        devs = [p.deviation_ms for p in run]
        mean = sum(devs) / len(devs)
        std = (sum((d - mean) ** 2 for d in devs) / len(devs)) ** 0.5
        intervals.append(
            DeviationInterval(
                kind=label_for(devs[0], threshold),
                ref_start_index=run[0].ref_index,
                ref_end_index=run[-1].ref_index,
                start_time_ms=run[0].ref_time,
                end_time_ms=run[-1].ref_time,
                mean_deviation_ms=round(mean, 3),
                min_deviation_ms=round(min(devs), 3),
                max_deviation_ms=round(max(devs), 3),
                std_deviation_ms=round(std, 3),
                beat_count=len(run),
                pairs=list(run),
            )
        )

    for pair in pairs:
        if pair.kind != "match":
            flush()
            run = []
            continue
        label = label_for(pair.deviation_ms, threshold)
        if run and label_for(run[-1].deviation_ms, threshold) != label:
            flush()
            run = []
        run.append(pair)
    flush()
    return intervals


def label_for(deviation_ms: float, threshold: float) -> str:
    if deviation_ms < -threshold:
        return "rushed"
    if deviation_ms > threshold:
        return "dragging"
    return "steady"
