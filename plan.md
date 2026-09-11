# Cloud in a Bottle Sleep Dashboard

## Context

`ciab_sleep_dash` is an empty repo (LICENSE, `.gitignore`, a stale `AGENTS.md` copied
from the sibling connector). It needs to become a Cloud in a Bottle **consumer** app:
a dashboard that reads sleep data over the health-data service spec and renders one
page with two charts on a **shared time axis** — sleep stage and heart rate — where
hovering at a given minute drops a thin vertical bar across *both* charts and updates
a widget showing the time, sleep stage, and heart rate at that minute.

It exists because the existing [health-dashboard] sleep graph is a Chart.js
**categorical bar chart**: every stage sample becomes an equal-width column
(`barPercentage: 1, categoryPercentage: 1`), so `end_timestamp` is discarded and a
4-minute wake reads as wide as a 90-minute deep block. This app renders a true
hypnogram with time-proportional interval widths, and correlates it with heart rate
on one axis. It must look like it belongs beside health-dashboard, so the dark theme
is inherited exactly.

Sibling apps to mirror: `../ciab_garmin_connector` (the reference **provider**, and
the house style of record) and `../openhost_spec_mcp` (the only local **consumer**).

[health-dashboard]: https://github.com/cloud-in-a-bottle/health-dashboard

### Decisions locked in

| Question | Decision |
|---|---|
| Rendering | Server-rendered inline SVG + vanilla JS. **One `<svg>`, two stacked panels, one shared x-scale.** No CDN, no Chart.js, no uPlot, no npm, no template engine. |
| Night scope | Latest night by default, `?night=<session id>` for prev/next. Plain `<a>` links — works with JS off. |
| Timezone | **Browser-local.** Server emits `data-ts` instants with a UTC fallback in the text; one JS pass localises every label. |
| Also on the page | Summary tile row, stage legend, provider/staleness footer line. |
| Package | `sleep_dash`, `src/` layout, Python `==3.12.*`, Litestar + Hypercorn, uv + hatchling. |

---

## Verified spec behaviour

Everything below I confirmed by running the installed `health_data_service` package
(in `../ciab_garmin_connector/.venv`), not by reading it. These four facts drive the
whole design.

**1. One call feeds both charts.** `get_sleep_sessions_merged()` returns
`SleepSession.stages.samples` as real `IntervalSample[SleepStage]` — `end_timestamp`
preserved, `value` coerced to the enum — *and* `SleepSession.heart_rate.samples` as
`Sample[float]` bpm, in the same response.

**2. `/v1/time-series?metric=sleep_stages` is a trap.** It silently returns plain
`Sample` objects: `end_timestamp` **gone**, `value` left as a raw `str`. The spec
registers a structure hook for `Sample` that resolves by MRO, so it fires for
`IntervalSample` too. The session path survives only because
`SleepStages.samples` is annotated with the *parametrised generic*
`list[IntervalSample[SleepStage]]`, on which cattrs' single-dispatch raises and falls
through to the correct generated path.

> **Never source stage intervals from `get_time_series`.** It is the one API call that
> would quietly delete the exact field this app is being built to render.

**3. One unrecognised stage string blanks the entire dashboard.** `get_sleep_sessions_merged`
structures every provider's sessions in a *single* `converter.structure(...)` call, so
one bad sample takes down all sessions from all providers:

```
value='deep' -> OK      value='core' -> IterableValidationError
batch of 2 (1 good, 1 bad) -> IterableValidationError   <-- ALL sessions lost
```

Apple's `core`, polysomnography `n1`/`n2`/`n3`, or any future spec value does this.
A lenient structure hook is **mandatory**, not defensive.

**4. Naive timestamps structure cleanly, then explode far away.**
`'2026-06-15 05:00:00'` (a space separator — exactly what the spec's own `_to_params`
emits via `str(datetime)`) yields `tzinfo=None`, and the failure surfaces hundreds of
lines later as `TypeError: can't subtract offset-naive and offset-aware datetimes`
inside the geometry layer. Normalise at the gateway boundary.

Also relevant: durations are **minutes as float**; `efficiency` is already a percent
(do not ×100); every scalar is a wrapped object with a `.value` and every one is
`| None`; `_fan_out` treats **any** non-200 from a provider as "this provider has
nothing", silently; with zero *running* providers it still makes one un-targeted call,
so "discovery returned nothing" and "no data" are different states; the httpx timeout
is hardcoded to 30 s and is not ours to change.

---

## Palette

Inherited verbatim from health-dashboard so the two apps read as one system. I ran the
`dataviz` skill's validator over the categorical set rather than eyeballing it.

Surfaces: page `#0f172a`, card `#1e293b`, tile `#0f172a`. Text: primary `#e2e8f0`,
secondary `#94a3b8`, muted `#64748b`, dimmest `#475569`. Borders/grid `#334155`.
Font `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`.
Heart rate `#f43f5e`, fill `rgba(244,63,94,0.06)`.

**Stage colours:** deep `#6366f1`, light `#64748b`, rem `#06b6d4`, awake `#f59e0b`.

Validated against surface `#1e293b`, all pairs: CVD separation ΔE **16.0**,
normal-vision floor **16.9**, contrast all ≥3:1 — all pass. (The validator also flags
lightness-band and chroma-floor cohesion failures; those are inherited from
health-dashboard's palette and are not ours to "fix" given the brief.)

Two consequences that **are** ours to fix:

- **`unknown` may not be a fifth grey.** health-dashboard falls back to `#64748b` —
  literally identical to `light`. A distinct grey `#475569` is barely better: ΔE **10.9**
  against `light`, below the hard floor of 15 *even with full colour vision*. Render
  `unknown` as a **hatched `<pattern>` band** instead — texture is secondary encoding,
  and "we don't know" reading differently from a real stage is honest.
- **The cyan↔slate tritan ΔE is 7.3**, inside the 6–8 band that is legal *only* with
  secondary encoding. We have it by construction and must keep it: each stage owns a
  **fixed y-lane**, there is a legend, and the hover widget names the stage in words.
  Position, not colour, is the primary encoding. Do not collapse the lanes.

---

## Repository layout

The rule that keeps this testable: **`health.py` is the only module that may import
`health_data_service.client`, touch `httpx`, or read the environment.** Everything from
`nights.py` down is pure — no I/O, no clock, no env — which is what lets the entire
chart be unit-tested without HTTP.

```
openhost.toml          Manifest (consumer block, health_check, resources)
pyproject.toml         Deps, ruff/mypy/pytest config, hatch allow-direct-references
justfile  Dockerfile  .dockerignore  README.md  plan.md
AGENTS.md              EXISTS and is stale — rewrite (see below)

src/sleep_dash/
  config.py     Settings (frozen attrs) from env. No I/O. Guards the client's KeyError.
  health.py     Gateway: client lifecycle, lenient hook, tz normalisation, TTL cache.
  nights.py     Overlap grouping, provider dedupe, nap filter, night selection. Pure.
  timeline.py   Per-minute stage/HR lookup arrays, HR gap runs, stage totals. Pure.
  geometry.py   Layout constants + sample->coordinate functions. No HTML, no I/O.
  svg.py        geometry -> SVG element strings. No data access.
  view.py       PageView and its parts (Tile, LegendRow, Footer, Notice). Frozen attrs.
  page.py       _render(view) -> str, the _xxx() helpers, STYLE, SCRIPT, JSON island.
  routes/dash.py   GET / with owner guard + HTML exception handlers.
  app.py        create_app(...) factory, /health, lifespan, module-level `app`.

tests/          conftest.py fakes.py fixtures.py helpers.py + one test_*.py per module
```

Dependency direction is strictly
`routes -> page -> view -> svg -> geometry -> timeline -> nights`, with `routes -> health`.
The spec's *types* are the domain vocabulary and may be imported anywhere below `routes`.

---

## The chart

One `<svg viewBox='0 0 1000 420'>`. The two panels share an `XScale`; **the crosshair is
a single `<line>` from `y=10` to `y=398`**, spanning both panels and the gap between them.
That is the whole reason both charts live in one SVG rather than two.

```python
PAD_L, PAD_R, PAD_T = 54, 12, 10
PLOT_X0, PLOT_W     = 54, 934
STAGE_Y0, STAGE_Y1  = 10, 160          # hypnogram panel
HR_Y0, HR_Y1        = 174, 398         # heart-rate panel
CROSSHAIR_Y0, CROSSHAIR_Y1 = STAGE_Y0, HR_Y1     # spans both
MIN_BAR_W = 1.0        # a 1-minute stage stays visible
```

- **Stage interval -> `<rect>`** at `x(timestamp)`, width `max(MIN_BAR_W, x(end) - x(start))`,
  `y`/`height` from its lane. Drawn chronologically so a later overlapping interval wins —
  the same rule the minute scan uses. Per the dataviz mark spec, inset adjacent fills by
  1px each side for a 2px surface gap, `rx='2'`.
- **Heart rate -> one `<polyline>` + fill `<polygon>` per gap-free run**, split at
  `hr_gap_seconds` (600 s, matching health-dashboard's `GAP_THRESHOLD`). A run of a single
  sample renders as a `<circle>` — a one-point polyline draws nothing and would silently
  hide a real reading.
- **Lanes**: stages present, in `AWAKE, REM, LIGHT, DEEP, UNKNOWN` order, always including
  `LIGHT` and `DEEP`. `UNKNOWN` gets a lane only when the night has any.
- **HR y-bounds**: snap out to multiples of 5, minimum span 20 bpm so a flat trace neither
  divides by zero nor renders as a wild squiggle.
- **Ticks** at round UTC boundaries, step chosen from `(15, 30, 60, 120, 180, 360)` for ≤8 ticks.

> **Accepted cosmetic compromise.** Ticks sit on UTC boundaries because the server must
> place them deterministically. At whole-hour offsets — most of the world — they land on
> round local hours; at `:30` offsets (Kolkata, Adelaide) the viewer sees correct times
> that are not round numbers. Re-placing ticks in JS would make the axis visibly jump on
> hydration, which is worse. Document it; do not fix it.

### Hit-testing: a precomputed per-minute array

`timeline.py` builds parallel arrays indexed by minute-offset, emitted as a
`<script type='application/json'>` island (~4 KB for a 500-minute night; parallel arrays
rather than an array of objects, which would be ~8×). JS does an O(1) index, never a search:

```json
{"t0":"2026-09-09T22:10:00+00:00","minutes":500,
 "names":["Awake","REM","Light","Deep","Unknown"],
 "colors":["#f59e0b","#06b6d4","#64748b","#6366f1","#475569"],
 "stage":[2,2,3,3,-1],"hr":[62,61,null,59],
 "vw":1000,"x0":54,"w":934,"hrY0":174,"hrH":224,"hrLo":45,"hrHi":80}
```

Every geometry constant the browser needs travels in this dict, so **Python is the single
source of truth** and `test_geometry.py` covers the exact numbers the browser uses.

- **Stage per minute — midpoint rule.** Minute `m` gets the stage of the interval containing
  `start + 60m + 30`. Deterministic under overlapping intervals, under intervals that do not
  tile the session, and under sub-minute intervals. One forward scan with a pointer, O(n+m).
- **HR per minute — linear interpolation bounded by the gap threshold.** The polyline *is*
  linear interpolation; nearest-sample would make the widget disagree with the picture the
  user is pointing at. A minute inside a >600 s gap reads `—` *and* sits in a gap in the
  drawn line. That equivalence is the runner-up highest-value test.
- `stage[i] == -1` means "no stage data at this minute" and draws nothing — **distinct** from
  the `unknown` stage, which is a real reading.

### The JS (~70 lines, ES5-flavoured, one inline `<script>`)

1. **Localisation pass, first and unconditional** — the empty-state pages have timestamps too.
   `querySelectorAll('[data-ts]')` matches SVG `<text>` as readily as HTML `<time>`, so one
   pass localises the axis and the prose together. `data-fmt` is `hm` | `date` | `datetime`.
2. **Crosshair + readout.** `getScreenCTM().inverse()` to map client x into SVG user units —
   immune to CSS scaling, page zoom, and the horizontal scroll container
   (`getBoundingClientRect` would need `height:auto` to be load-bearing). `show(i)` early-returns
   when the minute has not changed, so a sweep costs at most `minutes` DOM writes, not one per
   pixel — no `requestAnimationFrame` needed. The crosshair `<g>` moves with a single
   `transform` write and is `pointer-events='none'`; an invisible `<rect id='hit'>` with
   `fill='none'` **and** `pointer-events='all'` (the `fill` alone receives nothing) is the target.
3. **Keyboard**: arrow keys step a minute, shift-arrow 15. The readout is deliberately **not**
   an `aria-live` region — announcing on every mousemove is unusable with a screen reader;
   `role='img'` + `aria-label` on the `<svg>` plus arrow-key nav is the accessible path.

**With JS off:** both charts, true widths, shared axis, tiles, legend, footer and prev/next
all work; times read as UTC with a visible zone label. The readout is `hidden` in the server
markup and unhidden only by the script, so no interaction is advertised that cannot happen.

---

## Manifest

```toml
[app]
name = "sleep-dash"
version = "0.1.0"

[runtime.container]
image = "Dockerfile"
port = 8080

[routing]
health_check = "/health"
public_paths = []          # the owner's own sleep data

[resources]
memory_mb = 256
cpu_cores = 0.25           # NOT cpu_millicores -- see below

[data]
app_data = false           # no state of its own; the only cache is in-process

[[services.v2.consumes]]
service = "github.com/imbue-openhost/health-data-service-spec"
shortname = "health"       # MUST equal config.DEFAULT_SHORTNAME
version = ">=0.1.0"
grants = ["full_access"]
```

`service` is deliberately the **pre-rename `imbue-openhost` string** — the spec client
hardcodes it as `SERVICE_URL` and the router matches a provider's service string against
the consumer's. The `cloud-in-a-bottle` URL would route to nothing, silently. There is no
`endpoint` key on the consumer side; that is provider-only.

**`cpu_cores`, not `cpu_millicores`.** health-dashboard uses the latter, but the connector's
`AGENTS.md` records as a first-hand deploy finding that it is silently ignored and yields the
0.1-core default, and the docs document `cpu_cores`. The payoff is asymmetric: if `cpu_cores`
is honoured we get 0.25; if not we fall back to 0.1 — exactly what `cpu_millicores` gets
anyway. A manifest test pins it so a future copy-paste cannot regress it.

> **Unverified: `grants`.** `openhost_spec_mcp` consumes this identical service with **no
> `grants` key** and works. Include it (superset of the known-working config) but keep it out
> of the manifest test's assertions, and **drop it first** if the deployed app gets no data.

---

## Two defences that are not optional

Both go in `health.py` and nowhere else.

```python
def _structure_stage(value: object, _: type) -> SleepStage:
    """An unrecognised stage becomes UNKNOWN rather than killing the response.

    Verified: the merged call structures every provider's sessions in ONE
    converter.structure() call, so one bad sample from one provider blanks the
    whole dashboard. Apple's "core" and n1/n2/n3 vocabularies do exactly this.
    """
    try:
        return SleepStage(value)
    except ValueError:
        log.warning("Unrecognised sleep stage %r; reading as unknown.", value)
        return SleepStage.UNKNOWN

converter.register_structure_hook(SleepStage, _structure_stage)
```

This mutates the spec's module-level converter singleton — acceptable because we are the
only consumer in this process, but it must stay confined to this module, carry that
docstring, and be pinned by a test.

```python
def _aware(ts: dt.datetime) -> dt.datetime:
    """A naive timestamp is a provider that forgot to say UTC, not local time."""
    return ts.replace(tzinfo=dt.UTC) if ts.tzinfo is None else ts.astimezone(dt.UTC)
```

Applied via `attrs.evolve` to `session.start`/`.end` and every stage and HR sample.

**Do not send `start`/`end` on the sleep-sessions request.** `_to_params` renders datetimes
with `str(v)` — a *space* separator, not `T` — and a strictly-parsing provider 400s, which
`_fan_out` reads as "this provider has nothing". `limit` alone is the only verified-safe call
shape. The cost is that `session_limit` (default 30, env-tunable) is a count, not a date range.
The snapshot is TTL-cached behind an `asyncio.Lock`, so prev/next navigation is free and a
refresh cannot re-fan-out to every provider.

---

## Edge cases

| Case | Handling |
|---|---|
| Env vars missing | `.get()` in config; `Settings.connected` False; `HealthUnavailable` before any client is built. **200** + "not connected" card. |
| Provider running, zero sessions | Distinct card: "N providers running but reported no sleep sessions." |
| `discover_providers()` empty | *Not* "no providers" — `_fan_out` still makes one un-targeted call. Footer says so; never claims an outage it cannot see. |
| `heart_rate is None` | HR panel keeps full height (crosshair span unchanged), centred note, `hr` all `null`, readout `—`. Symmetric for `stages is None` (lanes fall back to LIGHT+DEEP). |
| Duplicate sessions, 2 providers | Overlap-grouped. Winner by stage-sample count -> HR-sample count -> duration -> source alphabetically. **Losers never blended** — two providers disagree on where a boundary falls; footer says "also reported by oura". |
| Naps | `total_duration < 30 min`, falling back to `end - start` when None. Hidden from the list, **counted in the footer**. A `Settings` field, not a constant — 30 min hides real short nights for some people. |
| DST boundary | X-axis is uniform in *elapsed* time, so a fall-back night really is 25 wall-clock hours and local labels correctly show `01:00` twice. Server never touches a local zone. |
| Stages that don't tile | Uncovered minutes are `-1` and show a visible gap. **No gap-filling, ever.** |
| Overlapping intervals | Later wins, in both the scan and the draw order — one rule, two places, one test. |
| `?night=` unknown / aged out | Falls back to latest. A bookmark must never 404. A key naming a dedupe loser resolves to its winner. |
| Hostile `source` / session id | Everything through `html.escape`. The JSON island needs the one documented exception: HTML escaping does not apply inside `<script>`, so `json.dumps(...).replace(chr(60), chr(92) + "u003c")` — i.e. every `<` becomes its unicode-escape form, which is still valid JSON and makes a closing-tag sequence unrepresentable. |
| Zero-length session / flat HR | `XScale` clamps to a 1-minute span; `hr_bounds` enforces a 20 bpm minimum. |

**`?night=` is keyed on session id**, not date. A date key would have to be a *local* date,
which the server cannot know — that is the entire premise of the timezone scheme. An index
key would break the moment a new night arrives.

---

## Routes

`/health` is registered **on the app, not the dashboard router** — outside the owner guard
(the probe carries no owner header) and outside the exception handlers, so no health-service
state can reach it. It returns `{"status": "ok"}` unconditionally; failing it makes the router
restart-loop the container.

Exception -> HTML handlers on the router (never try/except in handlers, per house style):
`HealthUnavailable` -> **200** (a bottle with no health service configured is a valid,
complete page, not a server error); `HealthTransportError` -> **503** (something upstream
really did fail). Neither ever renders a stack trace or JSON.

---

## Test plan

TDD throughout — `AGENTS.md` mandates tests before business logic. House style: full-sentence
test names, `class TestXxx:` with a docstring saying why the group exists, hand-written fakes
(not `unittest.mock`), full annotations, `TestClient` via a module-local `Iterator[TestClient]`.

| Test | Asserts |
|---|---|
| `test_the_shortname_the_client_uses_is_the_one_the_manifest_declares` | `tomllib` consumes `shortname` == `config.DEFAULT_SHORTNAME` |
| `test_the_manifest_consumes_exactly_the_spec_service` | the `imbue-openhost` string, verbatim |
| `test_resources_use_cpu_cores_not_cpu_millicores` | key present / absent |
| `test_an_unrecognised_stage_becomes_unknown_instead_of_killing_the_response` | a `'core'` sample structures; sibling sessions survive |
| `test_a_naive_timestamp_is_read_as_utc_before_it_reaches_the_geometry` | no `TypeError`; `tzinfo is UTC` |
| `test_the_client_is_never_constructed_without_credentials` | `HealthUnavailable`, not `KeyError` |
| `test_two_page_loads_inside_the_ttl_make_one_round_trip` | fake call count == 1 |
| `test_the_widget_value_at_a_minute_is_the_value_the_line_is_drawn_at` | `timeline.hr[m]` == y-inverse of the rendered polyline at `x_of_minute(m)`, to 1 bpm |
| `test_a_minute_inside_a_ten_minute_gap_has_no_reading_and_no_line` | `hr[m] is None` **and** the minute falls between two runs |
| `test_a_minute_is_given_the_stage_covering_its_midpoint` | boundary minutes resolve one way only |
| `test_stage_intervals_that_leave_a_hole_produce_minus_one_not_a_guess` | no interpolation |
| `test_a_night_crossing_a_fall_back_boundary_is_measured_in_elapsed_minutes` | 9 UTC hours -> 540 minutes |
| `test_the_crosshair_spans_both_panels` | `CROSSHAIR_Y0 == STAGE_Y0`, `CROSSHAIR_Y1 == HR_Y1`, gap inside |
| `test_both_panels_use_one_x_scale` | same `XScale` instance drives bars and HR points |
| `test_the_hit_rect_can_receive_pointer_events` | `fill='none'` **and** `pointer-events='all'` |
| `test_a_single_sample_run_is_drawn_as_a_dot_not_dropped` | `<circle>` emitted |
| `test_no_clock_time_is_rendered_without_a_machine_readable_instant` | `HTMLParser` walk: every `\d{1,2}:\d{2}` text node sits in an element with a valid aware-UTC `data-ts` |
| `test_the_fallback_text_is_the_utc_rendering_of_its_own_data_ts` | JS-off is *correct*, not merely present |
| `test_the_night_title_is_localised_rather_than_dated_on_the_server` | headline carries `data-fmt='date'` |
| `test_unknown_stage_is_drawn_with_a_pattern_not_a_second_grey` | `fill='url(#unknown-hatch)'` |
| `test_stage_colours_match_the_health_dashboard_palette` | exact hex per stage |
| `test_the_json_island_cannot_close_its_own_script_element` | `</script` never appears literally |
| `test_a_missing_scalar_renders_an_em_dash_and_never_a_zero` | `None` != `0` |
| `test_health_answers_two_hundred_while_the_gateway_is_raising` | the restart-loop guard |
| `test_not_being_connected_is_a_two_hundred_page_not_an_error` | 200 + card |
| `test_zero_sessions_and_zero_providers_are_different_pages` | distinct card text |
| `test_the_earlier_link_is_a_plain_anchor_that_works_without_javascript` | `<a href='?night=…'>` |

**Highest-value test: `test_the_shortname_the_client_uses_is_the_one_the_manifest_declares`.**
It is the only failure here with *zero* diagnostic signal anywhere. The client builds
`{router}/api/services/v2/call/{shortname}`; a mismatch 404s, `_fan_out` filters it out, and
the merged call returns `[]`. No exception, no log line, no non-200 — a dashboard that says
"no sleep sessions" forever while the provider sits there full of data. Every other bug at
least announces itself. The sibling repo has the mirror-image test because the provider side
already got burned by `endpoint = "/v1/"` landing on `/v1/v1/metrics`.

Runner-up: `test_the_widget_value_at_a_minute_is_the_value_the_line_is_drawn_at` — the only
test tying the readout, the timeline array and the rendered polyline together.

---

## Execution phasing

Each phase ends green and with a visibly better page.

0. **Toolchain + manifest.** `pyproject.toml`, `justfile`, `Dockerfile`, `.dockerignore`,
   `openhost.toml`, `config.py`, `app.py` with `/health` only, manifest + config tests.
   Front-loaded deliberately: the manifest contract is where the silent failures live.
1. **Walking skeleton.** `view.py`, `page.py` shell + `STYLE` + notice cards,
   `routes/dash.py` with guard and HTML exception handlers, `HealthGateway` Protocol +
   `FakeHealthGateway`. `/` renders the dark shell with the "not connected" card. Proves
   the theme, the guard, the exception->HTML path, and `/health` surviving a raising gateway.
2. **Real data, no chart.** `health.py` (both defences, TTL cache, error mapping), `nights.py`,
   `tests/fixtures.py`. Page gains tiles, footer, working prev/next. Every spec trap defused.
3. **`timeline.py`** — pure. Per-minute arrays and gap runs.
4. **`geometry.py`** — pure. Scales, bounds, ticks, lanes, bars.
5. **`svg.py`** — the chart appears, static, correct, fully legible with no JS. Legend added.
6. **JSON island + JS** — localisation, crosshair, readout, keyboard. Feature-complete.
7. **Edge-case sweep**, then `README.md`, `plan.md`, and the `AGENTS.md` rewrite.

## AGENTS.md is stale and must be rewritten

It was copied from the connector and is wrong in four places: its opening sentence is
truncated mid-clause ("…sleep stage transitions and "); Project Structure says
`src/garmin_health/` with the connector's `routes -> service -> registry -> garmin/*`
dependency chain; the run command is `litestar run …` where both siblings use
`uv run hypercorn <pkg>.app:app --bind 0.0.0.0:8080 --reload`; and `requires-python = ">=3.12.*"`
is not a valid specifier (siblings pin `==3.12.*`). Its Formatting paragraph also carries a
dangling "(plan.md §6 says 119…)" reference — either write that section or drop the parenthetical.

## Verification

1. `just test` (→ `uv run pytest -x`) green; `just check` (ruff + mypy strict) clean.
2. `just run` with no `OPENHOST_*` vars set → `/` renders the dark shell with the "not
   connected" card at 200, and `/health` returns `{"status":"ok"}`. This is the degraded
   path the router sees first.
3. Point `OPENHOST_ROUTER_URL`/`OPENHOST_APP_TOKEN` at the local `ciab_garmin_connector`
   and confirm a real night renders: hypnogram widths proportional to `end_timestamp`,
   HR line broken across gaps, crosshair tracking both panels, widget matching the chart.
4. Load with JS disabled — both charts, tiles, legend, footer and prev/next must all work,
   times labelled UTC, no readout advertised.
5. Narrow the viewport to 360 px: the card scrolls horizontally rather than shrinking axis
   labels to 4 px (`min-width: 640px` on the SVG inside an `overflow-x: auto` wrapper).
6. `docker build -t sleep-dash .` succeeds (needs `git` in the image — the spec is a git dep).
7. If podman is available, run the `openhost[test-harness]` `OpenhostStack` end-to-end — it
   is the only thing that can settle the `grants` and `shortname` questions against a real router.
