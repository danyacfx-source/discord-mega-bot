#!/usr/bin/env bash
# Read-only diagnostic for the bot Docker Compose service on a VPS.
# Run from the repository root with docker-compose.yml present.
# Intentionally does NOT print .env, docker inspect Config.Env or application logs:
# they can contain tokens and passwords. Does not restart any containers.
set -u

if ! command -v docker >/dev/null 2>&1; then
  printf '[FAIL] Docker CLI is not installed\n' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '[FAIL] Docker Compose plugin is unavailable\n' >&2
  exit 1
fi
if [[ ! -f docker-compose.yml && ! -f compose.yaml && ! -f compose.yml && ! -f docker-compose.yaml ]]; then
  printf '[FAIL] Run from the bot Compose project directory\n' >&2
  exit 1
fi

printf '=== DENDICH / RADIO SILENCE | VPS Docker startup diagnostics ===\n'
printf 'Date (UTC): '
date -u '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true
printf 'Host architecture: '
uname -m 2>/dev/null || true
printf 'Docker: '
docker version --format '{{.Server.Version}}' 2>/dev/null || printf 'daemon unavailable\n'
printf 'Compose: '
docker compose version --short 2>/dev/null || true
printf '\n[1] Compose syntax and required variables\n'
if docker compose --profile postgres config --quiet >/dev/null; then
  printf '[OK] Compose configuration is valid\n'
else
  printf '[FAIL] Compose configuration failed: see error above\n'
  exit 1
fi

printf '\n[2] Project services (only this Compose project)\n'
docker compose --profile postgres ps -a || true

printf '\n[3] Bot container state\n'
cid=$(docker compose --profile postgres ps -a -q bot 2>/dev/null)
if [[ -z "$cid" ]]; then
  printf '[WARN] No bot container found in this Compose project.\n'
  printf 'This is expected when the deployment failed before container creation.\n'
else
  docker inspect --format 'Name={{.Name}}
Status={{.State.Status}}
ExitCode={{.State.ExitCode}}
OOMKilled={{.State.OOMKilled}}
DockerError={{.State.Error}}
RestartCount={{.RestartCount}}
StartedAt={{.State.StartedAt}}
FinishedAt={{.State.FinishedAt}}
Health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$cid" || true
  printf '\n[4] Image ID of the bot container (no secrets)\n'
  docker inspect --format '{{.Image}}' "$cid" || true
fi

printf '\n[5] PostgreSQL container state (no credentials)\n'
pgid=$(docker compose --profile postgres ps -a -q postgres 2>/dev/null)
if [[ -n "$pgid" ]]; then
  docker inspect --format 'Status={{.State.Status}}; Health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}; RestartCount={{.RestartCount}}' "$pgid" || true
else
  printf '[INFO] No local PostgreSQL Compose container; external database may be configured.\n'
fi

printf '\n[6] Disk space and memory (summary)\n'
df -h . 2>/dev/null | tail -n 1 || true
if command -v free >/dev/null 2>&1; then
  free -h | head -n 2 || true
fi

printf '\nNo environment values, secrets or application logs were collected.\n'
printf 'If logs are needed, review them privately first:\n'
printf '  docker compose --profile postgres logs --no-color --tail=80 bot\n'
