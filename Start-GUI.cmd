@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if defined ENDFIELD_GUI_PYTHON goto custom_python
if exist "%~dp0_internal\python\python.exe" goto portable_python
if exist "%~dp0.dev-gui\dev-python.txt" goto check_dev_python
goto check_venv

:check_dev_python
set "GUI_DEV_PYTHON="
set /p "GUI_DEV_PYTHON=" < "%~dp0.dev-gui\dev-python.txt"
if not defined GUI_DEV_PYTHON goto check_venv
if exist "%~dp0%GUI_DEV_PYTHON%" goto dev_python
if exist "%GUI_DEV_PYTHON%" goto external_dev_python

:check_venv
if exist "%~dp0.venv\Scripts\python.exe" goto venv_python
where py >nul 2>nul
if not errorlevel 1 goto py_launcher
where python >nul 2>nul
if not errorlevel 1 goto path_python
echo Python was not found. Run Setup-Dev.cmd to prepare the development environment.
set "GUI_EXIT_CODE=1"
goto finish

:custom_python
"%ENDFIELD_GUI_PYTHON%" -B "%~dp0launch_gui.py" --detach %*
goto result

:portable_python
"%~dp0_internal\python\python.exe" -B "%~dp0launch_gui.py" --detach %*
goto result

:venv_python
"%~dp0.venv\Scripts\python.exe" -I -B "%~dp0launch_gui.py" --detach %*
goto result

:dev_python
"%~dp0%GUI_DEV_PYTHON%" -I -B "%~dp0launch_gui.py" --detach %*
goto result

:external_dev_python
"%GUI_DEV_PYTHON%" -B "%~dp0launch_gui.py" --detach %*
goto result

:py_launcher
py -3 -B "%~dp0launch_gui.py" --detach %*
goto result

:path_python
python -B "%~dp0launch_gui.py" --detach %*

:result
set "GUI_EXIT_CODE=%ERRORLEVEL%"
:finish
if not "%GUI_EXIT_CODE%"=="0" (
    echo.
    echo GUI startup failed or was cancelled. See .dev-gui\logs\launcher.log.
    if not defined ENDFIELD_GUI_NO_PAUSE pause
)
exit /b %GUI_EXIT_CODE%
