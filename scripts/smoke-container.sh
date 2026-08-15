#!/usr/bin/env bash
set -euo pipefail

container_name="media-finder-ci"
volume_name="media-finder-ci-data"
base_url="http://127.0.0.1:8000"

cleanup() {
  docker logs "$container_name" || true
  docker rm --force "$container_name" || true
  docker volume rm "$volume_name" || true
}
trap cleanup EXIT

assert_response() {
  local label="$1"
  local url="$2"
  local expected_status="$3"
  local expected_fragment="$4"
  shift 4
  local body
  body="$(mktemp)"
  local actual_status
  actual_status="$(curl --silent --show-error --output "$body" --write-out '%{http_code}' "$@" "$url")"
  if [[ "$actual_status" != "$expected_status" ]]; then
    echo "$label returned HTTP $actual_status instead of $expected_status" >&2
    cat "$body" >&2
    rm -f "$body"
    return 1
  fi
  if ! grep --fixed-strings --quiet -- "$expected_fragment" "$body"; then
    echo "$label response did not contain the expected body fragment" >&2
    cat "$body" >&2
    rm -f "$body"
    return 1
  fi
  rm -f "$body"
}

docker run --detach --name "$container_name" \
  --publish 127.0.0.1:8000:8000 \
  --volume "$volume_name:/data" \
  --env MEDIA_FINDER_UI_SECRET=ci-session-secret-with-sufficient-length \
  --env MEDIA_FINDER_INTEGRATION_TOKEN=ci-integration-token \
  --env MEDIA_FINDER_SECURE_COOKIE=false \
  media-finder:ci

for attempt in {1..30}; do
  if curl --fail --silent --output /dev/null "$base_url/health/ready"; then
    break
  fi
  if [[ "$attempt" == "30" ]]; then
    echo "Production image did not become ready" >&2
    exit 1
  fi
  sleep 1
done

assert_response "UI root" "$base_url/" "200" "<!doctype html>"
assert_response "Browser control session" "$base_url/api/control/v1/session" "200" '"csrf_token"'
assert_response "Liveness" "$base_url/health/live" "200" '{"status":"live"}'
assert_response "Readiness" "$base_url/health/ready" "200" '{"status":"ready"}'
assert_response \
  "Unauthorized processor API" \
  "$base_url/api/v1/media-items/missing/metadata" \
  "401" \
  '"code":"authentication_required"'
assert_response \
  "Authorized processor API" \
  "$base_url/api/v1/media-items/missing/metadata" \
  "404" \
  '"code":"media_item_not_found"' \
  --header "Authorization: Bearer ci-integration-token"

test "$(docker exec "$container_name" id -u)" = "10001"
test "$(docker exec "$container_name" id -g)" = "10001"
docker exec "$container_name" python -c \
  "import media_finder, media_finder_builtin_ui, media_finder_control"

docker rm --force "$container_name"
docker run --detach --name "$container_name" \
  --publish 127.0.0.1:8000:8000 \
  --volume "$volume_name:/data" \
  --env MEDIA_FINDER_UI_SECRET=ci-session-secret-with-sufficient-length \
  --env MEDIA_FINDER_INTEGRATION_TOKEN=ci-integration-token \
  --env MEDIA_FINDER_SECURE_COOKIE=false \
  --env MEDIA_FINDER_UI_MODE=disabled \
  media-finder:ci

for attempt in {1..30}; do
  if curl --fail --silent --output /dev/null "$base_url/health/ready"; then
    break
  fi
  if [[ "$attempt" == "30" ]]; then
    echo "Production image in disabled UI mode did not become ready" >&2
    exit 1
  fi
  sleep 1
done

assert_response "Disabled UI root" "$base_url/" "404" '"code":"not_found"'
assert_response "Disabled control session" "$base_url/api/control/v1/session" "200" '"csrf_token"'
assert_response "Disabled liveness" "$base_url/health/live" "200" '{"status":"live"}'
assert_response \
  "Disabled processor API" \
  "$base_url/api/v1/media-items/missing/metadata" \
  "401" \
  '"code":"authentication_required"'
