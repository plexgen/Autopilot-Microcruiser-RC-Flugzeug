@echo off
setlocal ENABLEDELAYEDEXPANSION

echo Willkommen
echo Sie haben sich entschieden mein Projekt "Autopilot zu Microcruiser" anzuschauen.
echo Die 3d Druckdaten koennen Sie auf https://aerojtp.com/s/aero-jtp/:Micro_Cruisers kaeuflich erwerben.
echo Diese Batch Datei laedt die Videodaten des CM4 herunter.
echo Dazu werden IP-Adresse, Benutzername und Passwort des Raspberry Pi benoetigt.

REM --- Pruefen, ob scp und ssh installiert sind
where scp >nul 2>&1 || (echo [Fehler] scp fehlt. Installiere OpenSSH-Client. & pause & exit /b 1)
where ssh >nul 2>&1 || (echo [Fehler] ssh fehlt. Installiere OpenSSH-Client. & pause & exit /b 1)

REM --- Standardwerte fuer Benutzername und Verzeichnis auf dem Pi
set "DEFAULT_USER=pi"
set "DEFAULT_REMOTE_DIR=/home/pi/Videos"

REM --- Eingaben vom Nutzer abfragen
echo.
set /p PI_IP=IP des Raspberry Pi (z.B. 192.168.0.36): 
if "%PI_IP%"=="" goto END_FAIL

set /p PI_USER=Benutzer [Enter=%DEFAULT_USER%]: 
if "%PI_USER%"=="" set "PI_USER=%DEFAULT_USER%"

set /p REMOTE_DIR=Remote-Verzeichnis [Enter=%DEFAULT_REMOTE_DIR%]: 
if "%REMOTE_DIR%"=="" set "REMOTE_DIR=%DEFAULT_REMOTE_DIR%"

set /p DEST_DIR=Zielordner auf diesem PC (z.B. C:\Users\Du\Videos): 
if "%DEST_DIR%"=="" goto END_FAIL

REM --- Zielordner auf dem PC anlegen, falls er nicht existiert
if not exist "%DEST_DIR%" (
  mkdir "%DEST_DIR%" || (echo [Fehler] Zielordner konnte nicht erstellt werden. & goto END)
)

REM --- Nur Passwort-Anmeldung erlauben, keine Schluessel
set "SSH_OPTS=-o PreferredAuthentications=password -o PubkeyAuthentication=no -o IdentitiesOnly=yes"

echo.
echo Lade Dateien von %PI_USER%@%PI_IP%:%REMOTE_DIR% nach "%DEST_DIR%"
echo Beim ersten Verbindungsaufbau muss der Host-Schluessel akzeptiert werden.
echo Danach erfolgt die Passwortabfrage.
echo.

REM --- Dateien vom Pi auf den PC kopieren
scp -r -p -o StrictHostKeyChecking=accept-new %SSH_OPTS% %PI_USER%@%PI_IP%:"%REMOTE_DIR%"/* "%DEST_DIR%\."
set ERR=%ERRORLEVEL%
echo scp ErrorLevel=%ERR%
echo.

REM --- Fehlerbehandlung beim Kopieren
if %ERR% GEQ 1 (
  echo [FEHLER] Transfer fehlgeschlagen – nichts wird geloescht.
  goto END
)

echo [OK] Dateien erfolgreich kopiert nach: "%DEST_DIR%"
echo.

REM --- Nach dem Kopieren optional Dateien auf dem Pi loeschen
set /p DELCONF=Moechten Sie die Quelldateien auf dem Pi loeschen? (j/n): 
if /I "%DELCONF%"=="j" (
  echo [INFO] Loesche Dateien auf dem Pi in %REMOTE_DIR% ...
  ssh %SSH_OPTS% %PI_USER%@%PI_IP% "rm -rf %REMOTE_DIR%/*"
  if errorlevel 1 (
    echo [WARN] Loeschen fehlgeschlagen. Bitte manuell pruefen.
  ) else (
    echo [OK] Ordner auf dem Pi geleert.
  )
) else (
  echo [INFO] Dateien bleiben auf dem Pi erhalten.
)

goto END

:END_FAIL
echo.
echo [Abbruch] Es wurden nicht alle Eingaben gemacht.

:END
echo.
pause
endlocal
