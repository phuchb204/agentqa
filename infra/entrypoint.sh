#!/bin/sh
set -e

if [ "$(id -u)" = "0" ] && [ -n "$AGENTQA_ARTIFACT_DIR" ]; then
    mkdir -p "$AGENTQA_ARTIFACT_DIR"
    chown -R appuser:appuser "$AGENTQA_ARTIFACT_DIR" 2>/dev/null || true
fi

if [ "$(id -u)" = "0" ]; then
    exec setpriv --reuid=appuser --regid=appuser --clear-groups "$@"
fi
exec "$@"
