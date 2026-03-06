@echo off
taskkill /IM *ClaudeCodeWrapper* /F 2>nul
taskkill /IM *Messenger* /F 2>nul
echo ClaudeCodeWrapper and Messenger have been closed.
pause
