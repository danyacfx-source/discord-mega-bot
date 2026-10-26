# Build the Vite/Preact web panel from source for every Docker deployment.
# The repository may contain older checked-in dist files; never serve those in a fresh image.
FROM node:22-alpine AS panel-builder
WORKDIR /frontend/panel-ui
COPY panel-ui/package.json panel-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY panel-ui/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg и libopus — обязательны для музыки и голосовых каналов (py-nacl, discordsrv)
# curl + ca-certificates — для загрузки sing-box
# postgresql-client — pg_dump для периодических backup-ов PostgreSQL
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 libopus-dev curl ca-certificates gosu postgresql-client fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# sing-box — опциональный прокси только для Gemini (если хост в EEA/NL, где API недоступен).
# Запускается entrypoint'ом при заданном SINGBOX_CONFIG_B64 (см. .env.example).
ARG SINGBOX_VERSION=1.14.1
# BuildKit supplies TARGETARCH for the VPS architecture; old builds always
# fetched amd64 and failed with "exec format error" on ARM64 servers.
ARG TARGETARCH
RUN set -eu; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in amd64|arm64) ;; *) echo "Unsupported sing-box architecture: $arch" >&2; exit 1 ;; esac; \
    archive="sing-box-${SINGBOX_VERSION}-linux-${arch}-musl"; \
    curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/${archive}.tar.gz" -o /tmp/sb.tgz; \
    curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-checksums.txt" -o /tmp/sb.sum; \
    grep " ${archive}\.tar\.gz\$" /tmp/sb.sum | sha256sum -c -; \
    tar -xzf /tmp/sb.tgz -C /tmp; \
    install -m 0755 "/tmp/${archive}/sing-box" /usr/local/bin/sing-box; \
    rm -rf /tmp/sb.tgz /tmp/sb.sum "/tmp/${archive}"; \
    sing-box version

WORKDIR /app

RUN addgroup --system bot \
    && adduser --system --ingroup bot --home /app --no-create-home bot

# requirements.lock — пины + sha256: pip отклонит любой пакет, чей хэш не
# совпал с локом. Пересборка лока после правки requirements.txt:
#   python scripts/lock_requirements.py
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .

# Replace the tracked legacy bundle with the just-built Radio Silence UI.
RUN rm -rf /app/app/core/webpanel/dist
COPY --from=panel-builder /frontend/app/core/webpanel/dist /app/app/core/webpanel/dist

RUN sed -i 's/\r$//' /app/scripts/docker-entrypoint.sh \
    && chmod +x /app/scripts/docker-entrypoint.sh \
    && mkdir -p /app/data /app/logs \
    && chown -R bot:bot /app

# БД, токены и логи должны жить в volume (см. docker-compose.yml / хост)
VOLUME ["/app/data", "/app/logs"]

EXPOSE 3000

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["python", "main.py"]