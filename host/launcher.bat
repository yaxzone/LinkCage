@echo off
setlocal
set "HOST_DIR=%~dp0"
set "VENV_PY=%HOST_DIR%..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" "%HOST_DIR%launcher.py"
) else (
    python "%HOST_DIR%launcher.py"
)
