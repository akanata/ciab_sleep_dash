# Cloud in a Bottle Sleep Dashboard

This application implements a consumer of the Cloud in a Bottle health data
spec. Its focus is on sleep, inspired by the existing Health Dashboard sleep
graph but expanding on its capabilities with timestamped sleep stage
transitions and 

## Project Status

`plan.md` at the repo root is the design of record; read it before writing code.
Currently this is an empty repo.

## Important References

- Cloud in a Bottle Health Data service spec: https://github.com/cloud-in-a-bottle/health-data-service-spec
- Cloud in a Bottle - Creating an App: https://cloudinabottle.org/docs/creating_an_app/overview.html
- Cloud in a Bottle - App Manifest Spec: https://cloudinabottle.org/docs/creating_an_app/manifest_spec.html
- Cloud in a Bottle - Cross-App Services: https://cloudinabottle.org/docs/creating_an_app/cross_app_services.html
- Health Dashboard: https://github.com/cloud-in-a-bottle/health-dashboard

## Development Commands

- **Environment:** `uv sync` — manages the standard `.venv/`;
  `source .venv/bin/activate` still works. (The venv is `.venv/`, not `venv/`.)
- **Run local dev server:** `just run`
  → `litestar run --host 0.0.0.0 --port 8080 --reload`
- **Lint, format, typecheck:** `just check`
  → `ruff check --fix . && ruff format . && uv run mypy`
- **Execute test suite:** `just test` → `uv run pytest -x`
- **Build container image:** `just build` → `docker build -t sleep-dash .`

## Code Style & Architecture

- **Language:** Python 3.12+ (`requires-python = ">=3.12.*"`).
- **Framework:** Litestar.
- **Formatting:** 4-space indentation, double quotes, ruff `line-length = 100`.
  Lint rules `E,F,B,UP,I,PLC0415`; isort `force-single-line`. (plan.md §6 says
  119, matching the sibling app; this file wins and `pyproject.toml` uses 100.)
  `ruff format` reformats Python code blocks **inside Markdown**, which would
  rewrite the snippets in `plan.md` and this file — `extend-exclude = ["*.md"]`
  prevents that. Do not remove it.
- **Typing:** mypy `strict = true`, plus `follow_untyped_imports = true` — the
  spec package ships full annotations but no `py.typed` marker, so without it
  every import from it degrades to `Any`.
- **Wire types are attrs + cattrs, not pydantic.** All emitted timestamps are
  timezone-aware UTC, serialized as ISO 8601.

## Project Structure

```
src/garmin_health/
  routes/
    dash.py (contains dashboarding logic).
tests/
```

Dependency direction is strictly
`routes -> service -> registry -> garmin/* -> garmindb`, with `timezones.py`
imported only by `garmin/*`.

## Critical Guardrails & Gotchas

**General**
- ALWAYS IMPLEMENT UNIT TESTS BEFORE BUSINESS LOGIC (test-driven development).