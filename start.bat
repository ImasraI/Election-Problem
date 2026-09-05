@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="--server" goto :run_server

echo ============================================
echo  Social Choice Workshop - setup and start
echo ============================================
echo.

call :find_python
if defined PYCMD goto :deps

echo Python was not found. Installing Python 3.12 ...
call :install_python
call :refresh_path
call :find_python
if defined PYCMD goto :deps

echo.
echo Python could not be installed automatically.
echo Install Python 3 from https://www.python.org/downloads
echo and tick "Add python.exe to PATH", then run this file again.
pause
exit /b 1

:deps
echo Using: %PYCMD%
echo Installing Python packages...
%PYCMD% -m ensurepip --upgrade >nul 2>&1
%PYCMD% -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo Could not install packages. Check your internet connection and try again.
  pause
  exit /b 1
)
echo.

echo Starting the workshop server...
start "Social Choice Workshop" /D "%~dp0" cmd /c ""%~f0" --server"

echo Waiting for http://localhost:8765 ...
echo If it asks for an API key, type it in the other window.
:wait
timeout /t 1 /nobreak >nul
%PYCMD% -c "import socket; socket.create_connection(('127.0.0.1', 8765), 1).close()" 2>nul
if errorlevel 1 goto wait

start "" "http://localhost:8765/index.html"
exit /b 0

:run_server
call :find_python
if not defined PYCMD (
  echo Python was not found.
  pause
  exit /b 1
)
%PYCMD% llm.py
if errorlevel 1 pause
exit /b %ERRORLEVEL%

:find_python
set "PYCMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYCMD=py -3"
  exit /b 0
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYCMD=python"
  exit /b 0
)
python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYCMD=python3"
  exit /b 0
)
for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
) do (
  if exist %%P (
    set "PYCMD=%%~P"
    exit /b 0
  )
)
exit /b 1

:refresh_path
for /f "skip=2 tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SysPath=%%B"
for /f "skip=2 tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "UserPath=%%B"
set "PATH=%UserPath%;%SysPath%;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%LocalAppData%\Programs\Python\Python313;%LocalAppData%\Programs\Python\Python313\Scripts;%LocalAppData%\Programs\Python\Launcher;%PATH%"
exit /b 0

:install_python
where winget >nul 2>&1
if not errorlevel 1 (
  echo Trying winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if not errorlevel 1 exit /b 0
)

echo Downloading the Python installer...
set "PY_INST=%TEMP%\python-3.12.10-setup.exe"
set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-arm64.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INST%'"
if not exist "%PY_INST%" exit /b 1

echo Running the Python installer...
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 Include_test=0 SimpleInstall=1
exit /b %ERRORLEVEL%
