@echo off
REM ============================================================================
REM  Taller PDF - build the Windows .exe
REM  Run this on a WINDOWS machine (not on Linux/Mac). See README_WINDOWS.md.
REM ============================================================================
setlocal

echo.
echo [1/4] Building the frontend (requires Node.js + Yarn)...
pushd "%~dp0..\frontend"
call yarn install || goto :error
call yarn build || goto :error
popd

echo.
echo [2/4] Creating / using a Python virtual environment...
pushd "%~dp0..\backend"
if not exist ".venv" (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate || goto :error

echo.
echo [3/4] Installing backend + build dependencies...
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error
python -m pip install pyinstaller || goto :error

echo.
echo [4/4] Packaging with PyInstaller...
pyinstaller "..\packaging\taller_pdf.spec" --noconfirm || goto :error
popd

echo.
echo ============================================================================
echo  DONE. Your app is here:  backend\dist\TallerPDF\TallerPDF.exe
echo  Zip the whole "TallerPDF" folder to share it across the local network.
echo ============================================================================
echo.
goto :eof

:error
echo.
echo  BUILD FAILED. Check the message above.
exit /b 1
