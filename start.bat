@echo off
cd /d "%~dp0"

:: Try to find Python
set PYTHON=
for %%p in (python python3) do (
    where %%p >nul 2>&1 && set PYTHON=%%p && goto :found
)

:: Fallback to known paths
for %%p in (
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
) do (
    if exist %%p (set PYTHON=%%p && goto :found)
)

echo Python not found!
pause
exit /b 1

:found
echo Starting FC3D Predict Scheduler...
%PYTHON% main.py schedule
