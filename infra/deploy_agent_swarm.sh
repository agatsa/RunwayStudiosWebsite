#!/bin/bash
# infra/deploy_agent_swarm.sh
# Deploy agent_swarm service to Cloud Run
# Usage: bash infra/deploy_agent_swarm.sh

set -e

PROJECT="wa-ai-agency"
REGION="asia-south1"
SERVICE="agent-swarm"
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}"

echo "🚀 Building and deploying ${SERVICE}..."

# Build from repo root (so services/ imports work)
gcloud builds submit \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --tag "${IMAGE}" \
  --dockerfile "services/agent_swarm/Dockerfile" \
  .

# Deploy to Cloud Run
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --image "${IMAGE}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --concurrency 5 \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest" \
  --set-secrets "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest" \
  --set-secrets "META_ADS_TOKEN=META_ADS_TOKEN:latest" \
  --set-secrets "WA_ACCESS_TOKEN=WA_ACCESS_TOKEN:latest" \
  --set-secrets "CRON_TOKEN=CRON_TOKEN:latest" \
  --set-env-vars "META_AD_ACCOUNT_ID=act_6a329a0b9d4788" \
  --set-env-vars "WA_PHONE_NUMBER_ID=${WA_PHONE_NUMBER_ID}" \
  --set-env-vars "WA_REPORT_NUMBER=918826283840" \
  --set-env-vars "META_API_VERSION=v21.0" \
  --set-env-vars "TARGET_ROAS=2.5" \
  --set-env-vars "MAX_CPA=500" \
  --set-env-vars "DAILY_SPEND_CAP=20000" \
  --set-env-vars "APPROVAL_THRESHOLD=10000" \
  --set-env-vars "LANDING_PAGE_URL=${LANDING_PAGE_URL:-}" \
  --set-env-vars "META_AD_TIMEZONE=Asia/Kolkata"

echo ""
echo "✅ ${SERVICE} deployed!"
echo ""
echo "Next: Set up Cloud Scheduler jobs:"
echo "  POST /cron/hourly  → every hour"
echo "  POST /cron/weekly  → every Monday 9am IST"
echo ""
echo "Also update main.py (wa-bot) AGENT_SWARM_URL env var to the service URL above."
