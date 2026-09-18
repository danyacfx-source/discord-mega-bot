#!/usr/bin/env sh
# Точка входа контейнера.
# Если задан SINGBOX_CONFIG_B64 (base64 от sing-box config.json) — поднимает
# локальный прокси 127.0.0.1:2080 и запускает бота. Иначе просто запускает бота.
set -eu

if [ -n "${SINGBOX_CONFIG_B64:-}" ]; then
    mkdir -p /run/singbox
    printf '%s' "$SINGBOX_CONFIG_B64" | base64 -d > /run/singbox/config.json
    echo "[entrypoint] запускаю sing-box (/run/singbox/config.json)"
    /usr/local/bin/sing-box run -c /run/singbox/config.json &
    sleep 2
else
    echo "[entrypoint] SINGBOX_CONFIG_B64 не задан — старт без прокси"
fi

exec "$@"
