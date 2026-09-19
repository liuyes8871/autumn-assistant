@echo off
setlocal
node "%~dp0scripts\start-autumn-assistant.mjs"
if errorlevel 1 pause
