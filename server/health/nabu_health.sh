#!/bin/bash
# Health check for the voice stack (run from cron every minute on the server).
# Checks HA, Whisper, the language proxy, Piper, the RVC service and the speaker
# entity. A failed container is restarted once per 10 minutes; every event is
# written to /opt/applio-data/health.log and pushed to HA as a persistent
# notification so it is visible in the app.
set -u
LOG=/opt/applio-data/health.log
STATE=/opt/applio-data/health.state   # last restart timestamps per service
TOKEN_FILE=/opt/applio-data/secrets/ha_token
HA=http://127.0.0.1:8123
SPEAKER=assist_satellite.home_assistant_voice_0a0438_assist_satellite
touch "$STATE"

now() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "$(now) $*" >> "$LOG"; }

notify() {  # title, message
  [ -r "$TOKEN_FILE" ] || return 0
  curl -s -o /dev/null -X POST -H "Authorization: Bearer $(cat "$TOKEN_FILE")" \
    -H "Content-Type: application/json" \
    -d "{\"notification_id\":\"nabu_health\",\"title\":\"$1\",\"message\":\"$2\"}" \
    "$HA/api/services/persistent_notification/create"
}

# tcp_ok host port
tcp_ok() { timeout 3 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }

restart_once() {  # container name
  local name=$1 last
  last=$(grep "^$name " "$STATE" | awk '{print $2}')
  local ts; ts=$(date +%s)
  if [ -n "$last" ] && [ $((ts - last)) -lt 600 ]; then
    log "$name still down, restarted <10 min ago, not restarting again"
    return 1
  fi
  sudo docker restart "$name" >/dev/null 2>&1 && log "restarted $name" || log "restart of $name FAILED"
  grep -v "^$name " "$STATE" > "$STATE.tmp"; echo "$name $ts" >> "$STATE.tmp"; mv "$STATE.tmp" "$STATE"
  notify "Nabu health" "$name was down and has been restarted ($(now))."
}

failed=()

# 1. Home Assistant
if ! curl -s -o /dev/null -m 5 -w '%{http_code}' "$HA/api/" -H "Authorization: Bearer $(cat "$TOKEN_FILE" 2>/dev/null)" | grep -q 200; then
  failed+=(homeassistant)
fi
# 2-4. speech services
tcp_ok 127.0.0.1 10300 || failed+=(wyoming-whisper)
tcp_ok 127.0.0.1 10301 || failed+=(wyoming-langproxy)
tcp_ok 127.0.0.1 10200 || failed+=(wyoming-piper)
# 5. RVC service must answer /health with ready:true
if ! curl -s -m 5 http://127.0.0.1:10500/health | grep -q '"ready": true'; then
  failed+=(applio)
fi

for svc in "${failed[@]:-}"; do
  [ -z "$svc" ] && continue
  log "DOWN: $svc"
  restart_once "$svc"
done

# 6. speaker: entity must exist and not be unavailable (no restart possible; notify once per hour)
if [ -r "$TOKEN_FILE" ]; then
  st=$(curl -s -m 5 -H "Authorization: Bearer $(cat "$TOKEN_FILE")" "$HA/api/states/$SPEAKER" | grep -oE '"state": *"[^"]+"' | head -1)
  case "$st" in
    *unavailable*|"")
      last=$(grep "^speaker " "$STATE" | awk '{print $2}'); ts=$(date +%s)
      if [ -z "$last" ] || [ $((ts - last)) -ge 3600 ]; then
        log "speaker unavailable ($st)"
        notify "Nabu health" "The Voice PE speaker is unavailable ($(now)). Check power and Wi-Fi."
        grep -v "^speaker " "$STATE" > "$STATE.tmp"; echo "speaker $ts" >> "$STATE.tmp"; mv "$STATE.tmp" "$STATE"
      fi;;
  esac
fi

[ ${#failed[@]} -eq 0 ] && [ -n "${VERBOSE:-}" ] && log "all ok"
exit 0
