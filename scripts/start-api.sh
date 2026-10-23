#!/bin/sh
set -eu
if [ ! -d "$CHROMA_PATH" ]; then
    mkdir -p "$(dirname "$CHROMA_PATH")"
    cp -R /opt/chroma-template "$CHROMA_PATH"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
