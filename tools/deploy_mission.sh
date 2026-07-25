#!/usr/bin/env bash
# Put a built .miz on the DCS server and make it the mission clients actually get.
#
# THE WHOLE POINT OF THIS SCRIPT: gRPC LoadMission swaps the SIM but not the
# MULTIPLAYER layer. The sim happily runs the new mission while ASYNCNET keeps
# serving the one the server booted with, so a connecting client is offered a
# mission that is not running and sits on the loading screen forever. Nothing
# reports this -- the server log looks healthy from every angle, gRPC reports
# the new mission, and the only symptom is a pilot staring at a progress bar.
#
# It happened twice. The second time was after concluding, wrongly, that the
# problem had been hot-loading during boot rather than hot-loading at all.
#
# So: write the mission into serverSettings.lua and RESTART. A hot-load is only
# ever acceptable when nobody is going to connect.
#
#   ./tools/deploy_mission.sh build/missions/362nd-Blind-Flying.miz [name]
set -euo pipefail

MIZ="${1:?usage: deploy_mission.sh <path-to-miz> [remote-name]}"
NAME="${2:-$(basename "${MIZ%.miz}")-$(date +%H%M).miz}"
HOST="${DCS_SSH:-dcsserver}"
MISSIONS='C:\Users\dcsuser\Saved Games\DCS.dcs_serverrelease\Missions'

[ -f "$MIZ" ] || { echo "no such mission: $MIZ" >&2; exit 1; }
echo "deploying $(basename "$MIZ") as $NAME"

# A fresh name every time: the loaded .miz is file-locked on Windows, so
# overwriting the running mission fails silently or half-writes.
scp -q "$MIZ" "$HOST:$NAME"
ssh "$HOST" "powershell -Command \"Copy-Item -Path '\$HOME\\$NAME' -Destination '$MISSIONS\\$NAME' -Force; (Get-Item '$MISSIONS\\$NAME').Length\"" | tail -1

# Point the server at it. Written WITHOUT a BOM: PowerShell's -Encoding UTF8
# adds one, DCS then cannot parse serverSettings.lua, and the server wedges on
# boot at "enterToState_:3" with no error anywhere. That cost an evening.
cat > /tmp/_setmission.ps1 <<PS1
\$cfg = "\$env:USERPROFILE\Saved Games\DCS.dcs_serverrelease\Config\serverSettings.lua"
\$miz = "$(printf '%s' "$MISSIONS\\$NAME" | sed 's/\\/\\\\/g')"
\$t = [System.IO.File]::ReadAllText(\$cfg)
if (\$t.Length -gt 0 -and \$t[0] -eq [char]0xFEFF) { \$t = \$t.Substring(1) }
\$t = [regex]::Replace(\$t, '(?s)(\["missionList"\]\s*=\s*\r?\n\s*\{).*?(\}, -- end of \["missionList"\])',
                      ('\${1}' + "\`r\`n\`t\`t[1] = \`"\$miz\`",\`r\`n\`t" + '\${2}'))
[System.IO.File]::WriteAllText(\$cfg, \$t, (New-Object System.Text.UTF8Encoding(\$false)))
\$b = [System.IO.File]::ReadAllBytes(\$cfg)
if (\$b[0] -eq 239) { Write-Error "BOM survived -- DCS will not boot"; exit 1 }
PS1
scp -q /tmp/_setmission.ps1 "$HOST:_setmission.ps1"
ssh "$HOST" 'powershell -NoProfile -ExecutionPolicy Bypass -File _setmission.ps1'

echo "restarting (NOT hot-loading -- see the comment at the top)"
ssh "$HOST" 'powershell -Command Start-ScheduledTask -TaskName DCSRestart' >/dev/null

LOG='Saved Games/DCS.dcs_serverrelease/Logs/dcs.log'
for _ in $(seq 1 24); do
  sleep 15
  scp -q "$HOST:$LOG" /tmp/_dcs.log 2>/dev/null || continue
  grep -q "loadMission Done" /tmp/_dcs.log && break
done

# The check that matters: the MULTIPLAYER layer must name our file. If this
# line says something else, clients will hang no matter how healthy the rest
# of the server looks.
SERVED=$(grep -E "ASYNCNET.*Loading mission" /tmp/_dcs.log | tail -1)
echo "$SERVED"
case "$SERVED" in
  *"$NAME"*) echo "OK: the multiplayer layer is serving $NAME" ;;
  *) echo "FAIL: clients would be offered a different mission than the sim is running" >&2
     exit 1 ;;
esac
# The kneeboard runs in a container that generates its pages ONCE, at start,
# from mounted source. So every route.py change -- a frequency, a minimum, an
# MSA -- is invisible on the chart until it restarts, and a pilot flies a
# mission whose card disagrees with it. That is the same failure as the radio
# presets, and it is silent from both ends: the page looks fine, it is just
# answering an older question.
#
# A mission deploy is exactly when the two must agree, so it happens here.
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx marshall-kneeboard; then
  echo "rebuilding the kneeboard (it regenerates only on container start)"
  docker restart marshall-kneeboard >/dev/null
fi

echo "now unpause: it boots paused (pause_on_load), and AI tasking is frozen until you do"
