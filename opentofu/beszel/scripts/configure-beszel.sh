#!/usr/bin/env bash
# Configure Beszel alerts and notifications via PocketBase REST API.
#
# Required environment variables:
#   BESZEL_URL         - Beszel endpoint (e.g. https://beszel.homelab.local)
#   BESZEL_EMAIL       - Admin user email
#   BESZEL_PASSWORD    - Admin user password
#   WEBHOOK_URL        - Shoutrrr notification URL (e.g. discord://token@id)
#   CPU_THRESHOLD      - CPU alert threshold percentage
#   MEMORY_THRESHOLD   - Memory alert threshold percentage
#   DISK_THRESHOLD     - Disk alert threshold percentage

set -euo pipefail

CURL_OPTS=(-s -k --fail-with-body)

echo "Authenticating with Beszel at ${BESZEL_URL}..."
AUTH_RESPONSE=$(curl "${CURL_OPTS[@]}" \
  -X POST "${BESZEL_URL}/api/collections/users/auth-with-password" \
  -H "Content-Type: application/json" \
  -d "{\"identity\": \"${BESZEL_EMAIL}\", \"password\": \"${BESZEL_PASSWORD}\"}")

TOKEN=$(echo "${AUTH_RESPONSE}" | jq -r '.token')
USER_ID=$(echo "${AUTH_RESPONSE}" | jq -r '.record.id')

if [ -z "${TOKEN}" ] || [ "${TOKEN}" = "null" ]; then
  echo "ERROR: Authentication failed"
  echo "${AUTH_RESPONSE}"
  exit 1
fi
echo "Authenticated as user ${USER_ID}"

AUTH_HEADER="Authorization: ${TOKEN}"

# --- Configure notification webhook ---
if [ -n "${WEBHOOK_URL}" ]; then
  echo "Configuring notification webhook..."

  # Get current user settings
  SETTINGS_RESPONSE=$(curl "${CURL_OPTS[@]}" \
    -X GET "${BESZEL_URL}/api/collections/user_settings/records?filter=user='${USER_ID}'" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" || echo '{"totalItems":0}')

  SETTINGS_COUNT=$(echo "${SETTINGS_RESPONSE}" | jq -r '.totalItems // 0')

  SETTINGS_PAYLOAD=$(jq -n \
    --arg url "${WEBHOOK_URL}" \
    --arg user "${USER_ID}" \
    '{user: $user, settings: {notificationWebhooks: [$url]}}')

  if [ "${SETTINGS_COUNT}" -gt 0 ]; then
    SETTINGS_ID=$(echo "${SETTINGS_RESPONSE}" | jq -r '.items[0].id')
    echo "Updating existing user settings (${SETTINGS_ID})..."
    curl "${CURL_OPTS[@]}" \
      -X PATCH "${BESZEL_URL}/api/collections/user_settings/records/${SETTINGS_ID}" \
      -H "${AUTH_HEADER}" \
      -H "Content-Type: application/json" \
      -d "${SETTINGS_PAYLOAD}" > /dev/null
  else
    echo "Creating user settings..."
    curl "${CURL_OPTS[@]}" \
      -X POST "${BESZEL_URL}/api/collections/user_settings/records" \
      -H "${AUTH_HEADER}" \
      -H "Content-Type: application/json" \
      -d "${SETTINGS_PAYLOAD}" > /dev/null
  fi

  # Test notification
  echo "Testing notification..."
  curl "${CURL_OPTS[@]}" \
    -X POST "${BESZEL_URL}/api/beszel/test-notification" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${WEBHOOK_URL}\"}" > /dev/null || echo "WARNING: Test notification failed (endpoint may not exist in this version)"

  echo "Notification webhook configured"
fi

# --- Configure alert rules ---
echo "Fetching systems..."
SYSTEMS_RESPONSE=$(curl "${CURL_OPTS[@]}" \
  -X GET "${BESZEL_URL}/api/collections/systems/records?perPage=100" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json")

SYSTEM_COUNT=$(echo "${SYSTEMS_RESPONSE}" | jq -r '.totalItems')
echo "Found ${SYSTEM_COUNT} systems"

# Get existing alerts
ALERTS_RESPONSE=$(curl "${CURL_OPTS[@]}" \
  -X GET "${BESZEL_URL}/api/collections/alerts/records?perPage=500&filter=user='${USER_ID}'" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" || echo '{"totalItems":0,"items":[]}')

echo "${SYSTEMS_RESPONSE}" | jq -r '.items[].id' | while read -r SYSTEM_ID; do
  SYSTEM_NAME=$(echo "${SYSTEMS_RESPONSE}" | jq -r ".items[] | select(.id == \"${SYSTEM_ID}\") | .name")
  echo "Configuring alerts for system: ${SYSTEM_NAME} (${SYSTEM_ID})"

  for ALERT_TYPE in cpu mem disk; do
    case ${ALERT_TYPE} in
      cpu)  THRESHOLD=${CPU_THRESHOLD} ;;
      mem)  THRESHOLD=${MEMORY_THRESHOLD} ;;
      disk) THRESHOLD=${DISK_THRESHOLD} ;;
    esac

    # Check if alert already exists for this system + type
    EXISTING_ID=$(echo "${ALERTS_RESPONSE}" | jq -r \
      ".items[] | select(.system == \"${SYSTEM_ID}\" and .name == \"${ALERT_TYPE}\") | .id" || echo "")

    ALERT_PAYLOAD=$(jq -n \
      --arg user "${USER_ID}" \
      --arg system "${SYSTEM_ID}" \
      --arg name "${ALERT_TYPE}" \
      --argjson value "${THRESHOLD}" \
      '{user: $user, system: $system, name: $name, value: $value, triggered: false}')

    if [ -n "${EXISTING_ID}" ]; then
      echo "  Updating ${ALERT_TYPE} alert (${EXISTING_ID})..."
      curl "${CURL_OPTS[@]}" \
        -X PATCH "${BESZEL_URL}/api/collections/alerts/records/${EXISTING_ID}" \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "${ALERT_PAYLOAD}" > /dev/null || echo "  WARNING: Failed to update ${ALERT_TYPE} alert"
    else
      echo "  Creating ${ALERT_TYPE} alert (threshold: ${THRESHOLD}%)..."
      curl "${CURL_OPTS[@]}" \
        -X POST "${BESZEL_URL}/api/collections/alerts/records" \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "${ALERT_PAYLOAD}" > /dev/null || echo "  WARNING: Failed to create ${ALERT_TYPE} alert"
    fi
  done
done

echo "Beszel configuration complete"
