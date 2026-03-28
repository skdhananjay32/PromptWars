#!/bin/bash
# ── Universal Intent Bridge — Cloud Run Deployment ────────────────
# Usage: ./deploy-nodocker.sh
# Single unified service: FastAPI serves both UI and API.
# No Node.js, no Docker required locally.

set -e
source .env 2>/dev/null || true

PROJECT_ID="${GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="bridge-app"

echo "======================================================"
echo "  Universal Intent Bridge — Cloud Run Deploy"
echo "  Project: ${PROJECT_ID} | Region: ${REGION}"
echo "======================================================"

echo ""
echo "▶ Deploying ${SERVICE} via Cloud Build..."
gcloud run deploy "${SERVICE}" \
  --source ./backend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "GEMINI_API_KEY=${GEMINI_API_KEY}" \
  --memory 1Gi \
  --port 8000

APP_URL=$(gcloud run services describe "${SERVICE}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format "value(status.url)")

echo ""
echo "======================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "   App URL: ${APP_URL}"
echo "======================================================"
