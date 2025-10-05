# 🛫 Autopilot-Microcruiser-RC-Flugzeug

Begleitprojekt zur technischen Dokumentation  
**Autonomes Landeverfahren mit visueller Bahnerkennung und MAVLink-Autopilotsteuerung**

Dieses Repository enthält alle Skripte, Parameterdateien und Konfigurationen,  
die im Rahmen der Projektarbeit **„Autopilot für Microcruiser RC Flugzeug“** entwickelt und eingesetzt wurden.

---

## ⚙️ Systemübersicht

**Trägerplattform:**  
- [JTPaero – Microcruiser](https://aerojtp.com/s/aero-jtp/:Micro_Cruisers)  
- Spannweite: 460 mm  
- Antrieb: EDF (Electric Ducted Fan)  
- Steuerung: Quer-, Höhenruder, Gas  
- Missionsprofil: GPS-Navigation, autonomes Landeverfahren

**Autopilot: Pixracer R15 (ArduPlane 4.6.2)**  
- Zentrale Flugsteuerung (Lage, Mission, Sensorfusion)  
- MAVLink-Kommunikation mit CM4 (UART)  
- Unterstützt automatische Modi (AUTO, GUIDED, LAND)  
- Failsafe-Mechanismen und RC-Priorität aktiv

**Compute Module 4 (CM4):**  
- Raspberry Pi CM4 mit CSI-Kamera (IMX708)  
- Eigenes UBEC (5 V) für stabile Versorgung  
- Echtzeit-Bahnerkennung & Trigger des LAND-Modus über MAVLink  

---

## 📁 Projektstruktur

```text
Autopilot-Microcruiser-RC-Flugzeug/
│
├── 📘 README.md
│
├── 📂 scripts/
│   ├── autoland_trigger_on_land.py       ← Hauptskript (visuelle Landebahntriggerung)
│   └── Sensordaten_plott_und_excel.py    ← Auswertungsskript (.bin → HTML / Excel)
│
├── 📂 batch/
│   └── Datendownload.bat                 ← Automatischer Video- & Log-Download (Pi)
│
├── 📂 configs/
│   ├── microcruiser.xml                  ← Simulationsmodell (JSBSim)
│   └── reset_microcruiser.xml            ← Reset-Datei für Startbedingungen
│
├── 📂 params/
│   └── pixracer_autoland.param           ← Pixracer-Parameter (ArduPlane 4.6.2)
│
└── 📂 docs/
    └── Anhang_B_Autopilot_Microcruiser_final.pdf   ← Setup-, Parametrierungs- & Skriptanleitung
