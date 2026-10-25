"""Multi-frame vote (plan §5.4, task C5). Tests: `tests/test_vote.py`."""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from ..models import DigitResult, LineReading


def vote_line(frames: Sequence[Sequence[DigitResult]], decimals: int) -> LineReading:
    """Combine the same line read from several frames into one LineReading.

    `frames[f][i]` is digit position i in frame f; all frames have the same length (else ValueError).
    Per position:
    - Only results with a value (not None) vote. The value with the most votes wins if it has a strict majority of
      ALL frames (more than half of len(frames), unknown results count as frames that did not vote for it).
    - Tie between values with the same count: no winner (unknown), even if one has higher confidence.
    - Winner's confidence = the mean confidence of the results that voted for it.
    - No winner: DigitResult(None, 0.0).
    No frames at all: ValueError.
    """
    if not frames:
        raise ValueError("vote_line needs at least one frame")
    width = len(frames[0])
    if any(len(frame) != width for frame in frames):
        raise ValueError("all frames must have the same number of digits")

    digits = []
    for i in range(width):
        results = [frame[i] for frame in frames]
        counts = Counter(d.value for d in results if d.value is not None)
        ranked = counts.most_common(2)
        if not ranked or ranked[0][1] * 2 <= len(frames):
            digits.append(DigitResult(None, 0.0))
            continue
        if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
            digits.append(DigitResult(None, 0.0))
            continue
        winner = ranked[0][0]
        voters = [d.confidence for d in results if d.value == winner]
        digits.append(DigitResult(winner, sum(voters) / len(voters)))
    return LineReading(digits=tuple(digits), decimals=decimals)
