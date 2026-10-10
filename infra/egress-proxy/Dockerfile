FROM ghcr.io/astral-sh/uv:0.10.7 AS uv

FROM python:3.13-slim-bookworm AS runtime

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

COPY infra/egress-proxy/proxy_main.py /app/proxy_main.py

RUN useradd --create-home --uid 10003 appuser && chown -R appuser:appuser /app

ENV PATH="/app/.venv/bin:$PATH"

USER appuser
EXPOSE 8899

CMD ["python", "/app/proxy_main.py"]
