@echo off
chcp 65001 >nul
title Kilo-ZCode 桥客户端（守护）
cd /d D:\zcode-workspace\ai
:loop
node apps\bridge-client\server.mjs
echo %date% %time% 客户端退出，5 秒后自动重启…
timeout /t 5 /nobreak >nul
goto loop
