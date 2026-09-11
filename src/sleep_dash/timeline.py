"""Per-minute lookup arrays for the crosshair. Pure.

The crosshair has to answer "what was happening at this minute?" in O(1) while the
pointer moves, so the answer is precomputed here and shipped to the browser as two
parallel arrays. Parallel arrays rather than an array of objects: for a 500-minute
night that is roughly 4 KB instead of 8x that.

Both series are sampled at the MIDPOINT of each minute, which is also where the
crosshair snaps (``geometry.x_of_minute``). Sampling anywhere else would put the
readout and the vertical bar a few pixels out of step.
"""

import datetime as dt
from collections.abc import Sequence

import attrs
from health_data_service.data_types import IntervalSample
from health_data_service.data_types import Sample
from health_data_service.sleep_types import SleepStage

from sleep_dash.nights import Night

# Lane order, top to bottom. Conventional hypnogram reading: awake at the top,
# deep at the bottom, so "deeper sleep" is literally lower on the page.
STAGE_ORDER: tuple[SleepStage, ...] = (
    SleepStage.AWAKE,
    SleepStage.REM,
    SleepStage.LIGHT,
    SleepStage.DEEP,
    SleepStage.UNKNOWN,
)

_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_ORDER)}

# No stage data covers this minute. Deliberately distinct from SleepStage.UNKNOWN,
# which is a real reading meaning "the device recorded something it could not
# classify". -1 means "the device recorded nothing at all".
NO_STAGE = -1


@attrs.frozen
class Timeline:
    """One night, resampled to one entry per minute."""

    start: dt.datetime
    minutes: int
    stage: tuple[int, ...]
    hr: tuple[int | None, ...]


def _floor_minute(value: dt.datetime) -> dt.datetime:
    return value.replace(second=0, microsecond=0)


def _ceil_minute(value: dt.datetime) -> dt.datetime:
    floored = _floor_minute(value)
    return floored if floored == value else floored + dt.timedelta(minutes=1)


def window(night: Night) -> tuple[dt.datetime, dt.datetime]:
    """The union of the session and both series, snapped out to whole minutes.

    Widening rather than clamping: a heart-rate trace that runs past the session end
    is a real reading, and the stage lanes simply show nothing out there, which is
    accurate.
    """
    session = night.session
    starts = [session.start]
    ends = [session.end]
    if session.stages is not None and session.stages.samples:
        starts.append(min(s.timestamp for s in session.stages.samples))
        ends.append(max(s.end_timestamp for s in session.stages.samples))
    if session.heart_rate is not None and session.heart_rate.samples:
        starts.append(min(s.timestamp for s in session.heart_rate.samples))
        ends.append(max(s.timestamp for s in session.heart_rate.samples))
    start = _floor_minute(min(starts))
    end = _ceil_minute(max(ends))
    if end <= start:
        # A zero-length or inverted session still has to render something.
        end = start + dt.timedelta(minutes=1)
    return start, end


def _stage_track(
    samples: Sequence[IntervalSample[SleepStage]],
    start: dt.datetime,
    minutes: int,
) -> tuple[int, ...]:
    """Assign each minute the stage covering its midpoint.

    A later interval overrides an earlier one -- the same rule ``svg`` uses when it
    draws them in chronological order, so the array and the picture always agree.
    """
    track = [NO_STAGE] * minutes
    for sample in samples:
        stage_index = _STAGE_INDEX.get(sample.value, _STAGE_INDEX[SleepStage.UNKNOWN])
        # Minute m covers [start + 60m, start + 60(m+1)); its midpoint is at
        # 60m + 30. The midpoint lies inside [sample.timestamp, sample.end) when
        # m is in [ (ts - start - 30)/60 , (end - start - 30)/60 ).
        begin = (sample.timestamp - start).total_seconds()
        finish = (sample.end_timestamp - start).total_seconds()
        first = max(0, _ceil_div(begin - 30.0, 60.0))
        last = min(minutes, _ceil_div(finish - 30.0, 60.0))
        for minute in range(first, last):
            track[minute] = stage_index
    return tuple(track)


def _ceil_div(numerator: float, denominator: float) -> int:
    from math import ceil  # noqa: PLC0415 - local to keep the module import list flat

    return int(ceil(numerator / denominator))


def _hr_track(
    samples: Sequence[Sample[float]],
    start: dt.datetime,
    minutes: int,
    *,
    gap_seconds: float,
) -> tuple[int | None, ...]:
    """Linear interpolation between bracketing samples, broken across gaps.

    The drawn polyline *is* linear interpolation between samples, so reading the
    value any other way (nearest sample, say) would make the readout disagree with
    the line the reader is pointing at. A minute inside a gap wider than
    ``gap_seconds`` has no value here, and the line is broken there too.
    """
    track: list[int | None] = [None] * minutes
    if len(samples) < 2:
        if len(samples) == 1:
            # A lone sample covers only the minute it falls in.
            offset = (samples[0].timestamp - start).total_seconds()
            minute = int(offset // 60)
            if 0 <= minute < minutes:
                track[minute] = round(samples[0].value)
        return tuple(track)

    ordered = sorted(samples, key=lambda s: s.timestamp)
    cursor = 0
    for minute in range(minutes):
        moment = start + dt.timedelta(seconds=60 * minute + 30)
        while cursor + 1 < len(ordered) and ordered[cursor + 1].timestamp <= moment:
            cursor += 1
        left = ordered[cursor]
        if cursor + 1 >= len(ordered):
            break  # past the last sample
        right = ordered[cursor + 1]
        if moment < left.timestamp:
            continue  # before the first sample
        span = (right.timestamp - left.timestamp).total_seconds()
        if span > gap_seconds:
            continue  # inside a gap: no reading, and the line is broken here too
        if span <= 0:
            track[minute] = round(left.value)
            continue
        ratio = (moment - left.timestamp).total_seconds() / span
        track[minute] = round(left.value + (right.value - left.value) * ratio)
    return tuple(track)


def hr_runs(samples: Sequence[Sample[float]], *, gap_seconds: float) -> list[list[Sample[float]]]:
    """Split a trace into gap-free runs, one drawn polyline each."""
    if not samples:
        return []
    ordered = sorted(samples, key=lambda s: s.timestamp)
    runs: list[list[Sample[float]]] = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (current.timestamp - previous.timestamp).total_seconds() > gap_seconds:
            runs.append([current])
        else:
            runs[-1].append(current)
    return runs


def stage_totals(
    samples: Sequence[IntervalSample[SleepStage]],
) -> dict[SleepStage, float]:
    """Minutes per stage, measured from the interval widths themselves.

    Deliberately independent of the provider's own duration scalars: where the two
    disagree, that disagreement is information, and the legend says which is which.
    """
    totals: dict[SleepStage, float] = {}
    for sample in samples:
        minutes = (sample.end_timestamp - sample.timestamp).total_seconds() / 60.0
        totals[sample.value] = totals.get(sample.value, 0.0) + minutes
    return totals


def build_timeline(night: Night, *, gap_seconds: float) -> Timeline:
    start, end = window(night)
    minutes = max(1, int((end - start).total_seconds() // 60))
    session = night.session
    stage = (
        _stage_track(session.stages.samples, start, minutes)
        if session.stages is not None
        else (NO_STAGE,) * minutes
    )
    hr = (
        _hr_track(session.heart_rate.samples, start, minutes, gap_seconds=gap_seconds)
        if session.heart_rate is not None
        else (None,) * minutes
    )
    return Timeline(start=start, minutes=minutes, stage=stage, hr=hr)
