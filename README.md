#  Autopilot-Microcruiser-RC-Flugzeug

Begleitprojekt zur technischen Dokumentation  
**Autonomes Landeverfahren mit visueller Bahnerkennung und MAVLink-Autopilotsteuerung**

Dieses Repository enthält alle Skripte, Parameterdateien und Konfigurationen,  
die im Rahmen der Projektarbeit **„Autopilot für Microcruiser RC Flugzeug“** entwickelt wurden.

---

##  Systemübersicht

**Trägerplattform:**  
- Hersteller: [JTPaero – Microcruiser](https://aerojtp.com/s/aero-jtp/:Micro_Cruisers)  
- Spannweite: 460 mm  
- Antrieb: EDF (Electric Ducted Fan)  
- Steuerung: Quer-, Höhenruder, Gas  
- Missionsprofil: Wegpunktflug & autonomes Landeverfahren  

**Autopilot: Pixracer R15 (ArduPlane 4.6.2)**  
- Zentrale Flugsteuerung für Lage, Navigation & Missionsmanagement  
- MAVLink-Kommunikation (UART) mit CM4  
- Unterstützte Flugmodi: `AUTO`, `GUIDED`, `LAND`  
- Empfangene Befehle:
  - `SET_MODE` – Wechsel Flugmodus  
  - `DO_LAND_START` – Start Autoland-Sequenz  
  - `SET_POSITION_TARGET_GLOBAL_INT` – Positionsvorgabe (z. B. Offset-Landung)  

**Compute Module 4 (CM4):**  
- Raspberry Pi CM4 mit **CSI-Kamera (IMX708)**  
- Eigenes 5 V-UBEC (getrennte Stromversorgung)  
- Echtzeit-Bahnerkennung über **Picamera2 + OpenCV**  
- MAVLink-Kommunikation mit Pixracer  
- Autonomer Trigger des LAND-Modus  

---

##  Projektstruktur

```text
Autopilot-Microcruiser-RC-Flugzeug/
│
├──  README.md
│
├── 📂 scripts/
│   ├── autoland_trigger_on_land.py       ← Hauptskript (visuelle Bahnerkennung & Trigger)
│   └── Sensordaten_plott_und_excel.py    ← Auswertungsskript (.bin → HTML / Excel)
│
├── 📂 batch/
│   └── Datendownload.bat                 ← Automatischer Video- & Log-Download (Raspberry Pi)
│
├── 📂 configs/
│   ├── microcruiser.xml                  ← Flugzeugmodell (JSBSim)
│   └── reset_microcruiser.xml            ← Reset-Parameter
│
├── 📂 params/
│   └── pixracer_autoland.param           ← Pixracer-Konfiguration (ArduPlane 4.6.2)
│
└── 📂 docs/
    ├── Anhang_B_Autopilot_Microcruiser_final.pdf   ← Begleitdokumentation (Setup, Parameter, Skripte)
    ├──📂 logs/                          ← Logdaten
    ├──📂 STL/                           ← Druckdateien Halter LIDAR und Kamera
    └──📂 videos/                        ← Videodateien 
