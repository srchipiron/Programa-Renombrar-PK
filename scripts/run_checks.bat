@echo off
REM Run the standard developer workflow checks (pytest, headless Qt).
setlocal
cd /d "%~dp0.."

set QT_QPA_PLATFORM=offscreen

echo [1/2] Comprobando dependencias...
python -c "import PySide6, shapely, PIL, piexif" 2>nul
if errorlevel 1 (
    echo Instala dependencias: pip install -r requirements.txt pytest pytest-qt
    exit /b 1
)

echo [2/2] Ejecutando tests...
python -m pytest tests/ -q --tb=short
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE%==0 (
    echo.
    echo OK — todos los tests pasaron.
) else (
    echo.
    echo FALLIDO — revisa la salida de pytest arriba.
)

exit /b %EXIT_CODE%
