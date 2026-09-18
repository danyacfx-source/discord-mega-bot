FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg и libopus — обязательны для музыки и голосовых каналов (py-nacl, discordsrv)
# curl + ca-certificates — для загрузки sing-box
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# sing-box — опциональный прокси только для Gemini (если хост в EEA/NL, где API недоступен).
# Запускается entrypoint'ом при заданном SINGBOX_CONFIG_B64 (см. .env.example).
ARG SINGBOX_VERSION=1.14.1
RUN curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-amd64-musl.tar.gz" -o /tmp/sb.tgz \
    && tar -xzf /tmp/sb.tgz -C /tmp \
    && install -m 0755 "/tmp/sing-box-${SINGBOX_VERSION}-linux-amd64-musl/sing-box" /usr/local/bin/sing-box \
    && rm -rf /tmp/sb.tgz "/tmp/sing-box-${SINGBOX_VERSION}-linux-amd64-musl" \
    && sing-box version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' /app/scripts/docker-entrypoint.sh \
    && chmod +x /app/scripts/docker-entrypoint.sh

# БД, токены и логи должны жить в volume (см. docker-compose.yml / хост)
VOLUME ["/app/data", "/app/logs"]

EXPOSE 17890

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["python", "main.py"]