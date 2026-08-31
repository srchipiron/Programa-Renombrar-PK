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

REM -- Empaquetar portable (ZIP) -------------------------------------
echo.
echo [5/6] Empaquetando version portable...
set "ZIP_NAME=RenombradorPKS-portable.zip"
if exist "dist\%ZIP_NAME%" del /q "dist\%ZIP_NAME%"

REM Ojo: "tar -a -c -f x.zip" NO comprime, solo almacena (medido: un DLL de
REM 195 MB seguia ocupando 195 MB). 7-Zip si lo hace y es el mas rapido;
REM Compress-Archive es el plan B y viene con Windows.
set "SEVENZIP="
where 7z >nul 2>&1 && set "SEVENZIP=7z"
if not defined SEVENZIP if exist "%ProgramFiles%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles%\7-Zip\7z.exe"

if defined SEVENZIP (
    echo      Comprimiendo con 7-Zip...
    "%SEVENZIP%" a -tzip -mx=5 -bso0 -bsp0 "dist\%ZIP_NAME%" ".\dist\RenombradorPKS"
) else (
    echo      Comprimiendo con PowerShell ^(varios minutos^)...
    powershell -NoProfile -Command "Compress-Archive -Path 'dist\RenombradorPKS' -DestinationPath 'dist\%ZIP_NAME%' -CompressionLevel Optimal -Force"
)
if exist "dist\%ZIP_NAME%" (
    echo      Portable listo: dist\%ZIP_NAME%
) else (
    echo      [AVISO] No se pudo crear el ZIP portable.
)

REM -- Instalador (opcional, si hay Inno Setup) -----------------------
echo.
echo [6/6] Instalador...
set "ISCC="
where iscc >nul 2>&1
if %ERRORLEVEL%==0 set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

for /f %%V in ('"%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from src.core.version import __version__; print(__version__)" 2^>nul') do set "APP_VERSION=%%V"
if not defined APP_VERSION set "APP_VERSION=0.0.0"
echo      Version: %APP_VERSION%

if defined ISCC (
    "%ISCC%" /DAppVersion=%APP_VERSION% installer.iss
    if !ERRORLEVEL!==0 (
        echo      Instalador listo en dist_installer\
    ) else (
        echo      [AVISO] Inno Setup devolvio error.
    )
) else (
    echo      Inno Setup no encontrado: se omite el instalador.
    echo      Para generarlo:  winget install JRSoftware.InnoSetup
    echo      y vuelve a ejecutar este script.
)

REM -- Resultado -----------------------------------------------------
echo.
echo =================================================================
echo   BUILD COMPLETADO
echo =================================================================
echo.
set "DIST_SIZE="
for /f %%A in ('powershell -NoProfile -Command "[int]((Get-ChildItem -Recurse dist\RenombradorPKS | Measure-Object -Property Length -Sum).Sum / 1MB)" 2^>nul') do set "DIST_SIZE=%%A"
set "ZIP_SIZE="
for /f %%A in ('powershell -NoProfile -Command "[int]((Get-Item 'dist\%ZIP_NAME%' -ErrorAction SilentlyContinue).Length / 1MB)" 2^>nul') do set "ZIP_SIZE=%%A"

echo   1) Carpeta portable : dist\RenombradorPKS\  (%DIST_SIZE% MB)
echo      Copiala entera al PC destino y ejecuta RenombradorPKS.exe.
echo      No necesita Python ni permisos de administrador.
echo.
if defined ZIP_SIZE echo   2) ZIP para enviar  : dist\%ZIP_NAME%  (%ZIP_SIZE% MB)
if not defined ZIP_SIZE echo   2) ZIP para enviar  : no generado
echo.
if defined ISCC echo   3) Instalador       : dist_installer\
if not defined ISCC echo   3) Instalador       : requiere Inno Setup 6
echo.
echo   Los ajustes (config.json, proyectos\, logs\) se crean junto al
echo   ejecutable si la carpeta es escribible; si no, en %%LOCALAPPDATA%%.
echo.
pause
endlocal
exit /b 0
