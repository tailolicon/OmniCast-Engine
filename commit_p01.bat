@echo off
REM ============================================================================
REM  Commit P0 + P0.1 (competitor intelligence + containment + SSOT router)
REM
REM  CHAY TREN WINDOWS, KHONG chay qua bridge Linux: git trong VM cua bridge
REM  khong unlink duoc file tam trong .git/objects, nen `git add` stage 0 file
REM  va de lai .git/index.lock.
REM
REM  Script nay CHI stage dung cac file cua dot lam viec nay. ~93 file churn
REM  CRLF va cac thay doi narrative/visual khong lien quan van nam nguyen
REM  unstaged — do la muc dich.
REM ============================================================================
cd /d "E:\Project\OmniCast Engine"

echo.
echo === Nhanh hien tai ===
git rev-parse --abbrev-ref HEAD

echo.
echo === Stage source ===
git add ^
 implementation/src/omnicast/analytics/cohort.py ^
 implementation/src/omnicast/analytics/transcript.py ^
 implementation/src/omnicast/analytics/competitor_intel.py ^
 implementation/src/omnicast/analytics/video_intel.py ^
 implementation/src/omnicast/analytics/intel_gate.py ^
 implementation/src/omnicast/discovery/scorer.py ^
 implementation/src/omnicast/discovery/scoring_calibration.py ^
 implementation/src/omnicast/discovery/shadow_log.py ^
 implementation/src/omnicast/discovery/topic_router.py ^
 implementation/src/omnicast/discovery/models.py ^
 implementation/src/omnicast/discovery/orchestrator.py ^
 implementation/src/omnicast/discovery/brief_generator.py ^
 implementation/src/omnicast/discovery/youtube_scanner.py ^
 implementation/src/omnicast/platforms/youtube.py ^
 implementation/src/omnicast/upload/youtube_api.py ^
 implementation/src/omnicast/upload/oauth.py ^
 implementation/src/omnicast/vault/db.py ^
 implementation/src/omnicast/vault/models.py ^
 implementation/src/omnicast/agents/writer.py ^
 implementation/src/omnicast/agents/channel_architect.py ^
 implementation/src/omnicast/models/script.py ^
 implementation/src/omnicast/config/settings.py ^
 implementation/src/omnicast/config/channel.py ^
 implementation/src/omnicast/pipeline/steps.py ^
 implementation/src/omnicast/api/server.py ^
 implementation/pyproject.toml

echo.
echo === Stage tests ===
git add ^
 implementation/tests/unit/test_cohort_selection.py ^
 implementation/tests/unit/test_transcript_fetch.py ^
 implementation/tests/unit/test_competitor_intel_cohort.py ^
 implementation/tests/unit/test_competitor_intel_containment.py ^
 implementation/tests/unit/test_youtube_comments.py ^
 implementation/tests/unit/test_scorer.py ^
 implementation/tests/unit/test_scorer_gap_and_stack_fit.py ^
 implementation/tests/unit/test_scoring_shadow_mode.py ^
 implementation/tests/unit/test_video_intel_measurement.py ^
 implementation/tests/unit/test_intel_gate.py ^
 implementation/tests/unit/test_writer_intel_gate_wiring.py ^
 implementation/tests/unit/test_topic_router_ssot.py ^
 implementation/tests/unit/test_p01_audit_regressions.py ^
 implementation/tests/unit/test_p01_audit_round2.py ^
 implementation/tests/unit/test_p01_round4_wiring.py ^
 implementation/tests/unit/test_discovery_models.py ^
 implementation/tests/unit/test_discovery_orchestrator.py

echo.
echo === Stage docs ===
git add docs/HANDOFF_P0_competitor_intel.md docs/HANDOFF_P01_containment.md docs/HANDOFF_P01_ssot.md

echo.
echo === Da stage (kiem tra truoc khi commit) ===
git diff --cached --name-only
echo.
echo === Con lai unstaged (churn CRLF + viec khac — KHONG commit o day) ===
git status --short ^| find /c /v ""

echo.
echo Nhan Ctrl+C de huy, hoac Enter de commit.
pause

git commit -F "%~dp0commit_p01_message.txt"

echo.
echo === Ket qua ===
git log -1 --stat ^| more
pause
