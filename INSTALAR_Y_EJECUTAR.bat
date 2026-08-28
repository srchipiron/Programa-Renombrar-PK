@echo off
REM ===================================================================
REM  Renombrador PKS - AEROSCAN
REM  PRIMERA INSTALACION - Configura todo desde cero en cualquier PC
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Instalacion - Renombrador PKS AEROSCAN

cls
echo.
echo  =====================================================================
echo    RENOMBRADOR PKS - AEROSCAN
echo    Instalacion y primer inicio automatico
echo  =====================================================================
echo.
echo  Este asistente instalara todo lo necesario:
echo    - Python 3.11 (si no esta instalado)
echo    - Librerias del programa
echo    - Iniciara la aplicacion automaticamente
echo.
echo  El proceso puede tardar 3-8 minutos la primera vez.
echo  Las siguientes veces sera instantaneo.
echo.
pause

REM ── PASO 1: Comprobar si ya existe el .exe compilado ──────────────
if exist "dist\RenombradorPKS\RenombradorPKS.exe" (
    echo.
    echo  [OK] Ejecutable standalone encontrado. Iniciando...
    start "" "dist\RenombradorPKS\RenombradorPKS.exe"
    exit /b 0
)

REM ── PASO 2: Comprobar si ya hay entorno virtual ────────────────────
if exist "venv\Scripts\python.exe" (
    echo  [OK] Entorno virtual ya existe.
    set "PYTHON_EXE=venv\Scripts\python.exe"
    goto :INSTALL_DEPS
)

REM ── PASO 3: Buscar Python en el sistema ───────────────────────────
cls
echo  =====================================================================
echo   PASO 1 de 3 - Comprobando Python
echo  =====================================================================
echo.

set "FOUND_PYTHON=0"
set "PYTHON_CMD="

REM Comprobar python
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if !ERRORLEVEL!==0 ( set "FOUND_PYTHON=1" & set "PYTHON_CMD=python" )
)

REM Comprobar py launcher
if !FOUND_PYTHON!==0 (
    where py >nul 2>&1
    if !ERRORLEVEL!==0 (
        py -3 -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
        if !ERRORLEVEL!==0 ( set "FOUND_PYTHON=1" & set "PYTHON_CMD=py -3" )
    )
)

if !FOUND_PYTHON!==1 (
    echo  [OK] Python encontrado en el sistema.
    goto :CREATE_VENV_STEP
)

REM ── PASO 4: Instalar Python automaticamente ────────────────────────
echo  Python no esta instalado. Intentando instalacion automatica...
echo.

set "INSTALL_OK=0"
where winget >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  Instalando Python 3.11 via winget...
    echo  ^(Esto puede tardar 2-3 minutos^)
    echo.
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if !ERRORLEVEL!==0 (
        echo  [OK] Python instalado correctamente via winget.
        set "INSTALL_OK=1"
        REM Recargar PATH
        for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USER_PATH=%%B"
        for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYS_PATH=%%B"
        set "PATH=!SYS_PATH!;!USER_PATH!"
        set "PYTHON_CMD=python"
    )
)

if !INSTALL_OK!==0 (
    cls
    echo  =====================================================================
    echo   INSTALACION MANUAL DE PYTHON NECESARIA
    echo  =====================================================================
    echo.
    echo  No se pudo instalar Python automaticamente.
    echo.
    echo  Por favor, sigue estos pasos:
    echo.
    echo   1. Se va a abrir la pagina de descarga de Python
    echo   2. Descarga "Python 3.11.x" para Windows 64-bit
    echo   3. Durante la instalacion, MARCA la casilla:
    echo         [x] Add Python to PATH
    echo   4. Completa la instalacion
    echo   5. Vuelve a ejecutar este archivo
    echo.
    echo  Abriendo descarga de Python en 5 segundos...
    timeout /t 5 >nul
    start "" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    echo.
    echo  Una vez que Python este instalado, vuelve a ejecutar
    echo  este archivo (INSTALAR_Y_EJECUTAR.bat) para continuar.
    echo.
    pause
    exit /b 1
)

REM ── PASO 5: Crear entorno virtual ─────────────────────────────────
:CREATE_VENV_STEP
cls
echo  =====================================================================
echo   PASO 2 de 3 - Creando entorno virtual
echo  =====================================================================
echo.
echo  Creando entorno aislado para el programa...

if defined PYTHON_CMD (
    %PYTHON_CMD% -m venv venv
) else (
    python -m venv venv
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] No se pudo crear el entorno virtual.
    pause
    exit /b 1
)
echo  [OK] Entorno virtual creado en: venv\
set "PYTHON_EXE=venv\Scripts\python.exe"

REM ── PASO 6: Instalar dependencias ─────────────────────────────────
:INSTALL_DEPS
cls
echo  =====================================================================
echo   PASO 3 de 3 - Instalando librerias del programa
echo  =====================================================================
echo.
echo  Instalando: PySide6, Pillow, shapely, piexif, pysrt...
echo  ^(Primera vez puede tardar 3-5 minutos segun la conexion^)
echo.

"%PYTHON_EXE%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%PYTHON_EXE%" -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Algunas librerias no se pudieron instalar.
    echo  Comprueba tu conexion a internet e intenta de nuevo.
    pause
    exit /b 1
)

REM ── INICIO ────────────────────────────────────────────────────────
cls
echo  =====================================================================
echo   INSTALACION COMPLETADA
echo  =====================================================================
echo.
echo  Todo instalado correctamente.
echo  La proxima vez usa directamente ejecutar.bat o run.bat
echo.
echo  Iniciando Renombrador PKS...
echo.
timeout /t 2 >nul

"%PYTHON_EXE%" main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  La aplicacion cerro con un error.
    echo  Comprueba que el archivo requirements.txt este correcto.
    pause
)
endlocal
exit /b 0
