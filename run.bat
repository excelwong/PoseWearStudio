@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PoseWear Studio

set PY="C:\AI\ComfyUI-aki-v3\python\python.exe"
set COMFY_DIR="C:\AI\ComfyUI-aki-v3\ComfyUI"

echo.
echo  PoseWear Studio - checking local ComfyUI service...
%PY% -c "import urllib.request,sys; sys.exit(0 if urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8188/system_stats',timeout=3).status==200 else 1)" >nul 2>nul
if errorlevel 1 (
  echo  ComfyUI is not running. Starting it in a new window...
  start "ComfyUI" /D %COMFY_DIR% %PY% -s main.py --listen --port 8188 --use-ck-attention --reserve-vram 2 --cache-ram 12 60
  echo  Waiting 25 seconds for model backend to come up...
  timeout /t 25 /nobreak >nul
) else (
  echo  ComfyUI is online.
)

echo  Launching desktop app...
%PY% app.py
if errorlevel 1 (
  echo.
  echo  [ERROR] The app exited unexpectedly. See the message above.
  pause
)
