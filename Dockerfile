FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --frozen 2>/dev/null || uv sync --no-dev --no-install-project

FROM python:3.12-slim

RUN groupadd -r bridge && useradd -r -g bridge -s /usr/sbin/nologin bridge
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY bridge.py ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

USER bridge:bridge
ENTRYPOINT ["python", "bridge.py"]
