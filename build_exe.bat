@echo off
chcp 65001 >nul
echo 正在打包计球器...
pip install pyinstaller -q
pyinstaller --onefile --windowed --name "计球器" --clean main.py
echo.
echo 完成！exe 位于 dist\计球器.exe
pause
