#!/bin/sh
# Disks are often mounted owned by root (Render does this). Fix ownership, then run the app as a normal user.
set -e
if [ "$(id -u)" = "0" ]; then
  for d in /data "${COACHBOT_INSTITUTES_DIR:-}" /app/institutes; do
    if [ -n "$d" ] && [ -d "$d" ]; then chown -R 1000:1000 "$d" 2>/dev/null || true; fi
  done
  exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
fi
exec "$@"
