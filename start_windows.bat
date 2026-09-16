@echo off
cd /d "%~dp0"
if not exist .env copy .env.example .env
python -m uvicorn main:app --reload
pause
