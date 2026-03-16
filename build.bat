@echo off
echo Building Laksefisk...

pyinstaller --onefile --windowed ^
    --name Laksefisk ^
    --hidden-import=win32timezone ^
    --collect-binaries pywin32 ^
    --distpath . ^
    gui.py

echo.
echo Done! Laksefisk.exe is in this folder.
pause
