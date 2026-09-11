"""The chart, as one SVG element. No data access, no I/O.

Both panels live in a single ``<svg>`` sharing one x-scale, which is what lets the
crosshair be a single ``<line>`` crossing them both instead of two lines kept in
step by script.
"""

import datetime as dt
from collections.abc import Sequence
from html import escape

import attrs
from health_data_service.sleep_types import SleepStage

from sleep_dash import geometry as geo
from sleep_dash import theme
from sleep_dash.nights import Night
from sleep_dash.timeline import Timeline
from sleep_dash.timeline import hr_runs

# Shrinks each bar by a unit on each side, so abutting stages read as two blocks
# rather than one -- but only where there is width to spare.
BAR_INSET = 1.0
BAR_INSET_MIN_WIDTH = 4.0

SVG_ID = "night-chart"
CROSSHAIR_ID = "crosshair"
CROSSHAIR_DOT_ID = "crosshair-dot"
HIT_ID = "hit"


@attrs.frozen
class ChartModel:
    """Everything ``render_chart`` draws."""

    xs: geo.XScale
    ys: geo.HrScale
    lane_order: tuple[SleepStage, ...]
    bars: tuple[geo.Bar, ...]
    hr_points: tuple[tuple[tuple[float, float], ...], ...]
    ticks: tuple[geo.TimeTick, ...]
    minutes: int
    has_stages: bool
    has_heart_rate: bool


def build_chart(night: Night, timeline: Timeline, *, gap_seconds: float) -> ChartModel:
    session = night.session
    xs = geo.XScale(
        t0=timeline.start,
        t1=timeline.start + dt.timedelta(minutes=timeline.minutes),
    )

    stage_samples = session.stages.samples if session.stages is not None else []
    lane_order = geo.lanes(s.value for s in stage_samples)
    bars = geo.stage_bars(stage_samples, xs, lane_order)

    hr_samples = session.heart_rate.samples if session.heart_rate is not None else []
    ys = geo.HrScale(*geo.hr_bounds([s.value for s in hr_samples]))
    paths = geo.hr_paths(hr_runs(hr_samples, gap_seconds=gap_seconds), xs, ys)

    return ChartModel(
        xs=xs,
        ys=ys,
        lane_order=tuple(lane_order),
        bars=tuple(bars),
        hr_points=tuple(tuple(p) for p in paths),
        ticks=tuple(geo.time_ticks(xs)),
        minutes=timeline.minutes,
        has_stages=bool(stage_samples),
        has_heart_rate=bool(hr_samples),
    )


def _defs() -> str:
    """The hatch used for UNKNOWN.

    UNKNOWN is drawn as texture rather than a fifth grey because every grey close
    enough to fit the palette is too close to LIGHT to tell apart -- see theme.py.
    """
    return (
        "<defs>"
        f"<pattern id='{theme.UNKNOWN_HATCH_ID}' width='6' height='6' "
        "patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
        f"<rect width='6' height='6' fill='{theme.CARD_BG}'></rect>"
        f"<line x1='0' y1='0' x2='0' y2='6' stroke='{theme.TEXT_DIM}' "
        "stroke-width='3'></line>"
        "</pattern>"
        "</defs>"
    )


def _hit_rect() -> str:
    """The pointer target for both panels.

    ``fill='none'`` alone receives no pointer events in SVG; ``pointer-events='all'``
    is what makes an invisible rect hittable. One target covering both panels is
    only possible because they share an svg.
    """
    return (
        f"<rect id='{HIT_ID}' x='{geo.PLOT_X0}' y='{geo.STAGE_Y0}' width='{geo.PLOT_W}' "
        f"height='{geo.CROSSHAIR_Y1 - geo.STAGE_Y0}' fill='none' pointer-events='all'></rect>"
    )


def _panel_backgrounds() -> str:
    return (
        f"<rect x='{geo.PLOT_X0}' y='{geo.STAGE_Y0}' width='{geo.PLOT_W}' "
        f"height='{geo.STAGE_H}' rx='6' fill='{theme.TILE_BG}'></rect>"
        f"<rect x='{geo.PLOT_X0}' y='{geo.HR_Y0}' width='{geo.PLOT_W}' "
        f"height='{geo.HR_H}' rx='6' fill='{theme.TILE_BG}'></rect>"
    )


def _grid(chart: ChartModel) -> str:
    """Vertical gridlines spanning both panels, plus the bpm gridlines."""
    parts = [
        f"<line x1='{tick.x:.2f}' y1='{geo.STAGE_Y0}' x2='{tick.x:.2f}' "
        f"y2='{geo.CROSSHAIR_Y1}' stroke='{theme.BORDER}' stroke-width='0.5' "
        "opacity='0.55'></line>"
        for tick in chart.ticks
    ]
    for value in chart.ys.ticks():
        y = chart.ys.y(value)
        parts.append(
            f"<line x1='{geo.PLOT_X0}' y1='{y:.2f}' x2='{geo.PLOT_X0 + geo.PLOT_W}' "
            f"y2='{y:.2f}' stroke='{theme.BORDER}' stroke-width='0.5' opacity='0.55'></line>"
        )
        parts.append(
            f"<text x='{geo.PLOT_X0 - 8}' y='{y + 3.5:.2f}' text-anchor='end' "
            f"font-size='10' fill='{theme.TEXT_MUTED}'>{value:.0f}</text>"
        )
    return "".join(parts)


def _bar(bar: geo.Bar) -> str:
    x, width = bar.x, bar.width
    if width > BAR_INSET_MIN_WIDTH:
        x += BAR_INSET
        width -= 2 * BAR_INSET
    return (
        f"<rect class='stage' x='{x:.2f}' y='{bar.y:.2f}' width='{width:.2f}' "
        f"height='{bar.height:.2f}' rx='2' fill='{theme.stage_fill(bar.stage)}'></rect>"
    )


def _note(y: float, text: str) -> str:
    """A centred message where a panel has nothing to draw."""
    return (
        f"<text x='{geo.PLOT_X0 + geo.PLOT_W / 2:.2f}' y='{y:.2f}' text-anchor='middle' "
        f"font-size='12' fill='{theme.TEXT_DIM}'>{escape(text)}</text>"
    )


def _stage_panel(chart: ChartModel) -> str:
    parts = []
    for index, stage in enumerate(chart.lane_order):
        centre = geo.lane_centre(index, len(chart.lane_order))
        parts.append(
            f"<text x='{geo.PLOT_X0 - 8}' y='{centre + 3.5:.2f}' text-anchor='end' "
            f"font-size='10' fill='{theme.TEXT_MUTED}'>"
            f"{escape(theme.STAGE_LABELS[stage])}</text>"
        )
    if chart.has_stages:
        parts.extend(_bar(bar) for bar in chart.bars)
    else:
        parts.append(_note(geo.STAGE_Y0 + geo.STAGE_H / 2, "No sleep stages recorded"))
    return "".join(parts)


def _hr_run(points: Sequence[tuple[float, float]]) -> str:
    if len(points) == 1:
        x, y = points[0]
        # A one-point polyline draws nothing at all, which would silently hide a
        # real reading. Draw the dot instead.
        return f"<circle cx='{x:.2f}' cy='{y:.2f}' r='1.6' fill='{theme.HR_STROKE}'></circle>"
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    first_x, last_x = points[0][0], points[-1][0]
    return (
        f"<polygon class='hr-fill' points='{first_x:.2f},{geo.HR_Y1} {pts} "
        f"{last_x:.2f},{geo.HR_Y1}' fill='{theme.HR_FILL}'></polygon>"
        f"<polyline class='hr-line' points='{pts}' fill='none' "
        f"stroke='{theme.HR_STROKE}' stroke-width='1.5' stroke-linejoin='round' "
        "stroke-linecap='round'></polyline>"
    )


def _hr_panel(chart: ChartModel) -> str:
    if not chart.has_heart_rate:
        return _note(geo.HR_Y0 + geo.HR_H / 2, "No heart rate recorded for this night")
    return "".join(_hr_run(points) for points in chart.hr_points)


def _axis(chart: ChartModel) -> str:
    """Tick labels carrying the instant, so one JS pass localises chart and prose."""
    return "".join(
        f"<text class='axis' x='{tick.x:.2f}' y='{geo.VIEW_H - 7}' text-anchor='middle' "
        f"font-size='10' fill='{theme.TEXT_MUTED}' "
        f"data-ts='{escape(tick.timestamp.isoformat(), quote=True)}' data-fmt='hm'>"
        f"{tick.timestamp:%H:%M}</text>"
        for tick in chart.ticks
    )


def _crosshair() -> str:
    """One line across both panels, moved by a single transform write.

    ``pointer-events='none'`` so it never steals the pointer from the hit rect.
    """
    return (
        f"<g id='{CROSSHAIR_ID}' visibility='hidden' pointer-events='none'>"
        f"<line x1='0' y1='{geo.CROSSHAIR_Y0}' x2='0' y2='{geo.CROSSHAIR_Y1}' "
        f"stroke='{theme.CROSSHAIR}' stroke-width='1' stroke-dasharray='3 3'></line>"
        f"<circle id='{CROSSHAIR_DOT_ID}' cx='0' cy='0' r='3.5' fill='{theme.HR_STROKE}' "
        f"stroke='{theme.TILE_BG}' stroke-width='1.5' visibility='hidden'></circle>"
        "</g>"
    )


def render_chart(chart: ChartModel, *, label: str) -> str:
    return (
        f"<svg id='{SVG_ID}' class='chart' viewBox='0 0 {geo.VIEW_W} {geo.VIEW_H}' "
        f"tabindex='0' role='img' aria-label='{escape(label, quote=True)}'>"
        + _defs()
        + _panel_backgrounds()
        + _grid(chart)
        + _stage_panel(chart)
        + _hr_panel(chart)
        + _axis(chart)
        + _crosshair()
        + _hit_rect()
        + "</svg>"
    )


def chart_payload(chart: ChartModel, timeline: Timeline) -> dict[str, object]:
    """What the browser needs to run the crosshair.

    Every geometry constant travels in here rather than being duplicated in the
    script, so Python stays the single source of truth and test_geometry.py covers
    the exact numbers the browser uses.
    """
    return {
        "t0": timeline.start.isoformat(),
        "minutes": timeline.minutes,
        "names": [theme.STAGE_LABELS[s] for s in chart.lane_order],
        "colors": [theme.STAGE_COLOURS[s] for s in chart.lane_order],
        # The lane index in `stage` is an index into STAGE_ORDER, but the page only
        # renders the lanes actually present -- so remap onto `names`/`colors`.
        "stage": _remap_lanes(timeline.stage, chart.lane_order),
        "hr": list(timeline.hr),
        "vw": geo.VIEW_W,
        "x0": geo.PLOT_X0,
        "w": geo.PLOT_W,
        "hrY0": geo.HR_Y0,
        "hrH": geo.HR_H,
        "hrLo": chart.ys.lo,
        "hrHi": chart.ys.hi,
    }


def _remap_lanes(track: Sequence[int], lane_order: Sequence[SleepStage]) -> list[int]:
    from sleep_dash.timeline import STAGE_ORDER  # noqa: PLC0415 - avoids a cycle

    position = {stage: index for index, stage in enumerate(lane_order)}
    remapped: list[int] = []
    for value in track:
        if value < 0 or value >= len(STAGE_ORDER):
            remapped.append(-1)
            continue
        remapped.append(position.get(STAGE_ORDER[value], -1))
    return remapped
