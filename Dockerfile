FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# git: health-data-service is a git dependency (see pyproject.toml) and uv shells
#      out to a real git binary to fetch it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uv", "run", "--frozen", "--no-dev", "hypercorn", "sleep_dash.app:app", "--bind", "0.0.0.0:8080"]
