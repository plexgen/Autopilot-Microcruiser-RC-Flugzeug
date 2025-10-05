# Autopilot-Microcruiser-RC-Flugzeug
Begleitprojekt zur technischen Dokumentation - Autopilot für Microcruiser RC Flugzeug

Dieses Repository enthält alle Skripte, Parameterdateien und Konfigurationen, die im Rahmen der Technischen Dokumentation zum **autonomen Landeverfahren mit visueller Bahnerkennung und MAVLink-Autopilotsteuerung** beschrieben sind.

Das System basiert auf einem **Raspberry Pi Compute Module 4 (CM4)** zur Bildverarbeitung, einem **Pixracer R15** als Flugsteuerung sowie einer **CSI-Kamera** zur Laufzeit-Erkennung der Landebahn.

---

## 📘 Übersicht

| Kategorie              | Inhalt / Datei | Beschreibung |
|------------------------|----------------|---------------|
| 📂 `scripts/`          | [`autoland_trigger_on_land_objektorientiert.py`](scripts/autoland_trigger_on_land.py) | Hauptskript zur autonomen Triggerung des Landemodus bei erkannter Bahn |
|                        | [`Sensordaten_plott_und_excel.py`](scripts/Sensordaten_plott_und_excel.py) | Auswertungsskript (BIN → HTML + Excel-Export) |
| 📂 `batch/`            | [`Datendownload.bat`](batch/Datendownload.bat) | Automatischer Video- und Log-Download vom Raspberry Pi |
| 📂 `configs/`          | [`microcruiser.xml`](configs/microcruiser.xml) | Fahrzeugkonfiguration |
|                        | [`reset_microcruiser.xml`](configs/reset_microcruiser.xml) | Reset-Konfiguration |
| 📂 `params/`           | [`pixracer_autoland.param`](params/pixracer_autoland.param) | Pixracer-Parameterdatei (ArduPlane 4.6.2) |
| 📂 `docs/`             | `Anhang_B_Autopilot_Microcruiser_final.pdf` | Begleitdokumentation (Anhang B – Software & Parametrierungen) |

---

## ⚙️ Systemübersicht

**Komponenten:**
- Raspberry Pi CM4 (Compute Module 4)  
- Pixracer R15 (ArduPlane 4.6.2)  
- CSI-Kamera (IMX708)  
- Eigenes UBEC (5 V) für CM4  

**Kommunikation:**
- UART (MAVLink) zwischen CM4 ↔ Pixracer  
- CSI-Schnittstelle für Kamera  

**Funktion:**
- Visuelle Bahnerkennung in Echtzeit  
- Autonomer Wechsel in Landemodus  
- Log- und Videodokumentation zur Nachweisführung  

---

## 🚀 Verwendung

### 1. CM4 Setup
> Siehe Abschnitt **B.x.1** der Technischen Dokumentation  
> *(Anhang_B_Autopilot_Microcruiser_final.pdf)*

### 2. Skript-Start
```bash
source ~/mavenv/bin/activate
python3 autoland_trigger_on_land.py
