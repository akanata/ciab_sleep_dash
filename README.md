# Cloud in a Bottle Sleep Dashboard

A sleep dashboard for [Cloud in a Bottle](https://cloudinabottle.org). It reads
sleep data from whichever health-data provider apps are installed in your bottle —
a Garmin, Oura or Apple Health connector — and draws one night at a time.

## What it shows

Two charts on a **shared time axis**:

- a **hypnogram** — awake, REM, light and deep, each in its own lane, with every bar
  as wide as the stage actually lasted;
- your **heart rate** through the night, broken wherever the recording has a real
  gap rather than drawn straight across it.

Moving the pointer across either chart drops a thin vertical line through **both**,
and a readout above them shows the time, the sleep stage and the heart rate at that
minute. Arrow keys do the same thing a minute at a time, shift-arrow fifteen.

Below the charts: the night's summary figures as the provider reported them, a
legend whose durations are measured from the stage timeline itself, and a footer
saying which providers the data came from.

`← Earlier` and `Later →` step between nights. Each night is its own URL, so you can
bookmark one.

## How it differs from the Health Dashboard

The existing health-dashboard draws sleep stages as a categorical bar chart: every
stage becomes an equal-width column, so a four-minute wake looks as long as ninety
minutes of deep sleep. This app uses the interval end timestamps the spec actually
provides, so the picture is proportional to real time — and puts heart rate on the
same axis so you can see the two together.

It inherits health-dashboard's dark theme exactly, so the two sit side by side.

## Running it

```
just setup   # uv sync
just run     # uv run hypercorn sleep_dash.app:app --bind 0.0.0.0:8080 --reload
just test    # uv run pytest -x
just check   # ruff + mypy
```

The app reads `OPENHOST_ROUTER_URL` and `OPENHOST_APP_TOKEN` (the newer
`BOTTLE_`-prefixed spellings are also accepted and win when both are set). With
neither set it still starts and serves a page explaining that no health data service
is connected — that is the normal state of a fresh deployment, not an error.

## Things worth knowing

- **Times are shown in your browser's timezone.** The server only ever emits UTC and
  the page converts on arrival, so the same URL reads correctly wherever you open it.
  With JavaScript disabled everything still renders, labelled UTC.
- **It stores nothing.** No database, no settings, no persistent volume. Every read
  goes through the health service, cached in memory for five minutes.
- **Sessions under 30 minutes are treated as naps** and kept out of the night list.
  The footer says how many were hidden, and the threshold is configurable via
  `SLEEP_DASH_NAP_MINUTES`.
- **If two providers both report a night**, one is shown whole rather than averaging
  them together — they disagree about where stage boundaries fall, and a blend would
  be a number neither of them stands behind. The footer names the other one.
- **A blank dashboard is not necessarily a fault here.** The spec's client treats any
  error from a provider as "this provider has nothing", so the footer counts running
  providers against the ones that actually returned data and says when they differ.

See `plan.md` for the design of record and `AGENTS.md` for the working agreement.
