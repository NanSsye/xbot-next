# syntax=docker/dockerfile:1.7

FROM debian:bookworm-slim AS sqlite_build
ARG SQLITE_AUTOCONF_VERSION=3530400
ARG SQLITE_SHA256=0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c
ARG APT_MIRROR=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
RUN if [ -n "$APT_MIRROR" ]; then \
        bootstrap_mirror="$APT_MIRROR"; \
        case "$bootstrap_mirror" in https://*) bootstrap_mirror="http://${bootstrap_mirror#https://}" ;; esac; \
        sed -i "s|http://deb.debian.org/debian|$bootstrap_mirror|g; s|http://deb.debian.org/debian-security|$bootstrap_mirror-security|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -n "$HTTP_PROXY" ]; then \
        echo "Acquire::http::Proxy \"$HTTP_PROXY\";" > /etc/apt/apt.conf.d/99proxy; \
        echo "Acquire::https::Proxy \"$HTTPS_PROXY\";" >> /etc/apt/apt.conf.d/99proxy; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && (curl -fsSL --retry 1 --retry-all-errors --connect-timeout 15 --max-time 60 \
        -o /tmp/sqlite.tar.gz \
        "https://sqlite.org/2026/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz" \
      || curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 120 \
        -o /tmp/sqlite.tar.gz \
        "https://sources.buildroot.net/sqlite/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}.tar.gz") \
    && printf '%s  %s\n' "$SQLITE_SHA256" /tmp/sqlite.tar.gz | sha256sum -c - \
    && tar -xzf /tmp/sqlite.tar.gz -C /tmp \
    && cd "/tmp/sqlite-autoconf-${SQLITE_AUTOCONF_VERSION}" \
    && CFLAGS="-O2 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_UNLOCK_NOTIFY -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_THREADSAFE=1" \
        ./configure --prefix=/opt/sqlite-fixed --disable-static \
    && make -j"$(nproc)" \
    && make install

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

COPY --from=sqlite_build /opt/sqlite-fixed/lib/libsqlite3.so.3.53.4 /usr/local/lib/
RUN ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so.0 \
    && ln -sf libsqlite3.so.3.53.4 /usr/local/lib/libsqlite3.so \
    && printf '/usr/local/lib\n' > /etc/ld.so.conf.d/000-sqlite-fixed.conf \
    && ldconfig \
    && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version; db=sqlite3.connect(':memory:'); db.execute('CREATE VIRTUAL TABLE docs USING fts5(content)'); db.close()"

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
    && python -m pip install --no-build-isolation -i "$PIP_INDEX_URL" -e ./vendor/hermes -e ".[agent]" \
    && if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then python -m pip install --no-build-isolation -i "$PIP_INDEX_URL" -e ".[browser]" && python -m playwright install --with-deps chromium; fi \
    && cd /app/ui \
    && npm config set registry "$NPM_REGISTRY" \
    && npm ci \
    && npm run build \
    && mkdir -p /app/data /app/logs /app/workspace

EXPOSE 8548

ENTRYPOINT ["xbot-docker-entrypoint"]
CMD ["xbot", "run"]
