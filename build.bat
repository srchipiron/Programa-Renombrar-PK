@echo off
REM ===================================================================
REM  Renombrador PKS - AEROSCAN
REM  Script de construccion del ejecutable standalone (.exe)
REM  Uso: Ejecutar este .bat en el PC donde tienes Python instalado.
REM  Resultado: dist\RenombradorPKS\RenombradorPKS.exe (sin Python)
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Build - Renombrador PKS

echo.
echo =================================================================
echo   Renombrador PKS - Build de Ejecutable Standalone
echo =================================================================
echo.

REM ── Buscar Python ─────────────────────────────────────────────────
set "PYTHON_EXE="
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [OK] Usando entorno virtual: venv\
    goto :CHECK_PYINSTALLER
)
where python >nul 2>&1
if %ERRORLEVEL%==0 ( set "PYTHON_EXE=python" & goto :CHECK_PYINSTALLER )
where py >nul 2>&1
if %ERRORLEVEL%==0 ( set "PYTHON_EXE=py -3" & goto :CHECK_PYINSTALLER )

echo [ERROR] No se encontro Python. Ejecuta primero ejecutar.bat para
echo         instalar Python y las dependencias.
pause
exit /b 1

REM ── Verificar/instalar PyInstaller ────────────────────────────────
:CHECK_PYINSTALLER
echo [1/4] Verificando PyInstaller...
"%PYTHON_EXE%" -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo      PyInstaller no encontrado. Instalando...
    "%PYTHON_EXE%" -m pip install pyinstaller --quiet
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] No se pudo instalar PyInstaller.
        pause
        exit /b 1
    )
)
echo      PyInstaller OK.

REM ── Instalar dependencias del proyecto ────────────────────────────
echo [2/4] Instalando dependencias...
"%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Fallo al instalar dependencias.
    pause
    exit /b 1
)
echo      Dependencias OK.

REM ── Limpiar builds anteriores ─────────────────────────────────────
echo [3/4] Limpiando builds anteriores...
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"

REM ── Ejecutar PyInstaller ──────────────────────────────────────────
echo [4/4] Compilando con PyInstaller (puede tardar 2-5 min)...
echo.
"%PYTHON_EXE%" -m PyInstaller --noconfirm RenombradorPKS.spec
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller ha fallado. Revisa los mensajes anteriores.
    pause
    exit /b 1
)

REM ── Resultado ─────────────────────────────────────────────────────
echo.
echo =================================================================
echo   BUILD COMPLETADO CON EXITO
echo =================================================================
echo.
echo   Ejecutable: dist\RenombradorPKS\RenombradorPKS.exe
echo.
set "DIST_SIZE="
for /f %%A in ('powershell -NoProfile -Command "(Get-ChildItem -Recurse dist\RenombradorPKS | Measure-Object -Property Length -Sum).Sum / 1MB" 2^>nul') do set "DIST_SIZE=%%A"
if defined DIST_SIZE echo   Tamano carpeta dist: %DIST_SIZE% MB aprox.
echo.
echo   Para distribuir: copia la carpeta dist\RenombradorPKS completa.
echo   El .exe funciona sin Python instalado en el PC destino.
echo.
echo   Para generar instalador .exe (opcional, requiere Inno Setup 6):
echo     iscc installer.iss
echo     Descarga: https://jrsoftware.org/isinfo.php
echo.
pause
endlocal
exit /b 0
