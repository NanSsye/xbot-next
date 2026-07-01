# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XBOT_CONFIG_FILE=/app/configs/xbot.toml \
    XBOT_LOAD_DOTENV=true

ARG INSTALL_PLAYWRIGHT=false
ARG APT_MIRROR=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=localhost,127.0.0.1
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g; s|http://deb.debian.org/debian-security|$APT_MIRROR-security|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -n "$HTTP_PROXY" ]; then \
        echo "Acquire::http::Proxy \"$HTTP_PROXY\";" > /etc/apt/apt.conf.d/99proxy; \
        echo "Acquire::https::Proxy \"$HTTPS_PROXY\";" >> /etc/apt/apt.conf.d/99proxy; \
    fi \
    && apt-get update \
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
    && python -m pip install --no-build-isolation -i "$PIP_INDEX_URL" -e . \
    && if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then python -m pip install --no-build-isolation -i "$PIP_INDEX_URL" -e ".[browser]" && python -m playwright install --with-deps chromium; fi \
    && cd /app/ui \
    && npm config set registry "$NPM_REGISTRY" \
    && npm ci \
    && npm run build \
    && mkdir -p /app/data /app/logs /app/workspace

EXPOSE 8548

ENTRYPOINT ["xbot-docker-entrypoint"]
CMD ["xbot", "run"]
