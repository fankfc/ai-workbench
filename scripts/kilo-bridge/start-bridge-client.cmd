@echo off
chcp 65001 >nul
title 智能体协作桥
cd /d D:\zcode-workspace\ai
echo 正在启动智能体协作桥客户端，控制台地址 http://127.0.0.1:8791
echo 关闭本窗口即停止客户端。
node apps\bridge-client\server.mjs
pause
