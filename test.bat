@echo off
cd /d "%~dp0"
python tests/test_dedup.py
pause
