#!/usr/bin/env bash
# Back-compat alias → Cursor setup
exec bash "$(cd "$(dirname "$0")" && pwd)/setup-cursor-tradingview.sh" "$@"
