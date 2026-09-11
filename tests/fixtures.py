"""Real spec objects to test against.

The canonical night is arithmetically coherent, so assertions can be derivations
rather than magic numbers: 480 minutes in bed, stage spans summing to exactly that,
470 of them asleep, hence 97.9% efficiency.

Every spec type is constructed with KEYWORD arguments. attrs moves overridden base
fields to the end, so ``HeartRate.__init__`` is ``(source, metric_id, ..., samples)``
-- positional construction silently produces garbage the moment the spec adds a field.
"""

import datetime as dt
from collections.abc import Sequence

from health_data_service.data_types import IntervalSample
from health_data_service.data_types import Sample
from health_data_service.sleep_types import Efficiency
from health_data_service.sleep_types import Score
from health_data_service.sleep_types import SleepSession
from health_data_service.sleep_types import SleepStage
from health_data_service.sleep_types import SleepStages
from health_data_service.specific_types import Duration
from health_data_service.specific_types import HeartRate
from health_data_service.specific_types import HeartRateAvg
from health_data_service.specific_types import HeartRateMin

# 22:10 UTC, a plausible bedtime that is also a different *date* in the Americas --
# which is exactly the case that catches a date formatted on the server.
T0 = dt.datetime(2026, 9, 9, 22, 10, tzinfo=dt.UTC)

# (minutes, stage). Sums to 480; 470 of them asleep.
CANONICAL_SPANS: tuple[tuple[int, SleepStage], ...] = (
    (90, SleepStage.LIGHT),
    (60, SleepStage.DEEP),
    (45, SleepStage.LIGHT),
    (40, SleepStage.REM),
    (10, SleepStage.AWAKE),
    (80, SleepStage.LIGHT),
    (55, SleepStage.DEEP),
    (50, SleepStage.REM),
    (50, SleepStage.LIGHT),
)


def stage_samples(
    start: dt.datetime, spans: Sequence[tuple[int, SleepStage]]
) -> list[IntervalSample[SleepStage]]:
    """Contiguous, non-overlapping stage intervals starting at ``start``."""
    samples: list[IntervalSample[SleepStage]] = []
    cursor = start
    for minutes, stage in spans:
        end = cursor + dt.timedelta(minutes=minutes)
        samples.append(IntervalSample(timestamp=cursor, value=stage, end_timestamp=end))
        cursor = end
    return samples


def hr_samples(
    start: dt.datetime,
    minutes: int,
    *,
    every: int = 2,
    base: float = 56.0,
    skip: range | None = None,
) -> list[Sample[float]]:
    """A heart-rate trace at ``every``-minute cadence.

    ``skip`` drops a span of minute offsets, to build the gap cases.
    """
    samples: list[Sample[float]] = []
    for offset in range(0, minutes, every):
        if skip is not None and offset in skip:
            continue
        # A gentle, deterministic wander so interpolation has something to chew on.
        value = base + (offset % 20) * 0.5
        samples.append(Sample(timestamp=start + dt.timedelta(minutes=offset), value=value))
    return samples


def session_from_samples(
    *,
    start: dt.datetime = T0,
    minutes: int = 30,
    session_id: str = "x",
    source: str = "garmin",
    stages: Sequence[IntervalSample[SleepStage]] | None = None,
    heart_rate: Sequence[Sample[float]] | None = None,
) -> SleepSession:
    """A session built from exactly the samples given, for the awkward cases:
    holes, overlaps, lone samples, traces running past the session end."""
    return SleepSession(
        start=start,
        end=start + dt.timedelta(minutes=minutes),
        id=session_id,
        stages=(SleepStages(source=source, samples=list(stages)) if stages is not None else None),
        heart_rate=(
            HeartRate(source=source, samples=list(heart_rate)) if heart_rate is not None else None
        ),
        source=source,
    )


def build_session(
    *,
    start: dt.datetime = T0,
    minutes: int = 480,
    session_id: str = "night-1",
    source: str = "garmin",
    spans: Sequence[tuple[int, SleepStage]] | None = None,
    with_stages: bool = True,
    with_heart_rate: bool = True,
    hr_every: int = 2,
    hr_skip: range | None = None,
    total_duration: float | None = 470.0,
    scalars: bool = True,
) -> SleepSession:
    end = start + dt.timedelta(minutes=minutes)
    spans = CANONICAL_SPANS if spans is None else spans

    stages = None
    if with_stages:
        stages = SleepStages(source=source, samples=stage_samples(start, spans))

    heart_rate = None
    if with_heart_rate:
        heart_rate = HeartRate(
            source=source,
            samples=hr_samples(start, minutes, every=hr_every, skip=hr_skip),
        )

    return SleepSession(
        start=start,
        end=end,
        id=session_id,
        stages=stages,
        heart_rate=heart_rate,
        total_duration=(
            Duration(value=total_duration, source=source) if total_duration is not None else None
        ),
        time_in_bed=Duration(value=float(minutes), source=source) if scalars else None,
        deep_sleep_duration=Duration(value=115.0, source=source) if scalars else None,
        light_sleep_duration=Duration(value=265.0, source=source) if scalars else None,
        rem_sleep_duration=Duration(value=90.0, source=source) if scalars else None,
        awake_time=Duration(value=10.0, source=source) if scalars else None,
        latency=Duration(value=12.0, source=source) if scalars else None,
        average_heart_rate=HeartRateAvg(value=58.0, source=source) if scalars else None,
        lowest_heart_rate=HeartRateMin(value=49.0, source=source) if scalars else None,
        efficiency=Efficiency(value=97.9, source=source) if scalars else None,
        sleep_score=Score(value=84.0, source=source) if scalars else None,
        source=source,
    )
