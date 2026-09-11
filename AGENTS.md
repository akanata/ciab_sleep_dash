# Cloud in a Bottle Sleep Dashboard

This application is a consumer of the Cloud in a Bottle health data spec. Its focus
is sleep, inspired by the existing Health Dashboard sleep graph but expanding on it
with timestamped sleep stage transitions: a true hypnogram whose bar widths are
proportional to each stage's real duration, correlated with heart rate on a shared
time axis.

The existing health-dashboard draws stages as a Chart.js **categorical** bar chart
(`barPercentage: 1, categoryPercentage: 1`), which throws `end_timestamp` away and
renders a 4-minute wake as wide as a 90-minute deep block. Fixing that is the reason
this app exists.

## Project Status

**Landed — all of plan.md, Phases 0–7.** The toolchain (`pyproject.toml`, `uv.lock`,
`justfile`, `Dockerfile`, `openhost.toml`), the gateway (`config.py`, `health.py`),
the pure data layer (`nights.py`, `timeline.py`, `geometry.py`), rendering
(`theme.py`, `svg.py`, `view.py`, `page.py`), and the route (`routes/dash.py`,
`app.py`). 155 tests, mypy strict clean.

**Not built yet:** HRV (the spec serves it in the same payload as
`SleepSession.hrv`, and it would be a third panel), multi-night trends, and any
per-viewer settings — the app deliberately holds no state (`app_data = false`).

**Unverified against a live router:** the `grants = ["full_access"]` key in
`openhost.toml`. The sibling `openhost_spec_mcp` consumes the same service with no
`grants` key at all and works. If a deployed instance gets no data, drop that line
first. It is deliberately not asserted in `test_manifest.py`.

**Environment knobs:** `OPENHOST_ROUTER_URL` / `BOTTLE_ROUTER_URL`,
`OPENHOST_APP_TOKEN` / `BOTTLE_APP_TOKEN` (the new `BOTTLE_` spelling wins when both
are set), `SLEEP_DASH_SHORTNAME`, `SLEEP_DASH_SESSION_LIMIT` (default 30),
`SLEEP_DASH_CACHE_TTL_SECONDS` (300), `SLEEP_DASH_NAP_MINUTES` (30),
`SLEEP_DASH_HR_GAP_SECONDS` (600).

## Important References

- `plan.md` at the repo root is the design of record; read it before writing code.
- Cloud in a Bottle Health Data service spec: https://github.com/cloud-in-a-bottle/health-data-service-spec
- Cloud in a Bottle - Creating an App: https://cloudinabottle.org/docs/creating_an_app/overview.html
- Cloud in a Bottle - App Manifest Spec: https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html
- Cloud in a Bottle - Cross-App Services: https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html
- Health Dashboard: https://github.com/cloud-in-a-bottle/health-dashboard — the
  visual reference. Its palette is inherited verbatim; see `theme.py`.
- `../ciab_garmin_connector` is the sibling **provider** of this same spec and the
  house style of record. `../openhost_spec_mcp` is the other local **consumer**.

## Development Commands

`just` may not be installed; the underlying command is given for each.

- **Environment:** `just setup` → `uv sync` — manages the standard `.venv/`.
- **Run local dev server:** `just run`
  → `uv run hypercorn sleep_dash.app:app --bind 0.0.0.0:8080 --reload`
- **Lint, format, typecheck:** `just check`
  → `uv run ruff check --fix . && uv run ruff format . && uv run mypy`
- **Execute test suite:** `just test` → `uv run pytest -x`
- **Build container image:** `just build` → `docker build -t sleep-dash .`

## Code Style & Architecture

- **Language:** Python 3.12 (`requires-python = "==3.12.*"`).
- **Framework:** Litestar served by Hypercorn. There is **no CDN, no npm, no
  template engine and no frontend build.** The charts are server-rendered inline
  SVG; the only JavaScript is one inline progressive-enhancement script.
- **Formatting:** 4-space indentation, double quotes, ruff `line-length = 100`.
  Lint rules `E,F,B,UP,I,PLC0415`; isort `force-single-line`. `ruff format`
  reformats Python code blocks **inside Markdown**, which would rewrite the
  snippets in `plan.md` and this file — `extend-exclude = ["*.md"]` prevents that.
  Do not remove it.
- **Typing:** mypy `strict = true`, plus `follow_untyped_imports = true` — the spec
  package ships full annotations but no `py.typed` marker, so without it every
  import from it degrades to `Any`.
- **Wire types are attrs + cattrs, not pydantic.** Construct every spec type with
  **keyword arguments**: attrs moves overridden base fields to the end, so
  `HeartRate.__init__` is `(source, metric_id, display_name, unit, samples)` and
  positional construction produces garbage the moment the spec adds a field.

## Project Structure

```
src/sleep_dash/
  config.py    Settings from env. No I/O, never raises for missing credentials.
  health.py    The gateway. The ONLY module that may import the spec's client.
  nights.py    Overlap grouping, provider dedupe, nap filter, selection. Pure.
  timeline.py  Per-minute stage/HR arrays, HR gap runs, stage totals. Pure.
  geometry.py  Layout constants and sample -> coordinate functions. Pure.
  svg.py       geometry -> SVG element strings.
  theme.py     The palette, inherited from health-dashboard.
  view.py      PageView and build_view.
  page.py      The only HTML: render(view), STYLE, SCRIPT, the JSON island.
  routes/dash.py  GET / with the owner guard and HTML exception handlers.
  app.py       create_app factory, /health, module-level `app`.
tests/
```

Dependency direction is strictly
`routes -> page -> view -> svg -> geometry -> timeline -> nights`, with
`routes -> health`. **`health.py` is the only module that may import
`health_data_service.client`, touch httpx, or read the environment.** Everything
from `nights.py` down is pure, which is what lets the whole chart be unit-tested
without HTTP.

## Critical Guardrails & Gotchas

**General**
- ALWAYS IMPLEMENT UNIT TESTS BEFORE BUSINESS LOGIC (test-driven development).

**Reading the spec — all four verified by running the installed package.**
- **Never read stage intervals from `get_time_series(metric="sleep_stages")`.** The
  spec registers a structure hook for `Sample` that resolves by MRO, so it fires for
  `IntervalSample` too and silently returns start-only samples with `end_timestamp`
  gone and `value` left a raw `str`. Stages survive **only** through
  `SleepSession.stages`, where the parametrised generic
  `list[IntervalSample[SleepStage]]` bypasses single-dispatch. That field is the
  entire point of this app.
- **One unrecognised stage string blanks the whole dashboard.**
  `get_sleep_sessions_merged` structures every provider's sessions in a *single*
  `converter.structure()` call, so one bad sample from one provider loses every
  session from every provider. `health._structure_stage` is the defence and is not
  optional. Apple's `core` and any `n1`/`n2`/`n3` vocabulary trigger it.
- **Naive timestamps structure cleanly and explode later.** The spec's `_to_params`
  serialises datetimes with `str(v)` — a *space* separator, not a `T` — and a
  provider echoing that back yields `tzinfo=None`, which raises
  `TypeError: can't subtract offset-naive and offset-aware datetimes` deep inside
  `geometry.py`. `health._aware` normalises at the boundary; do not move it.
- **Do not send `start`/`end` on the sleep-sessions request.** Same space-separator
  problem in reverse: a strictly-parsing provider answers 400, and `_fan_out` reads
  any non-200 as "this provider has nothing". `limit` alone is the only call shape
  verified to work.
- Durations are **minutes as float**. `efficiency` is **already a percentage** — do
  not multiply by 100. Every scalar is a wrapped object with a `.value`, and every
  one is `| None`.

**Serving.**
- `/health` stays 200 through every degraded state and is registered on the app, not
  on `dash_router` — outside the owner guard (the probe carries no owner header) and
  outside the exception handlers. Failing it makes the router restart-loop the
  container the owner needs in order to fix the problem.
- `HealthUnavailable` renders at **200**: a bottle with no provider installed is a
  complete, correct page. `HealthTransportError` renders at **503**. Neither ever
  shows a stack trace or JSON.
- `_fan_out` swallows every per-provider failure, so **the footer is the app's only
  outage signal**. It compares running providers against contributing ones. Do not
  simplify it away.
- `discover_providers() == []` does **not** mean "no providers": `_fan_out` still
  makes one un-targeted call in that case. `Snapshot.discovery_empty` keeps the two
  distinguishable.

**The chart.**
- **Both panels share one `XScale` inside one `<svg>`.** That is what makes the
  crosshair a single `<line>` crossing both charts rather than two lines kept in
  step by script. Splitting them into two SVGs breaks the central feature.
- `geometry.x_of_minute(m)` must equal `x(start + 60m + 30s)` — the midpoint, which
  is also where `timeline` samples both series. If those drift apart the readout
  describes a different instant than the bar it is beside.
- The readout value and the drawn line are the same number by construction (both
  linear interpolation). `test_the_widget_value_at_a_minute_is_the_value_the_line_is_drawn_at`
  is what keeps them that way.
- An invisible `<rect>` needs `fill='none'` **and** `pointer-events='all'`; the
  `fill` alone receives no events. The crosshair group needs `pointer-events='none'`
  or it steals the pointer from the hit rect.
- Stage intervals that leave a hole produce `-1` and a visible gap. **Never fill
  gaps.** `-1` is distinct from `SleepStage.UNKNOWN`, which is a real reading.

**Theme and colour.**
- The palette is inherited verbatim from health-dashboard so the two apps read as
  one system. Stage colours: deep `#6366f1`, light `#64748b`, rem `#06b6d4`, awake
  `#f59e0b`.
- **`UNKNOWN` must not be a fifth grey.** health-dashboard falls back to `#64748b`,
  identical to LIGHT; even a distinct `#475569` scores ΔE 10.9 against LIGHT, below
  the hard floor of 15 *for full colour vision*. It is drawn with a hatch
  `<pattern>` instead.
- The cyan/slate pair scores 7.3 under tritanopia, which is only legal with a
  secondary encoding. That encoding is the **fixed per-stage lane**, plus the legend,
  plus the readout naming the stage in words. Do not collapse the lanes onto one row.

**Time and timezone.**
- The viewer's timezone is unknown to the server, so **no clock time or date may be
  formatted into the markup as final text.** Every instant is emitted as a UTC
  rendering carrying `data-ts` (+ `data-fmt`), and one JS pass rewrites them.
  `test_no_clock_time_is_rendered_without_a_machine_readable_instant` walks the whole
  document to enforce it. This applies to **dates** as well as times: a 23:30 UTC
  night is a different calendar day either side of the Atlantic.
- Axis ticks sit on round **UTC** boundaries because the server must place them
  deterministically. At `:30`-offset zones the viewer sees correct times that are not
  round numbers. This is an accepted trade — re-placing them in JS makes the axis
  jump on hydration.
- `?night=` is keyed on **session id**, never on a date (which would have to be
  local) or an index (which shifts the moment a new night arrives).

**Providers disagreeing.**
- `get_sleep_sessions_merged` does not dedupe, so two watches give two sessions for
  one night. One session wins **wholesale** — blending scalars would produce numbers
  no provider would stand behind — and the losers are named in the footer.
- The nap filter is a `Settings` field, not a constant: 30 minutes hides real short
  nights for people with fragmented sleep. Hidden sessions are **counted in the
  footer**, never dropped silently.
