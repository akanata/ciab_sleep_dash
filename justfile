default: test

# Install dependencies into .venv (Python 3.12).
setup:
    uv sync

# Run the app locally on http://localhost:8080 (auto-reloads on change).
run:
    uv run hypercorn sleep_dash.app:app --bind 0.0.0.0:8080 --reload

# Run the test suite.
test:
    uv run pytest -x

# Lint, format, and typecheck.
check:
    uv run ruff check --fix .
    uv run ruff format .
    uv run mypy

# Build the container image.
build:
    docker build -t sleep-dash .
