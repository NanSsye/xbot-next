#!/bin/sh
# Run on the Docker host with an existing local Xbot image. Fixtures only.
set -eu
: "${XBOT_TEST_IMAGE:?Specify a local Xbot image}"
root=$(mktemp -d)
name=xbot-update-rehearsal-$(basename "$root" | tr . -)
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || :; }
trap cleanup EXIT
mkdir "$root/app" "$root/next" "$root/state"
printf '%s\n' old > "$root/app/version"
printf '%s\n' next > "$root/next/version"
printf '%s\n' keep > "$root/state/data"
baseline=$(sha256sum "$root/app/version")
docker run --pull=never -d --name "$name" --network none --read-only \
    --mount "type=bind,src=$root/app,dst=/fixture,readonly" \
    --mount "type=bind,src=$root/state,dst=/fixture-state,readonly" \
    --entrypoint /bin/sh "$XBOT_TEST_IMAGE" -c 'exec sleep 300' >/dev/null
probe() { docker exec "$name" cat /fixture/version; }
test "$(probe)" = old
printf '%s\n' customized > "$root/app/version"
test "$baseline" != "$(sha256sum "$root/app/version")"
test "$(probe)" = customized
printf '%s\n' 'PASS: detected local modification; declined activation retains it'
docker stop -t 1 "$name" >/dev/null
mv "$root/app" "$root/previous"
mv "$root/next" "$root/app"
docker start "$name" >/dev/null
test "$(probe)" = next
printf '%s\n' 'PASS: Docker restart sees replacement bind directory'
mkdir "$root/bad"
printf '%s\n' invalid > "$root/bad/version"
docker stop -t 1 "$name" >/dev/null
mv "$root/app" "$root/good"
mv "$root/bad" "$root/app"
docker start "$name" >/dev/null
if test "$(probe)" != next; then
    docker stop -t 1 "$name" >/dev/null
    mv "$root/app" "$root/rejected"
    mv "$root/good" "$root/app"
    docker start "$name" >/dev/null
fi
test "$(probe)" = next
test "$(docker exec "$name" cat /fixture-state/data)" = keep
printf '%s\n' 'PASS: failed version probe rolled back; independent data unchanged'
