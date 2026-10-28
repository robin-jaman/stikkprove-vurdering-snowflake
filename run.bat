@echo off
cd /d "%~dp0"
echo Hvis appen krasjer med "utf-8 codec can't decode", kjor: python ensure_utf8.py
echo Deretter start pa nytt.
python -m pip install -r requirements.txt
python -m streamlit run app.py
