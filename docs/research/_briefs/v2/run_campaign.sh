#!/bin/sh
# V2 campaign launcher — sequential grok sessions, quota-frugal flags.
# Order: A1 (TTS) -> B2 (Flow API gold) -> A2 -> B1 -> C (harvest) -> D.
cd "/e/Project/OmniCast Engine" || exit 1
GROK="$USERPROFILE/.grok/bin/grok.exe"
BR="docs/research/_briefs/v2"
LOG="$BR/logs"
mkdir -p "$LOG"

run_one() {
  name="$1"; brief="$2"; out="$3"; turns="$4"
  echo "=== [$name] start $(date) turns=$turns ==="
  "$GROK" --prompt-file "$brief" --always-approve --max-turns "$turns" \
    --no-plan --no-subagents --reasoning-effort low --disable-web-search \
    > "$LOG/$name.log" 2>&1
  code=$?
  if [ -s "$out" ]; then
    lines=$(wc -l < "$out")
    echo "=== [$name] DONE exit=$code output=$out lines=$lines ==="
  else
    echo "=== [$name] FAILED exit=$code — no output file $out ==="
    tail -5 "$LOG/$name.log"
    if grep -qiE "quota|rate.?limit|429|credit" "$LOG/$name.log"; then
      echo "=== QUOTA SUSPECTED — stopping campaign ==="
      exit 2
    fi
  fi
}

run_one A1 "$BR/A1_ttsdub_videolingo_pyvideotrans.md" "docs/research/V2_A1_TTSDub.md" 60
run_one B2 "$BR/B2_tools_flow_remotion.md"            "docs/research/V2_B2_ToolsFlow.md" 60
run_one A2 "$BR/A2_voice_cap_assistant.md"            "docs/research/V2_A2_VoiceCap.md" 50
run_one B1 "$BR/B1_engines_mpt_pixelle.md"            "docs/research/V2_B1_Engines.md" 60
run_one C  "$BR/C_sb_prompt_config_harvest.md"        "docs/research/V2_C_SBHarvest.md" 80
run_one D  "$BR/D_agent_frameworks.md"                "docs/research/V2_D_AgentFrameworks.md" 60
echo "=== CAMPAIGN COMPLETE $(date) ==="
