#!/bin/bash
# Simple script to test the webhook endpoints

HOST="${1:-localhost:5099}"

echo "Testing unmonitarr webhooks on $HOST"
echo "=========================================="
echo ""

# Test health endpoint
echo "1. Testing health endpoint..."
curl -s -X GET "http://$HOST/health" | python3 -m json.tool
echo ""
echo ""

# Test Sonarr webhook
echo "2. Testing Sonarr webhook trigger..."
curl -s -X POST "http://$HOST/trigger/sonarr" | python3 -m json.tool
echo ""
echo ""

# Test Radarr webhook
echo "3. Testing Radarr webhook trigger..."
curl -s -X POST "http://$HOST/trigger/radarr" | python3 -m json.tool
echo ""
echo ""

echo "=========================================="
echo "Done! Check the unmonitarr logs to see if jobs were processed."
echo ""
echo "Usage: $0 [host:port]"
echo "Example: $0 localhost:5099"
