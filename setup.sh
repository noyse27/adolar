#!/bin/sh
# Usage: ./setup.sh [production|demo]   (default: production)
#
# Creates the env file for the chosen mode if it doesn't exist yet
# (SECRET_KEY generated with openssl rand -hex 32), then brings up the
# matching Docker Compose stack. Safe to re-run: an existing env file, or an
# already-set real SECRET_KEY in it, is never overwritten.
set -eu
cd "$(dirname "$0")"

mode="${1:-production}"
case "$mode" in
  production|demo) ;;
  *) echo "Usage: $0 [production|demo]"; exit 1 ;;
esac

# .env.example ships SECRET_KEY with this literal placeholder rather than
# empty, so both "empty" and "still the placeholder" count as unset below.
placeholder="change_me_to_a_long_random_hex_value"

if [ "$mode" = demo ]; then
  env_file=".env.demo"
  example_file=".env.demo.example"
  compose_file="docker-compose.demo.yml"
  project="adolar-demo"
  port_var="DEMO_HOST_PORT"
  default_port=15012
else
  env_file=".env"
  example_file=".env.example"
  compose_file="docker-compose.yml"
  project="adolar"
  port_var=""
  default_port=15002
fi

if [ ! -f "$env_file" ]; then
  cp "$example_file" "$env_file"
  echo "$env_file aus $example_file erstellt."
fi

current_secret="$(grep '^SECRET_KEY=' "$env_file" 2>/dev/null | tail -1 | cut -d= -f2-)"
if [ -z "$current_secret" ] || [ "$current_secret" = "$placeholder" ]; then
  secret="$(openssl rand -hex 32)"
  if grep -q '^SECRET_KEY=' "$env_file"; then
    sed "s#^SECRET_KEY=.*#SECRET_KEY=$secret#" "$env_file" > "$env_file.tmp" && mv "$env_file.tmp" "$env_file"
  else
    printf 'SECRET_KEY=%s\n' "$secret" >> "$env_file"
  fi
  echo "$env_file: SECRET_KEY zufällig erzeugt."
fi

docker compose --env-file "$env_file" -p "$project" -f "$compose_file" up --build -d

port="$default_port"
if [ -n "$port_var" ]; then
  configured_port="$(grep "^${port_var}=" "$env_file" 2>/dev/null | tail -1 | cut -d= -f2-)"
  port="${configured_port:-$default_port}"
fi
if [ "$mode" = demo ]; then
  echo "Demo: http://localhost:$port - Admin-/Hörer-Login siehe Banner in der App, Details in docs/demo.md"
else
  echo "Adolar: http://localhost:$port - Setup-Link steht in den Logs (docker compose logs adolar)"
fi
