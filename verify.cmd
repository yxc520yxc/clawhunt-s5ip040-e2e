@echo off
REM S5-IP-040 一键复跑：真实 PostgreSQL + API E2E + Playwright E2E
REM 如需指定解释器，先 set PY=<python-with-requirements>（默认取 PATH 上的 python）
setlocal
cd /d "%~dp0"
if not defined PY set "PY=python"
if not defined E2E_PG_DSN set "E2E_PG_DSN=postgresql://postgres@127.0.0.1:55439/e2e2380"
if not defined E2E_PG_ADMIN_DSN set "E2E_PG_ADMIN_DSN=postgresql://postgres@127.0.0.1:55439/postgres"
REM 本机入口默认用已装的 Edge；CI/Docker 不要设此项，走 playwright install chromium 的 bundled 内核
if not defined PW_CHANNEL set "PW_CHANNEL=msedge"
"%PY%" run_all.py
exit /b %ERRORLEVEL%
