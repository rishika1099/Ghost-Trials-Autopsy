#!/usr/bin/env bash
# Check the deployed service: /health is 200, and one sample query answers within 300 s.
#   bash tests/test_deploy.sh https://ghost-trials-autopsy-xxxx.run.app
set -euo pipefail
URL="${1:-$(python3 -c 'import json; print(json.load(open("submission.json"))["deploy_url"])')}"
URL="${URL%/}"
echo "health: $URL/health"
curl -fsS --max-time 30 "$URL/health"; echo
QUERY="${QUERY:-Why was trial NCT02008682 stopped, were its results posted, and what did the sponsor tell investors?}"
echo "chat: $QUERY"
START=$(date +%s)
BODY=$(curl -fsS --max-time 300 -X POST "$URL/chat" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1]}))' "$QUERY")")
ELAPSED=$(( $(date +%s) - START ))
echo "$BODY" | python3 -c 'import json,sys; b=json.load(sys.stdin); assert set(b)=={"response","session_id","tool_calls"}; assert all("agent" in c for c in b["tool_calls"]); print(b["response"][:600]); print(len(b["tool_calls"]), "tool calls")'
echo "elapsed: ${ELAPSED}s"
[ "$ELAPSED" -le 300 ] || { echo "FAIL: over 300 s"; exit 1; }
echo "PASS"
