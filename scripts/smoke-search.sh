#!/usr/bin/env bash
#
# Verify SearXNG actually returns web search results.
#
# This is the check that would have caught the 2026-09-23 outage immediately:
# Open WebUI's native search_web tool was handing the model an empty list while
# everything looked healthy, because SearXNG answers HTTP 200 with
# {"results": []} when every upstream engine blocks it. The status code is not
# the signal -- the result count and unresponsive_engines are.
set -euo pipefail

query="${1:-stockholm weather forecast}"
namespace="${SEARXNG_NAMESPACE:-ai-workloads}"

ip=$(kubectl get svc searxng -n "$namespace" -o jsonpath='{.spec.clusterIP}')
if [ -z "$ip" ]; then
    echo "ERROR: could not resolve the searxng Service in namespace $namespace" >&2
    exit 1
fi

response=$(mktemp)
trap 'rm -f "$response"' EXIT

echo "querying searxng at $ip for: $query"
curl -sf --max-time 30 --get \
    --data-urlencode "q=$query" \
    --data-urlencode "format=json" \
    "http://$ip:8080/search" \
    -o "$response"

# The report runs from a file rather than a pipe: a heredoc-supplied script
# already occupies python's stdin.
RESPONSE_FILE="$response" python3 - <<'PY'
import json
import os
import sys

with open(os.environ["RESPONSE_FILE"]) as fh:
    d = json.load(fh)

results = d.get("results", [])
blocked = d.get("unresponsive_engines") or []
working = sorted({e for r in results for e in (r.get("engines") or [r.get("engine")]) if e})

print(f"results:  {len(results)}")
print(f"working:  {working}")
print(f"blocked:  {[(name, reason) for name, reason in blocked]}")
for r in results[:3]:
    print(f"  * {(r.get('title') or '')[:70]}")

if not results:
    print(
        "\nFAIL: zero results -- every engine listed above is blocking us.\n"
        "      Find engines that still work, then enable them in\n"
        "      helm/charts/searxng/values.yaml. To test a single engine:\n"
        "        curl -s '<svc-ip>:8080/search?q=test&format=json&engines=bing'",
        file=sys.stderr,
    )
    sys.exit(1)

print("\nOK")
PY
