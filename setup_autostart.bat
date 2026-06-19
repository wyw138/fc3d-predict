@echo off
echo ========================================
echo  福彩3D 预测系统 - 开机自启配置
echo ========================================
echo.
echo 正在配置开机自启...

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set VBS_FILE="%~dp0start.vbs"

if not exist %VBS_FILE% (
    echo 错误: 找不到 start.vbs 文件
    pause
    exit /b 1
)

copy /Y %VBS_FILE% "%STARTUP_DIR%\FC3D_Predict.vbs" >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo.
    echo 配置成功!
    echo 下次开机时，预测系统会自动在后台启动。
    echo.
    echo 如需立即启动，请手动运行:
    echo   %~dp0start.vbs
) else (
    echo.
    echo 自动配置失败，请手动操作:
    echo   1. 右键 start.vbs ^> 创建快捷方式
    echo   2. Win+R ^> shell:startup ^> 回车
    echo   3. 将快捷方式粘贴进去
)

echo.
pause
