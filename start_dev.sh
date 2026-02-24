#!/bin/bash
# Starts FastAPI (port 8081) + Next.js dashboard (port 3000) for local dev.
# Run from the project root: bash start_dev.sh

set -e

PROJECT_ROOT="/c/Users/rahul/Downloads/wa-agency-bot-extracted/wa-agency-bot"
cd "$PROJECT_ROOT"

DB_URL="postgresql://postgres:job314@34.93.56.252:5432/wa_agency"

echo "==> Killing any old servers on 8081 / 3000..."
PID_8081=$(netstat -ano 2>/dev/null | grep ":8081 " | grep LISTEN | awk '{print $5}' | head -1)
PID_3000=$(netstat -ano 2>/dev/null | grep ":3000 " | grep LISTEN | awk '{print $5}' | head -1)
[ -n "$PID_8081" ] && cmd //c "taskkill /F /PID $PID_8081" 2>/dev/null && echo "   Killed $PID_8081 (FastAPI)" || true
[ -n "$PID_3000" ] && cmd //c "taskkill /F /PID $PID_3000" 2>/dev/null && echo "   Killed $PID_3000 (Next.js)" || true
sleep 2

echo ""
echo "==> Starting FastAPI on :8081..."
env DATABASE_URL="$DB_URL" CRON_TOKEN="dev" \
  /c/Python314/Scripts/uvicorn services.agent_swarm.app:app \
  --port 8081 --host 127.0.0.1 > /tmp/fastapi.log 2>&1 &
FPID=$!
echo "   PID: $FPID  (logs: /tmp/fastapi.log)"

echo "==> Starting Next.js dashboard on :3000..."
cd "$PROJECT_ROOT/dashboard"
npm run dev > /tmp/nextjs.log 2>&1 &
NPID=$!
echo "   PID: $NPID  (logs: /tmp/nextjs.log)"

echo ""
echo "==> Waiting for servers to boot..."
sleep 10

echo ""
echo "==> Checking FastAPI..."
curl -sf http://localhost:8081/health && echo " OK" || echo " FAILED — check /tmp/fastapi.log"

echo "==> Checking Next.js..."
STATUS=$(curl -so /dev/null -w "%{http_code}" http://localhost:3000/)
echo "   HTTP $STATUS (404 = normal — Clerk blocks curl)"

echo ""
echo "====================================================="
echo " Dashboard ready at  http://localhost:3000"
echo " FastAPI ready at    http://localhost:8081/health"
echo "====================================================="
