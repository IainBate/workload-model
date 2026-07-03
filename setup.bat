@echo off
REM Setup script for Workload Model Calculator (Windows)
REM Creates a virtual environment and installs dependencies

echo Setting up Workload Model Calculator...

REM Check Python version
python --version >nul 2>&1 || (
    echo ERROR: python not found. Please install Python 3.8+ from python.org.
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Setup complete!
echo Run 'python main.py' to execute the calculator.
echo Run 'python main.py --dry-run' to see a data summary.
pause
