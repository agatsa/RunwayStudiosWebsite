#!/bin/bash
# infra/scheduler_jobs.sh
# Create Cloud Scheduler jobs for agent_swarm
# Usage: AGENT_SWARM_URL=https://agent-swarm-xxx.run.app bash infra/scheduler_jobs.sh

set -e

PROJECT="wa-ai-agency"
REGION="asia-south1"
BASE_URL="${AGENT_SWARM_URL}"
CRON_TOKEN_VALUE="${CRON_TOKEN:-}"

if [ -z "$BASE_URL" ]; then
  echo "❌ Set AGENT_SWARM_URL before running this script"
  exit 1
fi

echo "Creating Cloud Scheduler jobs..."

# Hourly run (every hour at :05)
gcloud scheduler jobs create http agent-swarm-hourly \
  --project "${PROJECT}" \
  --location "${REGION}" \
  --schedule "5 * * * *" \
  --uri "${BASE_URL}/cron/hourly" \
  --http-method POST \
  --headers "X-Cron-Token=${CRON_TOKEN_VALUE},Content-Type=application/json" \
  --message-body "{}" \
  --time-zone "Asia/Kolkata" \
  --attempt-deadline 300s \
  || gcloud scheduler jobs update http agent-swarm-hourly \
       --project "${PROJECT}" \
       --location "${REGION}" \
       --schedule "5 * * * *" \
       --uri "${BASE_URL}/cron/hourly" \
       --http-method POST \
       --headers "X-Cron-Token=${CRON_TOKEN_VALUE},Content-Type=application/json" \
       --message-body "{}" \
       --time-zone "Asia/Kolkata"

echo "✅ Hourly job: agent-swarm-hourly"

# Weekly creative director (every Monday at 9:00 AM IST)
gcloud scheduler jobs create http agent-swarm-weekly \
  --project "${PROJECT}" \
  --location "${REGION}" \
  --schedule "0 9 * * 1" \
  --uri "${BASE_URL}/cron/weekly" \
  --http-method POST \
  --headers "X-Cron-Token=${CRON_TOKEN_VALUE},Content-Type=application/json" \
  --message-body "{}" \
  --time-zone "Asia/Kolkata" \
  --attempt-deadline 300s \
  || gcloud scheduler jobs update http agent-swarm-weekly \
       --project "${PROJECT}" \
       --location "${REGION}" \
       --schedule "0 9 * * 1" \
       --uri "${BASE_URL}/cron/weekly" \
       --http-method POST \
       --headers "X-Cron-Token=${CRON_TOKEN_VALUE},Content-Type=application/json" \
       --message-body "{}" \
       --time-zone "Asia/Kolkata"

echo "✅ Weekly job: agent-swarm-weekly"
echo ""
echo "All jobs created. Check: gcloud scheduler jobs list --project ${PROJECT} --location ${REGION}"
