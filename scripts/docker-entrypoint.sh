#!/usr/bin/env sh
# Точка входа контейнера.
# Если задан SINGBOX_CONFIG_B64 (base64 от sing-box config.json) — поднимает
# локальный прокси 127.0.0.1:2080 и запускает бота. Иначе просто запускает бота.
set -eu

if [ "$(id -u)" -eq 0 ]; then
    # Bind-mounted ./data and ./logs are commonly created by root on the host.
    # Fix their ownership once, then run the actual bot as an unprivileged user.
    chown -R bot:bot /app/data /app/logs 2>/dev/null || true
    exec gosu bot "$0" "$@"
fi

umask 077

if [ -n "${SINGBOX_CONFIG_B64:-}" ]; then
    mkdir -p /tmp/singbox
    printf '%s' "$SINGBOX_CONFIG_B64" | base64 -d > /tmp/singbox/config.json
    echo "[entrypoint] запускаю sing-box (/tmp/singbox/config.json)"
    /usr/local/bin/sing-box run -c /tmp/singbox/config.json &
    sleep 2
else
    echo "[entrypoint] SINGBOX_CONFIG_B64 не задан — старт без прокси"
fi

exec "$@"
