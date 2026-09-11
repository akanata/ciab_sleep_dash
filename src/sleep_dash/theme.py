"""The palette, inherited verbatim from the health-dashboard app.

This app is meant to sit beside health-dashboard and read as one system, so these
values are copied from its templates rather than chosen. They live in one module
because both ``page.py`` (legend swatches, tiles) and ``svg.py`` (bars, lines) need
them and two copies would drift.

The categorical set was checked with the dataviz validator against the card surface
rather than by eye. The four real stages pass every legibility check: worst
adjacent-pair CVD separation dE 16.0, normal-vision floor 16.9, all four at or above
3:1 contrast on #1e293b.

Two results from that check are load-bearing and must not be "tidied" away:

1. UNKNOWN is NOT a fifth fill colour. health-dashboard falls back to #64748b for it
   -- identical to LIGHT -- and even a distinct grey (#475569) scores dE 10.9 against
   LIGHT, below the hard floor of 15 for *full colour vision*. It is drawn as a
   hatched band instead, so the difference survives being printed, being viewed with
   any form of colour vision deficiency, and meaning "we don't know" rather than
   being mistaken for a real stage.
2. The cyan/slate pair (REM against LIGHT) scores 7.3 under tritanopia, inside the
   band that is only legal with a secondary encoding. That encoding is the fixed
   per-stage lane in the hypnogram, plus the legend, plus the hover readout naming
   the stage in words. Position -- not colour -- is the primary encoding. Do not
   collapse the lanes onto one row.
"""

from enum import StrEnum

from health_data_service.sleep_types import SleepStage

# Surfaces
PAGE_BG = "#0f172a"
CARD_BG = "#1e293b"
TILE_BG = "#0f172a"

# Ink
TEXT = "#e2e8f0"
TEXT_SECONDARY = "#94a3b8"
TEXT_MUTED = "#64748b"
TEXT_DIM = "#475569"

# Lines
BORDER = "#334155"
GRID = "#1e293b"

# Accents, as health-dashboard's `C` object names them.
INDIGO = "#6366f1"
CYAN = "#06b6d4"
EMERALD = "#10b981"
AMBER = "#f59e0b"
ROSE = "#f43f5e"
PURPLE = "#a855f7"
SLATE = "#64748b"

ERROR_BG = "#7f1d1d"

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"

HR_STROKE = ROSE
HR_FILL = "rgba(244,63,94,0.06)"

CROSSHAIR = TEXT_SECONDARY

STAGE_COLOURS: dict[SleepStage, str] = {
    SleepStage.DEEP: INDIGO,
    SleepStage.LIGHT: SLATE,
    SleepStage.REM: CYAN,
    SleepStage.AWAKE: AMBER,
    # Referenced only by the hatch pattern's stroke; never used as a flat fill.
    SleepStage.UNKNOWN: TEXT_DIM,
}

STAGE_LABELS: dict[SleepStage, str] = {
    SleepStage.AWAKE: "Awake",
    SleepStage.REM: "REM",
    SleepStage.LIGHT: "Light",
    SleepStage.DEEP: "Deep",
    SleepStage.UNKNOWN: "Unknown",
}

# The id of the <pattern> svg.py emits for UNKNOWN. See the module docstring.
UNKNOWN_HATCH_ID = "unknown-hatch"
UNKNOWN_FILL = f"url(#{UNKNOWN_HATCH_ID})"


def stage_fill(stage: SleepStage) -> str:
    """The paint for a stage bar: a flat colour, or the hatch for UNKNOWN."""
    if stage is SleepStage.UNKNOWN:
        return UNKNOWN_FILL
    return STAGE_COLOURS[stage]


class Tone(StrEnum):
    """How prominently a notice card is drawn."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"
