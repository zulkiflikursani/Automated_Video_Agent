#!/usr/bin/env bash
# Jalankan Automated Video Agent di local.
#
#   scripts/run_local.sh          -> API :8000 + dashboard :3000 + agent scheduler (berjalan terus)
#   scripts/run_local.sh --once   -> satu siklus pipeline saja, lalu berhenti
#
# Tekan Ctrl+C untuk menghentikan semua service.
set -e
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "❌ .venv tidak ada. Jalankan dulu: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -d dashboard/node_modules ]; then
  echo "📦 Installing dashboard deps..."
  (cd dashboard && npm install --no-audit --no-fund)
fi

mkdir -p logs

if [ "$1" = "--once" ]; then
  echo "▶ Menjalankan satu siklus pipeline (scan -> process -> publish -> GC)..."
  .venv/bin/python -m backend.main --run-once
  exit 0
fi

cleanup() {
  echo ""
  echo "⏹  Menghentikan semua service..."
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null
  [ -n "$DASH_PID" ] && kill "$DASH_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

echo "🚀 Memulai semua service:"
echo "   • Agent scheduler  : scan tiap ${SCAN_INTERVAL_MINUTES:-360} menit, publish tick tiap 15 menit"
echo "   • API backend      : http://localhost:8000  (docs: /docs)"
echo "   • Dashboard        : http://localhost:3000"

# 1) API backend
.venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port 8000 >> logs/api.log 2>&1 &
API_PID=$!

# 2) Dashboard
(cd dashboard && npx next dev -p 3000) >> ../logs/dashboard.log 2>&1 &
DASH_PID=$!

# 3) Agent scheduler (foreground - Ctrl+C menghentikan semuanya)
sleep 3
.venv/bin/python -m backend.main
