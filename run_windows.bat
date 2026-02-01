@echo off
set VENV_DIR=.venv

echo 🚀 Starting GenAI Dashboard...

:: 1. Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found!
    echo 👉 Please install Python: https://www.python.org/downloads/
    pause
    exit /b
)

:: 2. Создание venv, если нет
if not exist %VENV_DIR% (
    echo 📦 Creating virtual environment...
    python -m venv %VENV_DIR%
    echo ✅ Created.
)

:: 3. Активация и установка
call %VENV_DIR%\Scripts\activate.bat

if exist requirements.txt (
    echo ⬇️ Checking dependencies...
    pip install -r requirements.txt
) else (
    echo ⚠️ requirements.txt not found.
)

:: 4. Запуск
echo 🟢 Running Streamlit...
streamlit run app.py

pause