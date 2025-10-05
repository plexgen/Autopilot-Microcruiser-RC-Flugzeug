#  Anhang B – Software, Parametrierungen & Skripte

**Projektarbeit Abschluss 2025**  
**Teko Bern, HF Elektrotechnik**  
**Autor:** Jarno Linder  
**Oktober 2025**

---

## B.1 Laufzeitumgebung & Abhängigkeiten

Das Kamerasystem basiert auf einem **Raspberry Pi Compute Module 4 (CM4)** mit einer **CSI-Kamera Picam3 (IMX708)**.  
Die Bildverarbeitung und MAVLink-Kommunikation erfolgen in einer **Python 3.9** Umgebung.

| Komponente | Version / Paket |
|-------------|-----------------|
| Python      | 3.9             |
| OpenCV      | 4.8             |
| pymavlink   | 2.4             |
| numpy       | 1.24            |
| matplotlib  | 3.7             |
| pandas      | 2.0             |

---

## B.2 Start & Betrieb

Das Hauptskript **autoland_trigger_on_land.py** startet automatisch beim Systemstart über einen `systemd`-Service.  
Ein manueller Start ist nicht erforderlich.

**Systemd-Service-Konfiguration:**
```ini
[Unit]
Description=Autoland Trigger Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/autoland_trigger_on_land.py
WorkingDirectory=/home/pi
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

**Service aktivieren:**
```bash
sudo systemctl enable autoland_trigger.service
sudo systemctl start autoland_trigger.service
```

**Status prüfen:**
```bash
sudo systemctl status autoland_trigger.service
```

---

## B.3 Parameterübersicht (Pixracer R15 – ArduPlane 4.6.2)

Der Flugcontroller **Pixracer R15** nutzt die **ArduPlane-Firmware 4.6.2**.  
Zentrale Parameter zur Aktivierung und Ausführung des autonomen Landeverfahrens:

| Parameter        | Wert       | Beschreibung                       |
|------------------|-------------|------------------------------------|
| FLTMODE5         | 2 (AUTO)    | Automodus für Missionsflug         |
| RC7_OPTION       | 153         | Trigger für Landemodus             |
| RTL_AUTOLAND     | 2           | Automatische Landung bei RTL       |
| TKOFF_THR_DELAY  | 2           | Verzögerung Triebwerksstart        |
| LAND_FLARE_ALT   | 3.0         | Flare-Höhe (m)                     |
| TECS_LAND_SINK   | 0.25        | Sinkrate Landung (m/s)             |

---

## B.4 Algorithmische Kerne

Das Skript implementiert die visuelle Bahnerkennung und die Steuerungslogik für den Wechsel in den Landemodus:

- Initialisierung der MAVLink-Verbindung *(Zeile 20–60)*
- Kamera-Feed-Analyse & Bahnerkennung *(Zeile 90–180)*
- Trigger-Logik: Bedingung erfüllt → Mode Switch *(Zeile 190–210)*
- Logging & Bildspeicherung zur Nachweisführung *(Zeile 220–260)*

---

## B.5 Skriptübersicht

- `autoland_trigger_on_land.py` – Hauptskript für visuelle Landung  
- `Sensordaten_plott_und_excel.py` – Umwandlung `.bin` → HTML / Excel  
- `Datendownload.bat` – Automatischer Video / Log-Download vom CM4

---

## B.6 Systemübersicht

**Compute Module 4 (CM4):** Raspberry Pi mit CSI-Kamera (IMX708), separates UBEC (5 V)  
**Pixracer R15:** Autopilot mit ArduPlane 4.6.2  
**Kommunikation:** UART (MAVLink), CSI  
**Trägerplattform:** Microcruiser (JTPaero)

> Herstellerlink: [JTP Aero – Micro Cruiser](https://aerojtp.com/s/aero-jtp/:Micro_Cruisers)

---

## B.7 Test & Nachweise

Zur Validierung wurden Flüge mit aktiviertem **Autoland** durchgeführt.  
Die Logdaten (`.BIN`) und Videodaten liegen in den Unterordnern:

```
/logs/
/videos/
```

---
