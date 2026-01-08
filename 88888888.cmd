@echo off
setlocal
chcp 65001 >nul
title Hist4x4 超傻瓜网页版（SOCKS + PAC 代理支持）

REM 1) 检查 Python
where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python。请先安装 Python 3.9+ ：https://www.python.org/downloads/windows/
  pause
  exit /b
)

REM 2) 创建虚拟环境
if not exist .venv (
  echo [1/4] 创建虚拟环境 .venv ...
  python -m venv .venv
)

REM 3) 安装依赖（补齐 itsdangerous + pypac + socks）
echo [2/4] 升级 pip ...
call .venv\Scripts\python -m pip install -q --upgrade pip
echo [3/4] 安装依赖（fastapi uvicorn requests[socks] authlib pypac itsdangerous）...
call .venv\Scripts\pip install -q fastapi "uvicorn[standard]" requests[socks] authlib pypac itsdangerous

REM 4) 读取或设置 OpenAI Key
if "%OPENAI_API_KEY%"=="" (
  echo.
  set /p OPENAI_API_KEY=请输入 OpenAI API Key（输入后回车，不会回显）： 
  if not "%OPENAI_API_KEY%"=="" setx OPENAI_API_KEY "%OPENAI_API_KEY%" >nul
)

REM 5) 启动服务
echo.
echo [4/4] 启动服务（浏览器将打开 http://127.0.0.1:8000 ）...
start "" http://127.0.0.1:8000
call .venv\Scripts\uvicorn app_hist4x4_web:app --host 127.0.0.1 --port 8000
