@echo off
REM ===================================================================
REM  Renombrador PKS - AEROSCAN
REM  Lanzador inteligente: instala Python y dependencias si no existen
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Renombrador PKS - AEROSCAN

REM ── OPCION 0: Si existe el .exe compilado, usarlo directamente ──────
if exist "dist\RenombradorPKS\RenombradorPKS.exe" (
    echo Iniciando RenombradorPKS...
    start "" "dist\RenombradorPKS\RenombradorPKS.exe"
    exit /b 0
)

REM ── OPCION 1: Usar el entorno virtual local si existe ───────────────
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    goto :INSTALL_DEPS
)

REM ── OPCION 2: Buscar Python en el PATH ─────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if !ERRORLEVEL!==0 (
        set "PYTHON_EXE=python"
        goto :CREATE_VENV
    )
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if !ERRORLEVEL!==0 (
        set "PYTHON_EXE=py -3"
        goto :CREATE_VENV
    )
)

REM ── OPCION 3: Instalar Python via winget (Windows 10/11) ───────────
echo.
echo ================================================================
echo  Python no esta instalado. Instalando automaticamente...
echo ================================================================
echo.

where winget >nul 2>&1
if %ERRORLEVEL%==0 (
    echo Instalando Python 3.11 via winget...
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if !ERRORLEVEL! NEQ 0 (
        echo ERROR: winget no pudo instalar Python.
        goto :MANUAL_INSTALL
    )
    REM Recargar PATH para que python sea encontrado
    call :REFRESH_PATH
    where python >nul 2>&1
    if !ERRORLEVEL!==0 (
        set "PYTHON_EXE=python"
        goto :CREATE_VENV
    )
) else (
    goto :MANUAL_INSTALL
)

REM ── OPCION 4: Descarga manual del instalador de Python ─────────────
:MANUAL_INSTALL
echo.
echo ================================================================
echo  No se pudo instalar Python automaticamente.
echo  Por favor, instala Python 3.11 manualmente desde:
echo     https://www.python.org/downloads/
echo.
echo  IMPORTANTE: Marca la casilla "Add Python to PATH"
echo ================================================================
echo.
echo Abriendo la pagina de descarga en tu navegador...
start "" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
echo.
echo Una vez instalado Python, vuelve a ejecutar este archivo.
pause
exit /b 1

REM ── CREAR ENTORNO VIRTUAL ──────────────────────────────────────────
:CREATE_VENV
echo.
echo [1/3] Creando entorno virtual...
%PYTHON_EXE% -m venv venv
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: No se pudo crear el entorno virtual.
    pause
    exit /b 1
)
set "PYTHON_EXE=venv\Scripts\python.exe"

REM ── INSTALAR/ACTUALIZAR DEPENDENCIAS ──────────────────────────────
:INSTALL_DEPS
echo.
echo [2/3] Verificando e instalando dependencias...
"%PYTHON_EXE%" -m pip install --upgrade pip --quiet
"%PYTHON_EXE%" -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Fallo al instalar dependencias.
    echo Intenta ejecutar manualmente:
    echo    venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
echo Dependencias OK.

REM ── EJECUTAR APLICACION ───────────────────────────────────────────
:RUN_APP
echo.
echo [3/3] Iniciando Renombrador PKS...
echo.
"%PYTHON_EXE%" main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo La aplicacion cerro con un error ^(codigo: %ERRORLEVEL%^).
    echo Revisa los mensajes anteriores para mas detalles.
    pause
)
endlocal
exit /b 0

REM ── SUBRUTINA: Refrescar PATH despues de instalar Python ──────────
:REFRESH_PATH
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USER_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYS_PATH=%%B"
set "PATH=%SYS_PATH%;%USER_PATH%"
exit /b 0
