#!/usr/bin/env bash
# Scripted walkthrough of the demo against the running stack (`make up` first). Uses only curl and python3.
# Everything is simulated: fictional providers, no real bookings.
set -euo pipefail
API=${API:-http://localhost:8000}
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
chat() { python3 -c "
import json,sys
print(json.dumps({'threadId':'demo','runId':'r','messages':[{'id':'1','role':'user','content':sys.argv[1]}],'tools':[],'context':[],'state':{},'forwardedProps':{}}))" "$1" \
  | curl -sN "$API/api/agui" -H 'content-type: application/json' -d @-; }
wait_state() { for _ in $(seq 60); do s=$(curl -s "$API/api/jobs/$1/stream" -m 1 | grep -o '"state": "[a-z]*"' | tail -1 | cut -d'"' -f4 || true); case "$s" in completed|failed) echo "$s"; return;; esac; sleep 0.5; done; }
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "1. An incomplete request: the assistant asks, it does not invent a location or dates"
chat "I need a physio soon" | grep -o '"delta":"[^"]*"' | cut -d'"' -f4 | tr -d '\n'; echo

step "2. A complete request: the chat starts the research as a background job (a worker runs it)"
chat "Back pain, evening appointments in Haidhausen next week" > /tmp/demo-chat.out
RESEARCH=$(grep -o '"job_id\\*":\\*"[a-f0-9]*' /tmp/demo-chat.out | head -1 | grep -o '[a-f0-9]\{32\}')
echo "research job: $RESEARCH"; echo "state: $(wait_state "$RESEARCH")"
curl -s "$API/api/jobs/$RESEARCH" > /tmp/demo-job.json
json "'criteria: ' + str(d['criteria'])" < /tmp/demo-job.json
json "'\n'.join('  ' + p['message'] for p in d['progress'])" < /tmp/demo-job.json

step "3. The shortlist: providers and slots, as the provider service returned them"
json "'\n'.join(f\"  {i['rank']}. {i['provider']['name']} ({i['provider']['neighbourhood']}): {' '.join(i['reasons'])}\n     slots: {', '.join(s['starts_at'][:16] for s in i['slots'])}\" for i in d['result']['shortlist'])" < /tmp/demo-job.json
PROVIDER=$(json "d['result']['shortlist'][0]['provider']['id']" < /tmp/demo-job.json)
SLOT=$(json "d['result']['shortlist'][0]['slots'][0]['id']" < /tmp/demo-job.json)

prepare() { curl -s "$API/api/preparations" -H 'content-type: application/json' \
  -d "{\"job_id\":\"$RESEARCH\",\"provider_id\":\"$PROVIDER\",\"slot_id\":\"$SLOT\",\"simulate_failure\":$1}" | json "d['job_id']"; }
show() { curl -s "$API/api/preparations/$1" | json "d['state'] + '  ' + str([p['message'] for p in d['progress']])"; }

step "4. Failure: with the failure parameter on, 'prepare booking' fails after its first agent"
P1=$(prepare true); echo "prepare job: $P1"; echo "state: $(wait_state "$P1")"; show "$P1"

step "5. Retry is a RESUME: the finished first step is reused, only the second agent runs"
P2=$(curl -s -X POST "$API/api/preparations/$P1/retry" -H 'content-type: application/json' -d '{"simulate_failure":false}' | json "d['job_id']"); echo "resumed job: $P2"; echo "state: $(wait_state "$P2")"; show "$P2"
curl -s "$API/api/preparations/$P2" | json "'confirmation: ' + d['result']['confirmation']"

step "6. Booking needs an explicit confirmation; the same confirmation twice makes ONE booking"
KEY=demo-$RANDOM
for _ in 1 2; do
  curl -s "$API/api/bookings" -H 'content-type: application/json' \
    -d "{\"job_id\":\"$RESEARCH\",\"provider_id\":\"$PROVIDER\",\"slot_id\":\"$SLOT\",\"idempotency_key\":\"$KEY\"}" \
    | json "f\"  booking {d['id']} ({d['status']}, simulated={d['simulated']})\""
done

step "7. Everything survives a restart"
docker compose restart api worker >/dev/null 2>&1; sleep 6
curl -s "$API/api/jobs/$RESEARCH" | json "'  research ' + d['state'] + ', booking ' + d['booking']['id']"

step "8. Traces: one trace links the API request, the chat tool call and the worker's job"
echo "  open http://localhost:16686 and search service 'concierge-api'   (make traces)"
