@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%CD%"
set "LOG=%ROOT%\desktop-start.log"
set "DESKTOP=%ROOT%\desktop"
set "WEB=%ROOT%\wallbreaker\dashboard\web"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "VENV_BIN=%ROOT%\.venv\Scripts"

> "%LOG%" echo Wallbreaker Desktop start log
>> "%LOG%" echo root=%ROOT%
>> "%LOG%" echo time=%DATE% %TIME%

echo.
echo ============================================
echo  Wallbreaker Desktop quick start
echo  Root: %ROOT%
echo ============================================
echo.

if exist "%VENV_PY%" set "PATH=%VENV_BIN%;%PATH%"
if exist "%VENV_PY%" >> "%LOG%" echo using venv python

where node >nul 2>&1
if errorlevel 1 goto ERR_NODE
where npm >nul 2>&1
if errorlevel 1 goto ERR_NPM
if not exist "%DESKTOP%\package.json" goto ERR_PKG

if exist "%DESKTOP%\node_modules\" goto SKIP_DESKTOP_INSTALL
echo [1/3] Installing desktop dependencies...
>> "%LOG%" echo npm install desktop
pushd "%DESKTOP%"
call npm.cmd install
if errorlevel 1 goto ERR_DESKTOP_INSTALL
popd
goto AFTER_DESKTOP_INSTALL

:SKIP_DESKTOP_INSTALL
echo [1/3] desktop node_modules OK
>> "%LOG%" echo desktop node_modules OK

:AFTER_DESKTOP_INSTALL
if exist "%WEB%\dist\index.html" goto SKIP_WEB_BUILD
echo [2/3] Building dashboard web UI...
>> "%LOG%" echo building dashboard
if exist "%WEB%\node_modules\" goto WEB_BUILD
pushd "%WEB%"
call npm.cmd install
if errorlevel 1 goto ERR_WEB_INSTALL
popd

:WEB_BUILD
pushd "%WEB%"
call npm.cmd run build
if errorlevel 1 goto ERR_WEB_BUILD
popd
goto AFTER_WEB_BUILD

:SKIP_WEB_BUILD
echo [2/3] dashboard dist OK
>> "%LOG%" echo dashboard dist OK

:AFTER_WEB_BUILD
echo [3/3] Launching desktop...
echo       Close the app window, or press Ctrl+C here to stop.
echo.
>> "%LOG%" echo launching npm run dev
pushd "%DESKTOP%"
call npm.cmd run dev
set "EC=%ERRORLEVEL%"
popd
>> "%LOG%" echo exit=%EC%
if not "%EC%"=="0" goto ERR_EXIT
exit /b 0

:ERR_NODE
echo [ERROR] Node.js not found. Install Node 20+ first.
>> "%LOG%" echo ERROR node missing
goto END_FAIL

:ERR_NPM
echo [ERROR] npm not found. Install Node.js first.
>> "%LOG%" echo ERROR npm missing
goto END_FAIL

:ERR_PKG
echo [ERROR] desktop\package.json missing.
>> "%LOG%" echo ERROR package.json missing
goto END_FAIL

:ERR_DESKTOP_INSTALL
popd
echo [ERROR] desktop npm install failed.
echo See log: %LOG%
>> "%LOG%" echo ERROR desktop npm install
goto END_FAIL

:ERR_WEB_INSTALL
popd
echo [ERROR] dashboard npm install failed.
echo See log: %LOG%
>> "%LOG%" echo ERROR web npm install
goto END_FAIL

:ERR_WEB_BUILD
popd
echo [ERROR] dashboard build failed.
echo See log: %LOG%
>> "%LOG%" echo ERROR web build
goto END_FAIL

:ERR_EXIT
echo.
echo [ERROR] Desktop exited with code %EC%
echo Log: %LOG%
echo Tips:
echo   1. .venv\Scripts\activate
echo   2. pip install -e ".[dashboard]"
echo   3. check .env / config.toml
goto END_FAIL

:END_FAIL
echo.
pause
exit /b 1
