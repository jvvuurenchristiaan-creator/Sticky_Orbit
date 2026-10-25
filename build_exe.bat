@echo off
rem Builds StickyOrb.exe into this folder. The Python source stays untouched.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\python.exe" tools\make_icon.py || exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
    --name StickyOrb --icon "%~dp0assets\stickyorb.ico" ^
    --distpath "%~dp0." --workpath "%~dp0build\work" --specpath "%~dp0build" ^
    "%~dp0StickyOrb.pyw" || exit /b 1
echo.
echo Built %~dp0StickyOrb.exe
