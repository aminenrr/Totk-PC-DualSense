@echo off
rem Ports a DualSense button-prompt mod onto this game (tools\port_ui_mod.py), on top of the 60 fps patches.
rem Usage: DualSense-UI.bat "<install folder>" "<the mod's romfs folder>"
rem Then in totk.ini, [files]: romfs_patches = <install folder>\romfs-patches-dualsense
setlocal
set "HERE=%~dp0"
if "%~2"=="" (
  echo Usage: DualSense-UI.bat "install folder" "mod romfs folder"
  exit /b 1
)
if not exist "%~1\logs" mkdir "%~1\logs"
"%HERE%python\python.exe" "%HERE%tools\port_ui_mod.py" --version v143 --romfs "%~1\romfs" --base "%~1\romfs-patches" --mod "%~2" --out "%~1\romfs-patches-dualsense" %3 %4 > "%~1\logs\dualsense-ui.json" 2>&1
set "CODE=%ERRORLEVEL%"
type "%~1\logs\dualsense-ui.json"
if not "%CODE%"=="0" echo FAILED, see %~1\logs\dualsense-ui.json
exit /b %CODE%
