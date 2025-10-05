# 📘 Anhang B – Software, Parametrierungen & Skripte

**Projektarbeit Abschluss 2025**  
**Teko Bern, HF Elektrotechnik**  
**Autor:** Jarno Linder  
**Oktober 2025**

---

## B.1 Laufzeitumgebung & Abhängigkeiten

Das Kamerasystem basiert auf einem **Raspberry Pi Compute Module 4 (CM4)** mit einer **CSI-Kamera (IMX708)**.  
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
