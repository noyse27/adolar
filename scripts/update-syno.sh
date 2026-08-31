#!/usr/bin/env sh
set -eu

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-musicapp}"
SERVICE_NAME="${ADOLAR_SERVICE_NAME:-adolar}"
HEALTH_URL="${ADOLAR_HEALTH_URL:-http://localhost:15002/health}"

cd "$(dirname "$0")/.."

echo "Adolar update"
echo "Project: ${PROJECT_NAME}"
echo "Service: ${SERVICE_NAME}"

if docker inspect "${SERVICE_NAME}" >/dev/null 2>&1; then
  data_mount="$(docker inspect "${SERVICE_NAME}" --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Source }}{{ end }}{{ end }}')"
  echo "Current /data mount: ${data_mount}"
  case "${data_mount}" in
    *"${PROJECT_NAME}_adolar-data"*)
      ;;
    *)
      echo "ERROR: /data is not mounted from the expected ${PROJECT_NAME}_adolar-data volume." >&2
      echo "Refusing to continue so an accidental project-name change cannot start an empty database." >&2
      exit 1
      ;;
  esac
fi

echo "Pulling latest code..."
git pull --ff-only

echo "Rebuilding and restarting container..."
docker compose -p "${PROJECT_NAME}" up -d --build "${SERVICE_NAME}"

echo "Waiting for healthcheck..."
attempt=1
while [ "${attempt}" -le 20 ]; do
  if command -v curl >/dev/null 2>&1 && curl -fsS "${HEALTH_URL}" >/dev/null; then
    echo "Adolar is healthy: ${HEALTH_URL}"
    docker compose -p "${PROJECT_NAME}" ps "${SERVICE_NAME}"
    exit 0
  fi
  sleep 3
  attempt=$((attempt + 1))
done

echo "ERROR: Healthcheck did not become ready: ${HEALTH_URL}" >&2
docker compose -p "${PROJECT_NAME}" ps "${SERVICE_NAME}" >&2
exit 1
