@echo off
setlocal EnableExtensions
title StepToSales launcher
rem ---------------------------------------------------------------
rem  StepToSales: reset the demo and start everything.
rem    start.bat          reset demo data, start API + web, open Chrome
rem    start.bat keep     same, but keep today's live data (no reset)
rem ---------------------------------------------------------------

cd /d "%~dp0"
set "ROOT=%~dp0"
set "URL=http://localhost:5173/login"

if not exist "backend\.venv\Scripts\activate.bat" (
  echo [x] backend\.venv not found. Create it first:
  echo     cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  goto fail
)

echo [1/5] Stopping anything still running from last time...
taskkill /FI "WINDOWTITLE eq StepToSales API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq StepToSales Web*" /T /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5173 .*LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1
timeout /t 2 /nobreak >nul

call "backend\.venv\Scripts\activate.bat"

echo [2/5] Updating the database...
pushd backend
alembic upgrade head
if errorlevel 1 (
  popd
  echo [x] Database update failed. Is PostgreSQL running?
  echo     Open Services and start "postgresql-x64-16", then run this again.
  goto fail
)

if /i "%~1"=="keep" (
  echo [3/5] Keeping existing demo data.
) else (
  echo [3/5] Resetting demo data...
  python scripts\reset_demo.py
  if errorlevel 1 (
    popd
    echo [x] reset_demo.py failed - see the message above.
    goto fail
  )
)
popd

if not exist "frontend\node_modules" (
  echo Installing frontend packages, first run only...
  pushd frontend
  call npm install
  popd
)

echo [4/5] Starting the API and the website in their own windows...
start "StepToSales API" /D "%ROOT%backend" cmd /k ".venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"
start "StepToSales Web" /D "%ROOT%frontend" cmd /k "npm run dev"

echo [5/5] Waiting for both to come up...
set /a tries=0
:wait
set /a tries+=1
curl -s -o nul http://localhost:8000/ && curl -s -o nul http://localhost:5173/ && goto up
if %tries% geq 90 (
  echo [!] Still not up after 90 seconds - check the two new windows for errors.
  goto open
)
timeout /t 1 /nobreak >nul
goto wait

:up
echo Ready.

:open
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined CHROME (
  start "" "%CHROME%" "%URL%"
) else (
  echo Chrome not found - opening your default browser instead.
  start "" "%URL%"
)

echo.
echo  StepToSales is running at %URL%
echo  Log in as s2 / s2shop, go to Dashboard, pick Today.
echo  The live shop may take a minute to catch up to the current time.
echo  To stop: close the "StepToSales API" and "StepToSales Web" windows.
echo.
timeout /t 15
exit /b 0

:fail
echo.
pause
exit /b 1
