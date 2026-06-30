@echo off
setlocal

cd /d "%~dp0.."
uv run copilot-proxy %*
