# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XBOT_CONFIG_FILE=/app/configs/xbot.toml \
    XBOT_LOAD_DOTENV=true

ARG INSTALL_PLAYWRIGHT=true

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY configs ./configs
COPY migrations ./migrations
COPY plugins ./plugins
COPY scripts ./scripts
COPY skills ./skills
COPY src ./src
COPY vendor ./vendor
COPY ui ./ui
COPY docker/entrypoint.sh /usr/local/bin/xbot-docker-entrypoint

RUN chmod +x /usr/local/bin/xbot-docker-entrypoint \
    && python -m pip install --upgrade pip \
    && python -m pip install -e . \
    && if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then python -m playwright install --with-deps chromium; fi \
    && cd /app/ui \
    && npm ci \
    && npm run build \
    && mkdir -p /app/data /app/logs /app/workspace

EXPOSE 8548

ENTRYPOINT ["xbot-docker-entrypoint"]
CMD ["xbot", "run"]
