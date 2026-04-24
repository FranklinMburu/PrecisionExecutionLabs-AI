@echo off
echo --- MT5 Straddle Engine Setup ---
echo.
echo 1. Creating Virtual Environment...
python -m venv venv
echo 2. Activating Environment and Installing Requirements...
call venv\Scripts\activate
pip install -r requirements.txt
echo.
echo --- Setup Complete ---
echo To run the bot:
echo 1. Fill your credentials in the .env file
echo 2. Run: python main.py
echo.
pause
