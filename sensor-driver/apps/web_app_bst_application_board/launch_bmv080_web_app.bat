@echo off
REM Launch BMV080 web application (index.html) in default browser

setlocal

set "HTML_FILE=%~dp0index.html"

echo Launching BMV080 web app with default browser.
start "" "%HTML_FILE%"

endlocal
