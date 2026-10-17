@echo off
chcp 65001 >nul
title Kilo-ZCode 桥客户端
cd /d D:\zcode-workspace\ai
echo 正在启动 Kilo-ZCode 桥客户端，控制台地址 http://127.0.0.1:8791
echo 关闭本窗口即停止客户端。
node apps\bridge-client\server.mjs
pause
