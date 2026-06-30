@echo off
setlocal

cd /d "%~dp0.."
uv run cpx start %*
