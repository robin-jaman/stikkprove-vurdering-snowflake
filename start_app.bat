@echo off
cd /d "%~dp0"
echo Hvis appen krasjer med "utf-8 codec can't decode", kjor: .venv\Scripts\python.exe ensure_utf8.py
echo Deretter start start_app.bat pa nytt.
if not exist ".venv\Scripts\python.exe" (
  echo Fant ikke .venv. Opprett det med: python -m venv .venv
  echo Installer deretter: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
