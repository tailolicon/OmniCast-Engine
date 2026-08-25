@echo off
REM ============================================================================
REM  Commit P1 (3 muc) + P2.0 animation foundation cua brief §15
REM  KHONG phai "P1+P2 hoan tat" — xem IMPLEMENTATION_STATUS.md §4c
REM
REM  CHAY TREN WINDOWS. Git qua bridge Linux khong unlink duoc file tam trong
REM  .git/objects, stage 0 file va de lai .git/index.lock.
REM
REM  Chi stage dung cac file cua dot nay. Moi thay doi khac van nam nguyen.
REM ============================================================================
cd /d "E:\Project\OmniCast Engine"

echo.
echo === Nhanh hien tai ===
git rev-parse --abbrev-ref HEAD
git log -1 --oneline

echo.
echo === Stage P1 muc 1: audiovisual forensics ===
git add ^
 implementation/src/omnicast/analytics/av_forensics.py ^
 implementation/src/omnicast/analytics/av_fetch.py ^
 implementation/src/omnicast/analytics/video_intel.py ^
 implementation/src/omnicast/analytics/competitor_intel.py ^
 implementation/src/omnicast/analytics/intel_scope.py ^
 implementation/src/omnicast/analytics/intel_gate.py ^
 implementation/tests/unit/test_av_forensics_p1.py

echo.
echo === Stage P1 muc 2: channel strategy (§11) ===
git add ^
 implementation/src/omnicast/strategy ^
 implementation/tests/unit/test_channel_strategy_p1.py

echo.
echo === Stage P1 muc 3: quality + benchmark gates (§8, §9) ===
git add ^
 implementation/src/omnicast/quality ^
 implementation/tests/unit/test_quality_gates_p1.py

echo.
echo === Stage P2: animation subsystem (§7.1) ===
git add ^
 implementation/src/omnicast/animation ^
 implementation/tests/unit/test_animation_p2.py

echo.
echo === Stage wiring + shared + review fixes ===
git add ^
 implementation/src/omnicast/shared/numbers.py ^
 implementation/src/omnicast/media/output_audit.py ^
 implementation/src/omnicast/pipeline/steps.py ^
 implementation/src/omnicast/api/server.py ^
 implementation/src/omnicast/config/channel.py ^
 implementation/src/omnicast/config/settings.py ^
 implementation/src/omnicast/discovery/scoring_calibration.py ^
 implementation/src/omnicast/media/production_router.py ^
 implementation/render_real_video.py ^
 implementation/clickbait.py ^
 implementation/tests/unit/test_p1_p2_review_fixes.py ^
 implementation/src/omnicast/storage/products.py ^
 implementation/src/omnicast/api/render_routes.py ^
 implementation/src/omnicast/platforms/service.py ^
 implementation/tests/unit/test_review_round4_fixes.py ^
 implementation/tests/unit/test_review_round6_wiring.py ^
 implementation/tests/unit/test_production_router_p0.py

echo.
echo === Stage docs ===
git add IMPLEMENTATION_STATUS.md commit_p1_p2.bat commit_p1_p2_message.txt ^
 commit_p1_forensics.bat commit_p1_forensics_message.txt

echo.
echo === Da stage (kiem tra truoc khi commit) ===
git diff --cached --name-only

echo.
echo === Con lai unstaged (KHONG commit o day) ===
git status --short ^| find /c /v ""

echo.
echo Nhan Ctrl+C de huy, hoac Enter de commit.
pause

git commit -F "%~dp0commit_p1_p2_message.txt"

echo.
echo === Ket qua ===
git log -1 --stat ^| more
pause
