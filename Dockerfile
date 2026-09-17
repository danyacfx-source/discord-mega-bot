FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg — обязателен для воспроизведения музыки (yt-dlp)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД, токены и логи должны жить в volume (см. docker-compose.yml / хост)
VOLUME ["/app/data", "/app/logs"]

EXPOSE 17890

CMD ["python", "main.py"]