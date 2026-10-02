@echo off
REM Run the standard developer workflow checks (pytest, headless Qt).
setlocal
cd /d "%~dp0.."

set QT_QPA_PLATFORM=offscreen

REM Prefer the project venv: the system Python and the venv diverged once
REM (the system one lost its packages) and the checks must run on the
REM environment the app is actually launched with.
set PY=python
if exist "venv\Scripts\python.exe" set PY=venv\Scripts\python.exe

echo [1/2] Comprobando dependencias...
%PY% -c "import PySide6, shapely, PIL, piexif" 2>nul
if errorlevel 1 (
    echo Instala dependencias: pip install -r requirements.txt pytest pytest-qt
    exit /b 1
)

echo [2/2] Ejecutando tests...
%PY% -m pytest tests/ -q --tb=short
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE%==0 (
    echo.
    echo OK — todos los tests pasaron.
) else (
    echo.
    echo FALLIDO — revisa la salida de pytest arriba.
)

exit /b %EXIT_CODE%
