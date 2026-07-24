@echo off
:: This script runs main.py for the bioprint-gen project.
:: Double-click this file to launch it - no need to open cmd manually.

:: Move into the project folder so the script can find its files
cd /d "C:\...\bioprint-gen-main"

:: Run the Python script
python main.py

:: Keep the window open after the script finishes so you can read the output
pause
