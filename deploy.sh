#!/bin/bash
# Run this ON the production server (172.16.37.18) as jtlacs
DEPLOY_DIR=~/olt-provisioning-api
cd $DEPLOY_DIR

# Copy updated files (already transferred via scp/sftp)
echo "[1/3] Restarting API container..."
docker compose restart api

echo "[2/3] Waiting for startup..."
sleep 5

echo "[3/3] Health check..."
curl -s http://localhost:8000/health && echo " — API OK"
echo ""
echo "Portal URL: http://172.16.37.18:8000/portal"
