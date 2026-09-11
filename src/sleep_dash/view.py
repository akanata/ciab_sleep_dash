"""The value objects the page renders, and the pure function that builds them.

``build_view`` takes a Snapshot and returns everything the page needs, so the whole
rendering path can be tested without an app, a client, or a clock.
"""

import datetime as dt

import attrs
from health_data_service.data_types import ScalarMetric
from health_data_service.sleep_types import SleepSession
from health_data_service.sleep_types import SleepStage

from sleep_dash import theme
from sleep_dash.config import Settings
from sleep_dash.health import Snapshot
from sleep_dash.nights import Night
from sleep_dash.nights import nights_from
from sleep_dash.nights import select
from sleep_dash.svg import build_chart
from sleep_dash.svg import chart_payload
from sleep_dash.svg import render_chart
from sleep_dash.theme import Tone
from sleep_dash.timeline import build_timeline
from sleep_dash.timeline import stage_totals


@attrs.frozen
class Notice:
    """A card explaining why the page is not showing a chart."""

    tone: Tone
    title: str
    detail: str


@attrs.frozen
class Tile:
    """One cell of the summary row. ``value`` of None renders an em dash.

    Nothing here is ever derived: if a provider does not report efficiency, the page
    says so rather than computing a number the provider would not stand behind.
    """

    label: str
    value: str | None
    hint: str | None = None


@attrs.frozen
class LegendRow:
    name: str
    fill: str
    duration: str | None = None


@attrs.frozen
class PageView:
    """Everything ``page.render`` draws, assembled by ``build_view`` and passed down
    whole. A single value object rather than a dozen arguments: the page has several
    independent concerns and a render signature that long is one transposed argument
    away from a wrong page."""

    rendered_at: dt.datetime
    notices: tuple[Notice, ...] = ()
    tiles: tuple[Tile, ...] = ()
    legend: tuple[LegendRow, ...] = ()
    footer: tuple[str, ...] = ()
    # The night being shown, as instants. Rendered as a UTC fallback and localised
    # in the browser -- never formatted as a local date on the server, which cannot
    # know the viewer's zone.
    night_start: dt.datetime | None = None
    night_end: dt.datetime | None = None
    earlier_key: str | None = None
    later_key: str | None = None
    chart_svg: str | None = None
    chart_payload: dict[str, object] | None = None


NOT_CONNECTED = Notice(
    tone=Tone.INFO,
    title="No health data service is connected",
    detail=(
        "This app reads sleep data from a health data provider installed in the same "
        "bottle. Install one -- a Garmin, Oura or Apple Health connector -- and this "
        "page will fill in on its own."
    ),
)

UNREACHABLE = Notice(
    tone=Tone.ERROR,
    title="The health data service could not be reached",
    detail=(
        "The router or the provider did not answer in time. Nothing is wrong with "
        "your sleep data; reload in a moment."
    ),
)

NO_PROVIDERS = Notice(
    tone=Tone.INFO,
    title="No health data provider is running",
    detail=(
        "The service is reachable but no provider app is registered against it, so "
        "there is nothing to read sleep data from yet."
    ),
)

NO_SESSIONS = Notice(
    tone=Tone.INFO,
    title="No sleep sessions yet",
    detail=(
        "The provider is running but has not reported any sleep sessions. If it has "
        "only just been installed it may still be syncing."
    ),
)


def notice_view(notice: Notice, *, rendered_at: dt.datetime) -> PageView:
    """The page reduced to a single explanatory card."""
    return PageView(rendered_at=rendered_at, notices=(notice,))


def _value(scalar: ScalarMetric[float] | None) -> float | None:
    """The number out of a wrapped spec scalar, or None."""
    if scalar is None:
        return None
    value = scalar.value
    return float(value) if value is not None else None


def _hm(minutes: float | None) -> str | None:
    """Minutes to "7h 35m". Durations arrive from the spec in MINUTES, as floats."""
    if minutes is None:
        return None
    total = int(round(minutes))
    hours, rest = divmod(total, 60)
    return f"{hours}h {rest:02d}m" if hours else f"{rest}m"


def _share(part: float | None, whole: float | None) -> str | None:
    if part is None or not whole:
        return None
    return f"{part / whole * 100:.0f}% of asleep"


def _tiles(session: SleepSession) -> tuple[Tile, ...]:
    asleep = _value(session.total_duration)
    deep = _value(session.deep_sleep_duration)
    light = _value(session.light_sleep_duration)
    rem = _value(session.rem_sleep_duration)
    awake = _value(session.awake_time)
    efficiency = _value(session.efficiency)
    return (
        Tile("Asleep", _hm(asleep)),
        Tile("In bed", _hm(_value(session.time_in_bed))),
        Tile("Deep", _hm(deep), _share(deep, asleep)),
        Tile("Light", _hm(light), _share(light, asleep)),
        Tile("REM", _hm(rem), _share(rem, asleep)),
        Tile("Awake", _hm(awake)),
        Tile("Avg HR", _bpm(_value(session.average_heart_rate))),
        Tile("Lowest HR", _bpm(_value(session.lowest_heart_rate))),
        # Already a percentage on the wire. Multiplying by 100 here is the classic
        # way to ship a dashboard reporting 9790% efficiency.
        Tile("Efficiency", f"{efficiency:.0f}%" if efficiency is not None else None),
        Tile("Latency", _hm(_value(session.latency))),
        Tile("Sleep score", _score(_value(session.sleep_score))),
    )


def _bpm(value: float | None) -> str | None:
    return f"{value:.0f} bpm" if value is not None else None


def _score(value: float | None) -> str | None:
    # Structures to a float even when the provider sent an int.
    return f"{value:.0f}" if value is not None else None


def _legend(night: Night, lane_order: tuple[SleepStage, ...]) -> tuple[LegendRow, ...]:
    """Swatches with durations measured from the stage timeline itself.

    These can disagree with the provider's own duration scalars in the tiles above.
    That disagreement is information, not a bug, which is why the legend says where
    its numbers come from.
    """
    samples = night.session.stages.samples if night.session.stages is not None else []
    totals = stage_totals(samples)
    return tuple(
        LegendRow(
            name=theme.STAGE_LABELS[stage],
            fill=theme.stage_fill(stage),
            duration=_hm(totals.get(stage)),
        )
        for stage in lane_order
    )


def build_view(
    snapshot: Snapshot,
    night_key: str | None,
    settings: Settings,
    *,
    rendered_at: dt.datetime,
) -> PageView:
    """Assemble the dashboard from one snapshot."""
    nights, naps_hidden = nights_from(snapshot.sessions, nap_minutes=settings.nap_minutes)
    footer = _footer(snapshot, naps_hidden)

    if not nights:
        notice = NO_SESSIONS if (snapshot.running or snapshot.sessions) else NO_PROVIDERS
        return attrs.evolve(notice_view(notice, rendered_at=rendered_at), footer=footer)

    selection = select(nights, night_key)
    night = selection.night
    assert night is not None  # nights is non-empty, so select always resolves one

    timeline = build_timeline(night, gap_seconds=settings.hr_gap_seconds)
    chart = build_chart(night, timeline, gap_seconds=settings.hr_gap_seconds)
    label = (
        f"Sleep stages and heart rate, {timeline.minutes} minutes from "
        f"{timeline.start:%Y-%m-%d %H:%M} UTC"
    )

    sources = [night.session.source] if night.session.source else []
    if night.other_sources:
        sources.append(f"also reported by {', '.join(night.other_sources)}")

    return PageView(
        rendered_at=rendered_at,
        tiles=_tiles(night.session),
        legend=_legend(night, chart.lane_order),
        footer=(*tuple(f"data from {s}" for s in sources[:1]), *sources[1:], *footer),
        night_start=night.session.start,
        night_end=night.session.end,
        earlier_key=selection.earlier_key,
        later_key=selection.later_key,
        chart_svg=render_chart(chart, label=label),
        chart_payload=chart_payload(chart, timeline),
    )


def _footer(snapshot: Snapshot, naps_hidden: int = 0) -> tuple[str, ...]:
    """The app's only outage signal.

    ``_fan_out`` swallows every per-provider failure -- any non-200 is read as "this
    provider has nothing" -- so a provider that is up but erroring looks exactly like
    a quiet night. Counting running providers against contributing ones is the only
    way to notice.
    """
    parts: list[str] = []
    running = snapshot.running
    if running:
        parts.append(f"{len(running)} provider{'s' if len(running) != 1 else ''} running")
    if snapshot.discovery_empty:
        parts.append("could not list providers; asked the router directly")
    contributing = snapshot.contributing
    if running and contributing and len(contributing) < len(running):
        parts.append("at least one provider returned nothing")
    if naps_hidden:
        parts.append(
            f"{naps_hidden} session{'s' if naps_hidden != 1 else ''} under 30 minutes hidden"
        )
    return tuple(parts)
