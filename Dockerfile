FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg и libopus — обязательны для музыки и голосовых каналов (py-nacl, discordsrv)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД, токены и логи должны жить в volume (см. docker-compose.yml / хост)
VOLUME ["/app/data", "/app/logs"]

EXPOSE 17890

# Диагностика при старте: печатает, что реально попало в образ
CMD ["sh", "-c", "echo '--- /app contents ---'; ls -la /app; echo '--- app/ contents ---'; ls -la /app/app; echo '--- app/db ---'; if [ -d /app/app/db ]; then ls -la /app/app/db; echo 'app/db OK'; else echo 'app/db ABSENT'; fi; exec python main.py"]