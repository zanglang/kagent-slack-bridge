FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --frozen 2>/dev/null || uv sync --no-dev --no-install-project

FROM python:3.12-slim

# Fixed numeric UID/GID: Kubernetes' runAsNonRoot check can't verify a named
# USER is non-root without inspecting /etc/passwd, and refuses to start the
# container ("image has non-numeric user") unless runAsUser is also set
# numerically in the pod spec — so pin one here and match it there.
RUN groupadd -r -g 10001 bridge && useradd -r -u 10001 -g bridge -s /usr/sbin/nologin bridge
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY bridge.py ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

USER 10001:10001
ENTRYPOINT ["python", "bridge.py"]
