"""Sample coordinates. Pure: no HTML, no I/O, no clock.

Every number the browser needs is computed here and travels to it in the JSON
island, so Python is the single source of truth for the layout and these functions
are what the tests pin.

The two panels deliberately share one ``XScale``. That is what makes the crosshair a
single ``<line>`` spanning both charts rather than two lines that have to be kept in
step.
"""

import datetime as dt
from collections.abc import Iterable
from collections.abc import Sequence
from math import ceil
from math import floor

import attrs
from health_data_service.data_types import IntervalSample
from health_data_service.data_types import Sample
from health_data_service.sleep_types import SleepStage

from sleep_dash.timeline import STAGE_ORDER

VIEW_W = 1000
VIEW_H = 420

PAD_L = 54  # room for 3-digit bpm labels and the lane names
PAD_R = 12
PAD_T = 10

STAGE_H = 150
PANEL_GAP = 14
AXIS_H = 22

PLOT_X0 = PAD_L
PLOT_X1 = VIEW_W - PAD_R
PLOT_W = PLOT_X1 - PLOT_X0

STAGE_Y0 = PAD_T
STAGE_Y1 = STAGE_Y0 + STAGE_H

HR_Y0 = STAGE_Y1 + PANEL_GAP
HR_Y1 = VIEW_H - AXIS_H
HR_H = HR_Y1 - HR_Y0

# The crosshair spans both panels AND the gap between them. This is the whole
# reason the two charts live inside one <svg>.
CROSSHAIR_Y0 = STAGE_Y0
CROSSHAIR_Y1 = HR_Y1

# A one-minute stage on an eight-hour axis is under two units wide; without a floor
# it would round away to nothing and a real wake would vanish.
MIN_BAR_W = 1.0

# Bar height as a fraction of its lane, leaving a visible channel between lanes.
BAR_FILL = 0.62

# Heart-rate axis snapping.
HR_SNAP = 5.0
HR_PAD = 2.0
HR_MIN_SPAN = 20.0
HR_FALLBACK = (50.0, 70.0)

TICK_STEPS_MINUTES = (15, 30, 60, 120, 180, 360)
TARGET_TICKS = 8


@attrs.frozen
class XScale:
    """Time to horizontal position. Shared by both panels."""

    t0: dt.datetime
    t1: dt.datetime

    @property
    def span_seconds(self) -> float:
        span = (self.t1 - self.t0).total_seconds()
        # A zero-length or inverted session still has to render something rather
        # than dividing by zero.
        return span if span > 0 else 60.0

    def x(self, timestamp: dt.datetime) -> float:
        offset = (timestamp - self.t0).total_seconds()
        return PLOT_X0 + offset / self.span_seconds * PLOT_W

    def x_of_minute(self, minute: int, minutes: int) -> float:
        """The centre of a minute -- where the crosshair snaps.

        Must agree with ``timeline``, which samples both series at the midpoint of
        each minute. If these two drift apart the readout and the vertical bar end
        up describing different instants.
        """
        span = minutes if minutes > 0 else 1
        return PLOT_X0 + (minute + 0.5) / span * PLOT_W


def hr_bounds(values: Sequence[float]) -> tuple[float, float]:
    """A padded, snapped bpm range with a floor on its span.

    The minimum span keeps a flat trace from rendering as a wild squiggle across the
    full panel height (and from dividing by zero).
    """
    if not values:
        return HR_FALLBACK
    lo = floor((min(values) - HR_PAD) / HR_SNAP) * HR_SNAP
    hi = ceil((max(values) + HR_PAD) / HR_SNAP) * HR_SNAP
    if hi - lo < HR_MIN_SPAN:
        middle = (hi + lo) / 2.0
        lo = floor((middle - HR_MIN_SPAN / 2) / HR_SNAP) * HR_SNAP
        hi = lo + HR_MIN_SPAN
    return lo, hi


@attrs.frozen
class HrScale:
    lo: float
    hi: float

    @property
    def span(self) -> float:
        span = self.hi - self.lo
        return span if span > 0 else HR_MIN_SPAN

    def y(self, bpm: float) -> float:
        return HR_Y0 + (self.hi - bpm) / self.span * HR_H

    def bpm_at(self, y: float) -> float:
        """Inverse of ``y``. Used by tests to read the drawn line back."""
        return self.hi - (y - HR_Y0) / HR_H * self.span

    def ticks(self) -> list[float]:
        """Three gridlines: bottom, middle, top."""
        return [self.lo, (self.lo + self.hi) / 2.0, self.hi]


def lanes(present: Iterable[SleepStage]) -> tuple[SleepStage, ...]:
    """The stage lanes to draw, top to bottom.

    LIGHT and DEEP are always included so a sparse night is not rendered as one fat
    bar filling the panel. UNKNOWN earns a lane only when the night actually has
    unknown samples, so the common case uses the full height across four lanes.
    """
    have = set(present)
    have.update({SleepStage.LIGHT, SleepStage.DEEP})
    return tuple(stage for stage in STAGE_ORDER if stage in have)


def lane_geometry(index: int, count: int) -> tuple[float, float]:
    """(y, height) of the bar in lane ``index`` of ``count``."""
    lane_height = STAGE_H / max(1, count)
    bar_height = lane_height * BAR_FILL
    y = STAGE_Y0 + index * lane_height + (lane_height - bar_height) / 2.0
    return y, bar_height


def lane_centre(index: int, count: int) -> float:
    lane_height = STAGE_H / max(1, count)
    return STAGE_Y0 + index * lane_height + lane_height / 2.0


@attrs.frozen
class Bar:
    stage: SleepStage
    x: float
    y: float
    width: float
    height: float


def stage_bars(
    samples: Sequence[IntervalSample[SleepStage]],
    xs: XScale,
    lane_order: Sequence[SleepStage],
) -> list[Bar]:
    """One bar per stage interval, in chronological order.

    Chronological because a later overlapping interval must paint over an earlier
    one -- the same rule ``timeline`` applies when assigning minutes.
    """
    index = {stage: position for position, stage in enumerate(lane_order)}
    bars: list[Bar] = []
    for sample in sorted(samples, key=lambda s: s.timestamp):
        stage = sample.value if sample.value in index else SleepStage.UNKNOWN
        if stage not in index:
            continue
        y, height = lane_geometry(index[stage], len(lane_order))
        left = xs.x(sample.timestamp)
        width = max(MIN_BAR_W, xs.x(sample.end_timestamp) - left)
        bars.append(Bar(stage=stage, x=left, y=y, width=width, height=height))
    return bars


def hr_paths(
    runs: Sequence[Sequence[Sample[float]]], xs: XScale, ys: HrScale
) -> list[list[tuple[float, float]]]:
    """One list of points per gap-free run."""
    return [[(xs.x(s.timestamp), ys.y(s.value)) for s in run] for run in runs if run]


def tick_step_minutes(span_minutes: float, target: int = TARGET_TICKS) -> int:
    """The coarsest step that still gives a readable number of ticks."""
    for step in TICK_STEPS_MINUTES:
        if span_minutes / step <= target:
            return step
    return TICK_STEPS_MINUTES[-1]


@attrs.frozen
class TimeTick:
    timestamp: dt.datetime
    x: float


def time_ticks(xs: XScale, step_minutes: int | None = None) -> list[TimeTick]:
    """Ticks on round UTC boundaries.

    UTC, not local, because the server places them and cannot know the viewer's
    zone. At whole-hour offsets -- most of the world -- these land on round local
    hours; at :30 offsets the viewer sees correct times that are not round numbers.
    Re-placing them in JS would make the axis jump visibly on hydration, which is a
    worse trade. See plan.md.
    """
    span_minutes = xs.span_seconds / 60.0
    step = step_minutes or tick_step_minutes(span_minutes)
    delta = dt.timedelta(minutes=step)
    midnight = xs.t0.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (xs.t0 - midnight).total_seconds() / 60.0
    first = midnight + dt.timedelta(minutes=ceil(elapsed / step) * step)
    ticks: list[TimeTick] = []
    cursor = first
    while cursor <= xs.t1:
        ticks.append(TimeTick(timestamp=cursor, x=xs.x(cursor)))
        cursor += delta
    return ticks
