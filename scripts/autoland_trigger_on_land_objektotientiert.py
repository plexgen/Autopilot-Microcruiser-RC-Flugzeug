#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==============================================================================
# AUTONOMES KAMERASYSTEM – MICROCRUISER (CM4 + PIXRACER R15 + PI CAMERA MODULE 3)
# ==============================================================================
# Hinweise zur Plattform:
#  - Luftfahrzeug: MicroCruiser (jtpaero.com)
#  - Flugcontroller: Pixracer R15 (MAVLink), Bodenstation: QGroundControl
#  - Kamera: Raspberry Pi Compute Module 4 + Raspberry Pi Camera Module 3 (Picamera2)
#
# Zweck dieses Skripts:
#  - Videoaufzeichnung (zeit-/ereignisbasierte Segmentierung)
#  - Einfache segmentierungsbasierte Landebahn-Erkennung (weiß/grün, Geometrie, Ringtest)
#  - Kleine Lande-Logik: LOITER -> optionaler GUIDED-Offset -> AUTO + DO_LAND_START
# ==============================================================================

import os, time, math
from datetime import datetime

import numpy as np
import cv2
from picamera2 import Picamera2
from libcamera import controls              # Fokus-Steuerung für Camera Module 3
from pymavlink import mavutil

# ==============================================================================
# KONFIGURATION
# ==============================================================================

SERIAL_DEV = "/dev/serial0"                 # Pixracer R15 via UART (CM4-IO-Board); QGC als GCS
BAUD = 115200                               # ggf. 57600 / 921600 je nach Telemetrie; hier konservativ
SAVE_DIR_VID = "/home/pi/Videos"            # Speicherpfad auf dem CM4

FRAME_SIZE = (1280, 720)                    # Aufnahmegröße (W,H). Muss zur Kamera passen
FPS = 30                                    # Bildrate
PROC_WIDTH = 640                             # Verarbeitungsbreite (Downscale spart CPU)
PROC_HEIGHT = int(PROC_WIDTH * FRAME_SIZE[1] / FRAME_SIZE[0])

PRIMARY_CODEC = ("mp4v", ".mp4")            # bevorzugt MP4 (mp4v)
FALLBACK_CODEC = ("MJPG", ".avi")           # Fallback, falls MP4 nicht geht

SEGMENT_SECONDS = 15.0                      # Länge pro Segment (zeitbasiert)
ROTATE_ON_EVENTS = True                     # bei Ereignissen eigene Segmente schneiden (z. B. Landestart/-ende)

# HSV-Standard-Schwellen
DEFAULT_WHITE_LOW  = np.array([0,   0, 180])   # Weiß: geringe Sättigung, hohe Helligkeit
DEFAULT_WHITE_HIGH = np.array([179, 60, 255])
DEFAULT_GREEN_LOW  = np.array([45,  60,  40])  # Grünbereich „um 60°“, genug S/V
DEFAULT_GREEN_HIGH = np.array([85, 255, 255])
DEFAULT_GRAY_LOW  = np.array([0,  0,  60], dtype=np.uint8)   # dunkles bis mittleres Grau
DEFAULT_GRAY_HIGH = np.array([179, 40, 200], dtype=np.uint8)
MIN_GRAY_RATIO = 0.35  # Startwert; ggf. 0.30–0.40 testen

# Geometrie/Validierung der Bahn
MIN_WHITE_AREA = 500
ASPECT_MIN = 3
ANGLE_TOL_DEG = 60

# Ringtest-Parameter
SCALE_RING_BY_TARGET = True
RING_OUTER_PX = 15
RING_INNER_PX = 7
RING_SCALE_OUTER = 0.20
RING_INNER_RATIO = 0.45
MIN_GREEN_RATIO = 0.25

# Auto-Kalibrierung (kann helfen bei Lichtwechseln; abschaltbar)
ENABLE_CALIBRATION = True
CALIBRATION_FRAMES = 25
CALIBRATION_TIMEOUT_SEC = 4.0
CAL_WHITE_V_MIN_CLAMP = (180, 240)
CAL_WHITE_S_MAX_CLAMP = (20,  80)
CAL_GREEN_H_WIDTH    = 20
CAL_GREEN_S_MIN_CLAMP = (40, 120)
CAL_GREEN_V_MIN_CLAMP = (30, 120)

# Missions-/Lande-Logik
SEARCH_WINDOW_SEC = 60
OFFSET_METERS = 300
LOITER_SECONDS = 15
DO_GUIDED_OFFSET = True


# ==============================================================================
# HILFSFUNKTIONEN
# ==============================================================================

# -----------------------------------------------------------------------------
# HILFSFUNKTION: _odd_int
# -----------------------------------------------------------------------------
# Liefert eine UNGERADE Ganzzahl innerhalb eines sinnvollen Bereichs [min_val, max_val].
# Warum ungerade?
# - Morphologische Operationen (Erosion, Dilatation, Öffnen, Schließen) nutzen
#   ein Strukturelement (Kernel) mit einem Ankerpunkt in der Mitte.
# - Nur bei UNGERADEN Kantenlängen (3,5,7,...) gibt es eine eindeutige Mitte.
#   Das verhindert einen Richtungs-Bias / Pixel-Shift.
# Warum begrenzen?
# - min_val (typisch >= 3) verhindert triviale Kerne wie 1x1 (macht quasi nichts).
# - max_val schützt Performance (sehr große Kerne sind extrem langsam).
# Ergebnis:
# - Stets „gut zentrierte“ Kernelgrößen für z. B. cv2.getStructuringElement(...).
# -----------------------------------------------------------------------------
def _odd_int(n, min_val=3, max_val=255):
    """
    Gibt eine ungerade Ganzzahl im Bereich [min_val, max_val] zurück.
    Wichtig für Morphologie-Kernel (z. B. cv2.MORPH_ELLIPSE), damit der
    Ankerpunkt exakt in der Mitte liegt und keine Verschiebungen entstehen.
    """
    n = int(max(min_val, min(max_val, round(n))))
    if n % 2 == 1:
        return n
    return n + 1 if n + 1 <= max_val else n - 1


# -----------------------------------------------------------------------------
# HILFSFUNKTION: dest_from
# -----------------------------------------------------------------------------
# Berechnet eine Zielkoordinate (Latitude, Longitude) ausgehend von einem
# Startpunkt (lat, lon), einer Richtung (heading in Grad, 0°=Nord, 90°=Ost)
# und einer Distanz (in Metern). Verwendet ein Kugelmodell der Erde (WGS-84),
# was für Distanzen im Bereich einiger 100 m völlig ausreicht.
# Rückgabe: (lat_out_deg, lon_out_deg)
# -----------------------------------------------------------------------------
def dest_from(lat, lon, heading_deg, distance_m):
    """
    Liefert Zielkoordinate (lat, lon) aus Startpunkt, Kurs (Grad) und Strecke (Meter).
    Kugelradius R=6 378 137 m (WGS-84).
    """
    R = 6378137.0
    brng = math.radians(heading_deg)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    lat_out = math.asin(math.sin(lat_rad) * math.cos(distance_m / R) + math.cos(lat_rad) * math.sin(distance_m / R) * math.cos(brng))
    lon_out = lon_rad + math.atan2(math.sin(brng) * math.sin(distance_m / R) * math.cos(lat_rad), math.cos(distance_m / R) - math.sin(lat_rad) * math.sin(lat_out))
    return math.degrees(lat_out), math.degrees(lon_out)


# ==============================================================================
# KOMPONENTEN
# ==============================================================================

class VideoRecorder:
    # -----------------------------------------------------------------------------
    # KLASSE: VideoRecorder
    # -----------------------------------------------------------------------------
    # Zuständigkeit:
    # - Kamera-Initialisierung (Picamera2, RGB888), optional AF beim Pi Camera Module 3
    # - Videoaufnahme starten/stoppen und zeit-/ereignisbasiert segmentieren
    # - MP4-Dateien sauber abschließen (writer.release + os.sync)
    # Hinweise:
    # - Vor dem Schreiben nach BGR konvertieren (OpenCV erwartet BGR).
    # -----------------------------------------------------------------------------

    # -----------------------------------------------------------------------------
    # METHODE: __init__
    # -----------------------------------------------------------------------------
    # Legt Zielpfad an, setzt Codec-Präferenzen, initiale Segmentzeit und Kamera-Handle.
    # -----------------------------------------------------------------------------
    def __init__(self):
        self.save_dir = SAVE_DIR_VID
        self.writer = None
        self.primary_codec = PRIMARY_CODEC
        self.fallback_codec = FALLBACK_CODEC
        os.makedirs(self.save_dir, exist_ok=True)
        self.last_segment_time = time.time()
        self.cam = None

    # -----------------------------------------------------------------------------
    # METHODE: _open_writer
    # -----------------------------------------------------------------------------
    # Öffnet einen OpenCV-VideoWriter mit gewünschtem FourCC.
    # Parameter:
    #   - path  : Ausgabepfad inkl. Endung
    #   - codec : FourCC-String (z. B. "mp4v", "MJPG")
    # -----------------------------------------------------------------------------
    def _open_writer(self, path, codec):
        fourcc = cv2.VideoWriter_fourcc(*codec)
        return cv2.VideoWriter(path, fourcc, FPS, FRAME_SIZE)

    # -----------------------------------------------------------------------------
    # METHODE: start_camera
    # -----------------------------------------------------------------------------
    # Initialisiert Picamera2 (RGB888). Versucht beim Camera Module 3 einen
    # kontinuierlichen Autofokus (Continuous/Fast). Bei Fehlern wird nur geloggt.
    # Rückgabe: True/False.
    # -----------------------------------------------------------------------------
    def start_camera(self):
        try:
            self.cam = Picamera2()
            config = self.cam.create_video_configuration(main={"size": FRAME_SIZE, "format": "RGB888"})
            self.cam.configure(config)
            try:
                self.cam.set_controls({"AfMode": controls.AfModeEnum.Continuous, "AfSpeed": controls.AfSpeedEnum.Fast})
                print("[CAM] Autofokus CM3: Continuous/Fast gesetzt.")
            except Exception as af_err:
                print("[CAM] AF optional, konnte nicht gesetzt werden:", af_err)
            self.cam.start()
            print("[CAM] Kamera gestartet.")
            return True
        except Exception as e:
            print("[ERROR] Kamera konnte nicht gestartet werden:", e)
            return False

    # -----------------------------------------------------------------------------
    # METHODE: start_recording
    # -----------------------------------------------------------------------------
    # Öffnet den Writer. Erst MP4 (mp4v), bei Fehlschlag Fallback auf AVI (MJPG).
    # Rückgabe: True/False.
    # -----------------------------------------------------------------------------
    def start_recording(self, base_name):
        path = os.path.join(self.save_dir, base_name + self.primary_codec[1])
        self.writer = self._open_writer(path, self.primary_codec[0])
        if not self.writer.isOpened():
            print("[INFO] MP4 ging nicht, versuche AVI/MJPG...")
            path = os.path.join(self.save_dir, base_name + self.fallback_codec[1])
            self.writer = self._open_writer(path, self.fallback_codec[0])

        if self.writer.isOpened():
            print("[REC] Aufnahme gestartet:", path)
            self.last_segment_time = time.time()
            return True
        else:
            print("[ERROR] VideoWriter konnte nicht gestartet werden :(")
            return False

    # -----------------------------------------------------------------------------
    # METHODE: cut_segment
    # -----------------------------------------------------------------------------
    # Beendet das aktuelle Segment (release + os.sync) und startet sofort ein neues.
    # Der neue Dateiname bekommt einen Zeitstempel und optional einen Ereignis-Tag.
    # -----------------------------------------------------------------------------
    def cut_segment(self, new_base_name, tag=None):
        if self.writer:
            self.writer.release()
            os.sync()   # MP4 sauber finalisieren
            print("[REC] Segment beendet.")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{new_base_name}_{ts}" + (f"_{tag}" if tag else "")
        self.start_recording(new_name)
        self.last_segment_time = time.time()

    # -----------------------------------------------------------------------------
    # METHODE: stop_recording
    # -----------------------------------------------------------------------------
    # Stoppt die Aufnahme, gibt den Writer frei und ruft os.sync() auf, damit
    # Dateipuffer zuverlässig geschrieben sind (MP4-Container).
    # -----------------------------------------------------------------------------
    def stop_recording(self):
        if self.writer:
            self.writer.release()
            os.sync()
            print("[REC] Aufnahme gestoppt.")

    # -----------------------------------------------------------------------------
    # METHODE: get_frame
    # -----------------------------------------------------------------------------
    # Liefert ein RGB-Frame (NumPy-Array) der Kamera. Gibt None zurück,
    # falls noch kein Frame verfügbar ist.
    # -----------------------------------------------------------------------------
    def get_frame(self):
        if self.cam:
            return self.cam.capture_array()
        return None


class MavlinkClient:
    # -----------------------------------------------------------------------------
    # KLASSE: MavlinkClient
    # -----------------------------------------------------------------------------
    # Zuständig für:
    # - Aufbau MAVLink-Verbindung (seriell) und Heartbeat
    # - Missionsdownload (REQUEST_LIST → COUNT → ITEM[_INT])
    # - Missionsfortschritt (MISSION_CURRENT)
    # - Kommandos: Mode-Wechsel, DO_LAND_START, GOTO (SET_POSITION_TARGET_GLOBAL_INT)
    # QGroundControl-kompatibel.
    # -----------------------------------------------------------------------------

    # -----------------------------------------------------------------------------
    # METHODE: __init__
    # -----------------------------------------------------------------------------
    # Speichert Schnittstellenparameter, setzt interne Statusfelder (Verbindung,
    # aktuelle Seq, Missionsliste) auf Startwerte.
    # -----------------------------------------------------------------------------
    def __init__(self, device, baud):
        self.device = device
        self.baud = baud
        self.conn = None
        self.is_connected = False
        self.current_seq = -1
        self.mission_waypoints = []

    # -----------------------------------------------------------------------------
    # METHODE: connect
    # -----------------------------------------------------------------------------
    # Baut die MAVLink-Verbindung auf und wartet auf Heartbeat.
    # Rückgabe: True/False.
    # -----------------------------------------------------------------------------
    def connect(self):
        try:
            self.conn = mavutil.mavlink_connection(self.device, baud=self.baud)
            self.conn.wait_heartbeat(timeout=10)
            print(f"[MAV] Verbunden: sys={self.conn.target_system} comp={self.conn.target_component}")
            self.is_connected = True
            return True
        except Exception as err_info:
            print("[WARN] MAVLink nicht verbunden:", err_info)
            self.conn = None
            self.is_connected = False
            return False

    # -----------------------------------------------------------------------------
    # METHODE: update_state
    # -----------------------------------------------------------------------------
    # Liest nicht-blockierend MISSION_CURRENT (und HEARTBEAT, ohne weitere Auswertung),
    # um die aktuelle Missions-Sequenznummer zu verfolgen.
    # -----------------------------------------------------------------------------
    def update_state(self):
        if not self.is_connected:
            return
        msg = self.conn.recv_match(type=['MISSION_CURRENT', 'HEARTBEAT'], blocking=False)
        if msg and msg.get_type() == 'MISSION_CURRENT':
            try:
                self.current_seq = int(msg.seq)
            except Exception:
                pass

    # -----------------------------------------------------------------------------
    # METHODE: download_mission
    # -----------------------------------------------------------------------------
    # Lädt die Mission vollständig in self.mission_waypoints:
    # 1) waypoint_request_list_send()
    # 2) MISSION_COUNT abwarten
    # 3) Für jedes Item mission_request_int_send() → MISSION_ITEM(_INT) empfangen
    # Rückgabe: Liste der Wegpunkte.
    # -----------------------------------------------------------------------------
    def download_mission(self):
        if not self.is_connected:
            return []

        try:
            self.conn.waypoint_request_list_send()
        except Exception as e:
            print("[MAV] REQUEST_LIST fehlgeschlagen:", e)
            self.mission_waypoints = []
            return []

        msg = self.conn.recv_match(type='MISSION_COUNT', blocking=True, timeout=3)
        if not msg:
            print("[MAV] Keine MISSION_COUNT erhalten.")
            self.mission_waypoints = []
            return []

        count = int(msg.count)
        loader = mavutil.mavwp.MAVWPLoader()
        for i in range(count):
            try:
                self.conn.mav.mission_request_int_send(self.conn.target_system, self.conn.target_component, i)
            except Exception:
                pass
            item = self.conn.recv_match(type=['MISSION_ITEM_INT', 'MISSION_ITEM'], blocking=True, timeout=3)
            if not item:
                print(f"[MAV] Timeout bei MISSION_ITEM {i}")
                break
            loader.add(item)

        self.mission_waypoints = [loader.wp(i) for i in range(loader.count())]
        print(f"[MAV] Mission geladen, WPs: {len(self.mission_waypoints)}")
        return self.mission_waypoints

    # -----------------------------------------------------------------------------
    # METHODE: autodetect_trigger_wp
    # -----------------------------------------------------------------------------
    # Sucht den Wegpunkt direkt VOR dem ersten NAV_LAND. Dieser dient als
    # "Trigger" zum Start des visuellen Suchfensters.
    # Rückgabe: seq (int) oder None.
    # -----------------------------------------------------------------------------
    def autodetect_trigger_wp(self):
        self.download_mission()
        if not self.mission_waypoints:
            return None
        for i, wp in enumerate(self.mission_waypoints):
            cmd = getattr(wp, 'command', None)
            if cmd == mavutil.mavlink.MAV_CMD_NAV_LAND and i > 0:
                seq = getattr(self.mission_waypoints[i-1], 'seq', i-1)
                print("[MAV] Trigger-WP:", seq)
                return seq
        return None

    # -----------------------------------------------------------------------------
    # METHODE: _mode_mapping
    # -----------------------------------------------------------------------------
    # Liefert ein Mapping Modusname → Modus-ID (Pixracer/ArduPilot unterscheiden sich).
    # Erst conn.mode_mapping(), dann conn.mode_mapping_ardupilot() als Fallback.
    # -----------------------------------------------------------------------------
    def _mode_mapping(self):
        mapping = {}
        try:
            mapping = self.conn.mode_mapping() or {}
        except Exception:
            pass
        if not mapping:
            try:
                mapping = self.conn.mode_mapping_ardupilot() or {}
            except Exception:
                mapping = {}
        return mapping

    # -----------------------------------------------------------------------------
    # METHODE: set_mode
    # -----------------------------------------------------------------------------
    # Fordert einen Mode-Wechsel an (z. B. 'AUTO', 'GUIDED', 'LOITER').
    # Funktioniert nur bei aktiver Verbindung und bekanntem Modus.
    # -----------------------------------------------------------------------------
    def set_mode(self, mode_name):
        if not self.is_connected:
            return
        mapping = self._mode_mapping()
        if mode_name not in mapping:
            print(f"[MAV] Modus unbekannt: {mode_name}")
            return
        self.conn.mav.set_mode_send(self.conn.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mapping[mode_name])
        print(f"[MAV] Modus -> {mode_name}")

    # -----------------------------------------------------------------------------
    # METHODE: do_land_start
    # -----------------------------------------------------------------------------
    # Sendet MAV_CMD_DO_LAND_START, um den autonomen Landevorgang zu initiieren.
    # -----------------------------------------------------------------------------
    def do_land_start(self):
        if not self.is_connected:
            return
        self.conn.mav.command_long_send(self.conn.target_system, self.conn.target_component,
                                        mavutil.mavlink.MAV_CMD_DO_LAND_START, 0, 0,0,0,0,0,0,0)
        print("[MAV] DO_LAND_START gesendet.")

    # -----------------------------------------------------------------------------
    # METHODE: get_current_pos_and_heading
    # -----------------------------------------------------------------------------
    # Liest GLOBAL_POSITION_INT (bis 1s). Rückgabe:
    #   ((lat, lon, alt_rel), heading_deg) oder (None, None)
    # heading in Grad (0..360), alt_rel in m relativ zu Home.
    # -----------------------------------------------------------------------------
    def get_current_pos_and_heading(self):
        if not self.is_connected:
            return None, None
        msg = self.conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True, timeout=1)
        if msg:
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.relative_alt / 1e3
            hdg = (msg.hdg / 100.0) if getattr(msg, 'hdg', None) is not None else None
            return (lat, lon, alt), hdg
        return None, None

    # -----------------------------------------------------------------------------
    # METHODE: goto_global_pos
    # -----------------------------------------------------------------------------
    # Setzt ein Positionsziel via SET_POSITION_TARGET_GLOBAL_INT (nur Position,
    # Geschwindigkeiten/Beschleunigungen/Yaw werden ignoriert).
    # Frame: GLOBAL_RELATIVE_ALT_INT.
    # -----------------------------------------------------------------------------
    def goto_global_pos(self, lat_deg, lon_deg, alt_m):
        if not self.is_connected:
            return
        frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        mask = (mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE)
        try:
            self.conn.mav.set_position_target_global_int_send(int(round(time.time()*1000)), self.conn.target_system, self.conn.target_component,
                                                              frame, mask, int(lat_deg*1e7), int(lon_deg*1e7), float(alt_m),
                                                              0,0,0, 0,0,0, 0,0)
            print(f"[MAV] GOTO: {lat_deg:.7f}, {lon_deg:.7f}, alt={alt_m:.1f}")
        except Exception as e:
            print("[MAV] Fehler GOTO:", e)


class RunwayDetector:
    # -----------------------------------------------------------------------------
    # KLASSE: RunwayDetector
    # -----------------------------------------------------------------------------
    # Führt die Bildverarbeitung zur Landebahn-Erkennung aus:
    # - Resize & RGB→HSV
    # - Segmentierung: Weiß (Bahn) + Grün (Umfeld)
    # - Morphologie (Öffnen/Schließen), größte Kontur
    # - Geometrieprüfungen (Fläche, Seitenverhältnis, Winkel)
    # - Ringtest (Grünanteil im Umfeld)
    # Optional: heuristische Auto-Kalibrierung und adaptive Ringgrößen.
    # -----------------------------------------------------------------------------

    # -----------------------------------------------------------------------------
    # METHODE: __init__
    # -----------------------------------------------------------------------------
    # Setzt Verarbeitungsgröße und initiale (kopierte) HSV-Schwellen.
    # -----------------------------------------------------------------------------
    def __init__(self, proc_width):
        self.proc_width = proc_width
        self.proc_height = int(proc_width * FRAME_SIZE[1] / FRAME_SIZE[0])
        self.white_low  = DEFAULT_WHITE_LOW.copy()
        self.white_high = DEFAULT_WHITE_HIGH.copy()
        self.green_low  = DEFAULT_GREEN_LOW.copy()
        self.green_high = DEFAULT_GREEN_HIGH.copy()

    # -----------------------------------------------------------------------------
    # METHODE: calibrate
    # -----------------------------------------------------------------------------
    # Führt eine einfache, zeitlich begrenzte Auto-Kalibrierung durch:
    # - Schätzt Weiß-Grenzen (V_min, S_max) aus Perzentilen.
    # - Schätzt Grün-Grenzen (H-Fenster um Median ± Breite, S_min, V_min).
    # - Clampt die Werte in sinnvolle Bereiche, um Ausreißer zu vermeiden.
    # -----------------------------------------------------------------------------
    def calibrate(self, get_frame, frames=CALIBRATION_FRAMES, timeout=CALIBRATION_TIMEOUT_SEC):
        if not ENABLE_CALIBRATION:
            print("[CAL] aus (skipped).")
            return

        print(f"[CAL] versuche kalibrierung mit bis zu {frames} frames (timeout {timeout}s)...")
        t0 = time.time()
        white_S, white_V, green_H, green_S, green_V = [], [], [], [], []
        got = 0
        while got < frames and (time.time() - t0) < timeout:
            frame = get_frame()
            if frame is None:
                time.sleep(0.02); continue
            hsv = cv2.cvtColor(cv2.resize(frame, (self.proc_width, self.proc_height)), cv2.COLOR_RGB2HSV)
            H = hsv[:,:,0].astype(np.int16); S = hsv[:,:,1].astype(np.int16); V = hsv[:,:,2].astype(np.int16)

            wm = (V >= np.percentile(V, 75)) & (S <= np.percentile(S, 55))
            gm = (H >= 35) & (H <= 85) & (S >= 60) & (V >= 40)

            if wm.any():
                ws = S[wm]; wv = V[wm]
                if ws.size > 30000:
                    idx = np.random.choice(ws.size, 30000, replace=False)
                    ws = ws[idx]; wv = wv[idx]
                white_S.append(ws); white_V.append(wv)

            if gm.any():
                gh = H[gm]; gs = S[gm]; gv = V[gm]
                if gh.size > 30000:
                    idx = np.random.choice(gh.size, 30000, replace=False)
                    gh = gh[idx]; gs = gs[idx]; gv = gv[idx]
                green_H.append(gh); green_S.append(gs); green_V.append(gv)

            got += 1

        def _cat(lst):
            return np.concatenate(lst) if lst else np.array([], dtype=np.int16)

        white_S = _cat(white_S); white_V = _cat(white_V)
        green_H = _cat(green_H); green_S = _cat(green_S); green_V = _cat(green_V)

        if white_V.size > 1000:
            v80 = int(np.percentile(white_V, 80)); v_min = max(CAL_WHITE_V_MIN_CLAMP[0], min(CAL_WHITE_V_MIN_CLAMP[1], v80 - 5))
        else:
            v_min = int(DEFAULT_WHITE_LOW[2])
        if white_S.size > 1000:
            s50 = int(np.percentile(white_S, 50)); s_max = max(CAL_WHITE_S_MAX_CLAMP[0], min(CAL_WHITE_S_MAX_CLAMP[1], s50 + 10))
        else:
            s_max = int(DEFAULT_WHITE_HIGH[1])

        if green_H.size > 1000:
            h_med = int(np.median(green_H)); h_lo = max(0, h_med - CAL_GREEN_H_WIDTH); h_hi = min(179, h_med + CAL_GREEN_H_WIDTH)
        else:
            h_lo, h_hi = int(DEFAULT_GREEN_LOW[0]), int(DEFAULT_GREEN_HIGH[0])
        if green_S.size > 1000:
            s40 = int(np.percentile(green_S, 40)); g_s_min = max(CAL_GREEN_S_MIN_CLAMP[0], min(CAL_GREEN_S_MIN_CLAMP[1], s40))
        else:
            g_s_min = int(DEFAULT_GREEN_LOW[1])
        if green_V.size > 1000:
            v30 = int(np.percentile(green_V, 30)); g_v_min = max(CAL_GREEN_V_MIN_CLAMP[0], min(CAL_GREEN_V_MIN_CLAMP[1], v30))
        else:
            g_v_min = int(DEFAULT_GREEN_LOW[2])

        self.white_low  = np.array([0, 0, v_min], dtype=np.uint8)
        self.white_high = np.array([179, s_max, 255], dtype=np.uint8)
        self.green_low  = np.array([h_lo, g_s_min, g_v_min], dtype=np.uint8)
        self.green_high = np.array([min(179, h_hi), 255, 255], dtype=np.uint8)

        print("[CAL] Weiß LOW/HIGH:", self.white_low.tolist(), self.white_high.tolist())
        print("[CAL] Grün LOW/HIGH:", self.green_low.tolist(), self.green_high.tolist())
        print("[CAL] ok.")

    # -----------------------------------------------------------------------------
    # METHODE: detect
    # -----------------------------------------------------------------------------
    # Führt die eigentliche Landebahn-Erkennung aus:
    # 1) Resize & HSV, 2) Weiß/Grün-Thresholds, 3) Morphologie, 4) größte Kontur,
    # 5) Geometriechecks (Fläche, Seitenverhältnis, Winkel), 6) Ringtest (Grünanteil).
    # Rückgabe: cv2.minAreaRect(...) oder None.
    # -----------------------------------------------------------------------------
    def detect(self, frame_rgb):
        proc = cv2.resize(frame_rgb, (self.proc_width, self.proc_height))
        hsv = cv2.cvtColor(proc, cv2.COLOR_RGB2HSV)

        mask_w   = cv2.inRange(hsv, self.white_low, self.white_high)
        mask_g   = cv2.inRange(hsv, self.green_low, self.green_high)
        mask_gray= cv2.inRange(hsv, DEFAULT_GRAY_LOW, DEFAULT_GRAY_HIGH)

        kernel = np.ones((5,5), np.uint8)
        mask_w = cv2.morphologyEx(mask_w, cv2.MORPH_OPEN, kernel)
        mask_w = cv2.morphologyEx(mask_w, cv2.MORPH_CLOSE, kernel)

        cnts, _ = cv2.findContours(mask_w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None

        c = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(c) < MIN_WHITE_AREA:
            return None

        rect = cv2.minAreaRect(c)
        (x, y), (width, height), angle = rect

        aspect = max(width, height) / max(1.0, min(width, height))
        if aspect < ASPECT_MIN:
            return None

        a = abs(angle)
        a = min(a, abs(a - 90))
        if a > ANGLE_TOL_DEG:
            return None

        # Ring erzeugen
        fill = cv2.drawContours(np.zeros_like(mask_w), [c], 0, 255, -1)
        if SCALE_RING_BY_TARGET:
            base = max(5.0, min(width, height) * RING_SCALE_OUTER)
            outer_sz = _odd_int(base, min_val=5, max_val=151)
            inner_sz = _odd_int(outer_sz * RING_INNER_RATIO, min_val=3, max_val=outer_sz - 2)
        else:
            outer_sz = _odd_int(RING_OUTER_PX)
            inner_sz = _odd_int(RING_INNER_PX, max_val=outer_sz - 2)

        outer = cv2.dilate(fill, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outer_sz, outer_sz)))
        inner = cv2.dilate(fill, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (inner_sz, inner_sz)))
        ring  = cv2.subtract(outer, inner)

        rp = int(np.count_nonzero(ring))
        if rp <= 0:
            return None

        gp = int(np.count_nonzero(cv2.bitwise_and(mask_g,    ring)))
        gr = int(np.count_nonzero(cv2.bitwise_and(mask_gray, ring)))
        green_ratio = gp / rp
        gray_ratio  = gr / rp

        # Akzeptiere, wenn EINES der beiden Kriterien erfüllt ist
        if (green_ratio < MIN_GREEN_RATIO) and (gray_ratio < MIN_GRAY_RATIO):
            return None

        return rect



class FlightRecorder:
    # -----------------------------------------------------------------------------
    # KLASSE: FlightRecorder
    # -----------------------------------------------------------------------------
    # Orchestriert das Gesamtsystem:
    # - setup(): Kamera & Aufnahme starten, MAVLink verbinden, Trigger-WP bestimmen, kalibrieren
    # - run(): Hauptschleife (Frames, Segmentierung, Trigger/Erkennung, Lande-Sequenz, Missionsende)
    # - finally: Aufnahme sauber stoppen (writer.release + os.sync)
    # -----------------------------------------------------------------------------

    # -----------------------------------------------------------------------------
    # METHODE: __init__
    # -----------------------------------------------------------------------------
    # Legt Komponenten an (Recorder/MAVLink/Detector) und setzt interne Flags.
    # -----------------------------------------------------------------------------
    def __init__(self):
        self.recorder = VideoRecorder()
        self.mavlink = MavlinkClient(SERIAL_DEV, BAUD)
        self.detector = RunwayDetector(PROC_WIDTH)
        self.searching = False
        self.trigger_wp = None
        self.deadline = -1

    # -----------------------------------------------------------------------------
    # METHODE: setup
    # -----------------------------------------------------------------------------
    # Startet Kamera und Aufnahme; stellt MAVLink-Verbindung her; sucht Trigger-WP;
    # führt (optional) die HSV-Auto-Kalibrierung aus.
    # Wirft RuntimeError, wenn Kamera/Recording nicht starten.
    # -----------------------------------------------------------------------------
    def setup(self):
        ok = self.recorder.start_camera()
        if not ok:
            raise RuntimeError("Kamera konnte nicht gestartet werden.")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not self.recorder.start_recording(f"flight_{ts}"):
            raise RuntimeError("Video-Aufnahme konnte nicht gestartet werden.")

        self.mavlink.connect()
        if self.mavlink.is_connected:
            self.trigger_wp = self.mavlink.autodetect_trigger_wp()

        self.detector.calibrate(self.recorder.get_frame)
        print("[SETUP] bereit.")

    # -----------------------------------------------------------------------------
    # METHODE: run
    # -----------------------------------------------------------------------------
    # Hauptschleife:
    # - Frames aus Kamera holen und ins Video schreiben (RGB→BGR)
    # - MAVLink-Status aktualisieren
    # - Zeitbasierte Segmentierung
    # - Suchfenster am Trigger-WP
    # - Bei Treffer: LOITER → optional GUIDED-Offset → AUTO + DO_LAND_START
    # - Missionsende erkennen; geordneter Abschluss
    # -----------------------------------------------------------------------------
    def run(self):
        try:
            self.setup()
            while True:
                frame = self.recorder.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                self.recorder.writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                self.mavlink.update_state()

                if time.time() - self.recorder.last_segment_time > SEGMENT_SECONDS:
                    self.recorder.cut_segment("flight")

                if (self.mavlink.is_connected and self.trigger_wp is not None and
                        self.mavlink.current_seq == self.trigger_wp and not self.searching):
                    self.searching = True
                    self.deadline = time.time() + SEARCH_WINDOW_SEC
                    print("[TRIGGER] Trigger-WP erreicht -> Suche an.")

                if self.searching:
                    res = self.detector.detect(frame)
                    if res is not None:
                        self.searching = False
                        if ROTATE_ON_EVENTS:
                            self.recorder.cut_segment("flight", tag="land_start")
                        print("[LAND] Bahn gefunden; Landeprozedur starten...")

                        self.mavlink.set_mode("LOITER")
                        time.sleep(LOITER_SECONDS)

                        if DO_GUIDED_OFFSET:
                            pos, hdg = self.mavlink.get_current_pos_and_heading()
                            if pos and hdg is not None:
                                lat, lon, alt = pos
                                lat2, lon2 = dest_from(lat, lon, hdg, OFFSET_METERS)
                                self.mavlink.set_mode("GUIDED")
                                self.mavlink.goto_global_pos(lat2, lon2, alt)
                                time.sleep(8)

                        self.mavlink.set_mode("AUTO")
                        self.mavlink.do_land_start()

                    elif time.time() > self.deadline:
                        print("[WARN] Suche timeout, schalte ab.")
                        self.searching = False

                if (self.mavlink.is_connected and self.mavlink.mission_waypoints and
                        self.mavlink.current_seq >= (len(self.mavlink.mission_waypoints) - 1) and
                        not self.searching):
                    print("[INFO] Mission fertig. beende.")
                    if ROTATE_ON_EVENTS:
                        self.recorder.cut_segment("flight", tag="landed")
                    break

        except KeyboardInterrupt:
            print("[INFO] Abbruch durch Benutzer (Ctrl+C).")
        except Exception as e:
            print("[ERROR] Unerwarteter Fehler:", e)
        finally:
            self.recorder.stop_recording()
            print("[INFO] Cleanup done. Tschüss!")


# ==============================================================================
# MAIN
# ==============================================================================
# Programmeinstieg: erstellt die FlightRecorder-Instanz und startet run().
if __name__ == "__main__":
    app = FlightRecorder()
    app.run()
