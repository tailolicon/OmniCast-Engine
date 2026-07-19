@echo off
cd /d "%~dp0"
uv run pytest tests/unit/test_models.py -v --tb=short > test_output.txt 2>&1
type test_output.txt