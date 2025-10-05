# export_log_interactive.py
# Anforderungen:
#   pip install pymavlink pandas openpyxl plotly
# Optional:
#   pip install xlsxwriter

import sys
import subprocess
import shutil
import re
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots


# ------------------------------ Pfad & Tool-Finder ------------------------------

def find_mavlogdump() -> Optional[str]:
    cand = shutil.which("mavlogdump.py") or shutil.which("mavlogdump")
    if cand:
        return cand
    for c in [
        Path(sys.exec_prefix) / "Scripts" / "mavlogdump.py",
        Path(sys.base_prefix) / "Scripts" / "mavlogdump.py",
        Path(sys.prefix) / "Scripts" / "mavlogdump.py",
        Path(r"C:\Python\Scripts\mavlogdump.py"),
    ]:
        if c.exists():
            return str(c)
    return None


def ask_path(prompt: str) -> Optional[Path]:
    p = input(prompt).strip().strip('"')
    if not p:
        return None
    path = Path(p).expanduser()
    if not path.exists():
        print(f"❌ Datei/Ordner nicht gefunden: {path}")
        return None
    if path.is_dir():
        cand = sorted(list(path.glob("*.bin")) + list(path.glob("*.tlog")),
                      key=lambda x: x.stat().st_mtime, reverse=True)
        if not cand:
            print("❌ Im Ordner keine .bin oder .tlog gefunden.")
            return None
        print(f"[i] Ordner erkannt – verwende neueste Logdatei: {cand[0].name}")
        return cand[0]
    return path


# ------------------------------ mavlogdump Wrapper ------------------------------

def run_mavlogdump_show_types(mavlogdump: str, log_path: Path) -> List[str]:
    target = str(log_path)  # kein 'file:'-Prefix
    cmd = [sys.executable, mavlogdump, "--show-types", target]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"mavlogdump --show-types fehlgeschlagen:\n{res.stderr or res.stdout}")
    types: List[str] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if line and re.fullmatch(r"[A-Z0-9_]+", line):
            types.append(line)
    return sorted(set(types))


def run_mavlogdump_csv_for_type(mavlogdump: str, log_path: Path, msg_type: str) -> Optional[pd.DataFrame]:
    target = str(log_path)
    cmd = [sys.executable, mavlogdump, "--format", "csv", "--types", msg_type, target]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return None
    csv_text = res.stdout.strip()
    if not csv_text or "," not in csv_text:
        return None
    try:
        df = pd.read_csv(StringIO(csv_text))
    except Exception:
        return None
    if df.empty:
        return None
    time_col = next((c for c in ["TimeUS", "time_usec", "TimeMS", "time_boot_ms"] if c in df.columns), None)
    if not time_col:
        return None
    try:
        base = float(df[time_col].iloc[0])
    except Exception:
        return None
    denom = 1_000_000.0 if ("US" in time_col or "usec" in time_col.lower()) else (1_000.0 if ("MS" in time_col or "ms" in time_col.lower()) else 1.0)
    df["t_sec"] = (df[time_col].astype("float64") - base) / denom
    df["t_sec"] = df["t_sec"].round(2)  # ✅ Sekunden auf 2 Dezimalstellen
    return df


# ------------------------------ Excel & Plots ------------------------------

def to_excel(sheets: Dict[str, pd.DataFrame], summary: Optional[pd.DataFrame], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        if summary is not None and not summary.empty:
            summary.to_excel(xw, sheet_name="SUMMARY", index=False)
        idx = pd.DataFrame(
            [{"Type": k, "Rows": len(v), "Columns": len(v.columns)} for k, v in sheets.items()]
        ).sort_values("Type")
        idx.to_excel(xw, sheet_name="INDEX", index=False)
        for typ, df in sheets.items():
            sheet_name = typ[:31]
            cols = ["t_sec"] + [c for c in df.columns if c != "t_sec"]
            # eindeutige Spaltennamen
            safe_cols, used = [], set()
            for c in cols:
                c2 = str(c)[:255]
                if c2 in used:
                    i = 2
                    c3 = f"{c2}_{i}"
                    while c3 in used:
                        i += 1
                        c3 = f"{c2}_{i}"
                    c2 = c3
                used.add(c2)
                safe_cols.append(c2)
            df_to_write = df[cols].copy()
            df_to_write.columns = safe_cols
            df_to_write.to_excel(xw, sheet_name=sheet_name, index=False)


def is_numeric_series(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not (s.dropna().empty)


# --- Relevante Spalten + Klartextnamen & Einheiten ---

TYPE_NAMES: Dict[str, str] = {
    "ATT":  "Attitude (Roll/Pitch/Yaw)",
    "GPS":  "Global Positioning System",
    "BARO": "Barometer",
    "RFND": "Rangefinder / Lidar",
    "RCIN": "RC Input",
    "RCOU": "RC Output",
    "BAT":  "Battery",
    "MODE": "Flight Mode",
    "MSG":  "Messages",
    "EV":   "Events",
    "XKF1": "Extended Kalman Filter (1)",
    "XKF2": "Extended Kalman Filter (2)",
    "XKF3": "Extended Kalman Filter (3)",
    "XKF4": "Extended Kalman Filter (4)",
    "XKF5": "Extended Kalman Filter (5)",
    "CTUN": "Control Tuning",
    "NTUN": "Navigation Tuning",
    "POS":  "Position Estimate",
}

PLOT_COLS_EXACT: Dict[str, List[str]] = {
    "ATT":  ["Roll", "Pitch", "Yaw"],
    "GPS":  ["Spd", "Sats", "Alt", "Yaw"],  # Speed, Satelliten, Höhe, Heading
    "BARO": ["Alt"],
    "RFND": ["Dist"],
    "RCIN": ["C1", "C2", "C3"],
    "RCOU": ["C1", "C2", "C3"],
    "BAT":  ["Volt", "Curr"],               # Spannung & Strom
}

PLOT_COLS_REGEX: Dict[str, List[str]] = {
    "ATT":  [r"^Roll", r"^Pitch", r"^Yaw"],
    "GPS":  [r"Sat|NSats", r"Spd|Speed|Vel", r"Alt", r"Yaw|Heading|Hdg"],
    "BARO": [r"Alt"],
    "RFND": [r"Dist|Range|rng|distance"],
    "RCIN": [r"^C[1-3]$"],
    "RCOU": [r"^C[1-3]$"],
    "BAT":  [r"Volt|Vcc|Voltage", r"Curr|CurrTot|Current"],
}

# Einheiten je Typ/Feld (Regex erlaubt)
UNITS: Dict[str, List[Tuple[str, str]]] = {
    "ATT":  [(r"^Roll$", "deg"), (r"^Pitch$", "deg"), (r"^Yaw$", "deg")],
    "GPS":  [
        (r"^(Spd|Speed|Vel[n]?)$", "m/s"),
        (r"^(Alt|AltMSL|RelAlt)$", "m"),
        (r"^(Yaw|Heading|Hdg)$", "deg"),
        (r"^(Sats|NSats)$", ""),   # dimensionslos
    ],
    "BARO": [(r"^(Alt|AltFilt|PressAlt)$", "m"), (r"^Press(ure)?$", "Pa"), (r"^Temp$", "°C")],
    "RFND": [(r"^(Dist|distance|Range|rng)$", "m")],
    "RCIN": [(r"^C\d+$", "µs")],
    "RCOU": [(r"^C\d+$", "µs")],
    "BAT":  [(r"^(Volt|Voltage|Vcc)$", "V"), (r"^(Curr|Current)$", "A"), (r"^CurrTot$", "Ah")],
}

DEFAULT_PLOT_TYPES: List[str] = ["RCIN", "RCOU", "ATT", "GPS", "BARO", "RFND", "BAT"]


def unit_for(typ: str, col: str) -> str:
    """Gibt Einheit für (Typ, Spaltenname) zurück, sonst ''."""
    rules = UNITS.get(typ, [])
    for pat, u in rules:
        if re.match(pat, col, flags=re.IGNORECASE):
            return u
    return ""


def choose_plot_columns(df: pd.DataFrame, typ: str) -> List[str]:
    """Wähle nur relevante Spalten gemäß Whitelist (mit Fallbacks)."""
    cols: List[str] = []
    # exakte Namen
    for name in PLOT_COLS_EXACT.get(typ, []):
        if name in df.columns and is_numeric_series(df[name]):
            cols.append(name)
    # Regex-Fallbacks, bis Zielanzahl erreicht
    if len(cols) < len(PLOT_COLS_EXACT.get(typ, [])):
        patterns = PLOT_COLS_REGEX.get(typ, [])
        for pat in patterns:
            for c in df.columns:
                if c in cols:
                    continue
                if re.search(pat, c, re.IGNORECASE) and is_numeric_series(df[c]):
                    cols.append(c)
    # deduplizieren
    seen, uniq = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def make_plots_html(sheets: Dict[str, pd.DataFrame], out_html: Path, selected_types: Optional[List[str]] = None):
    """Interaktive Plot-HTML: pro Typ ein Plot, mit zwei Y-Achsen bei gemischten Einheiten."""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    types_for_plots = selected_types if selected_types else [t for t in DEFAULT_PLOT_TYPES if t in sheets]
    if not types_for_plots:
        types_for_plots = list(sheets.keys())[:6]

    html_parts: List[str] = []
    for typ in types_for_plots:
        df = sheets.get(typ)
        if df is None or "t_sec" not in df.columns:
            continue

        plot_cols = choose_plot_columns(df, typ)
        if not plot_cols:
            continue

        # Einheiten je Spalte ermitteln
        col_units = {col: unit_for(typ, col) for col in plot_cols}
        # Gruppen nach Einheit
        groups: Dict[str, List[str]] = {}
        for col, u in col_units.items():
            groups.setdefault(u, []).append(col)

        # Achsen-Strategie:
        # - Primäre Achse = Einheit mit den meisten Kurven (oder erste)
        # - Sekundäre Achse = (falls vorhanden) eine weitere Einheit (alle restlichen Kurven zusammen)
        units_sorted = sorted(groups.keys(), key=lambda u: len(groups[u]), reverse=True)
        primary_unit = units_sorted[0] if units_sorted else ""
        secondary_unit = units_sorted[1] if len(units_sorted) > 1 else None

        # Figure mit secondary_y anlegen
        fig = make_subplots(specs=[[{"secondary_y": secondary_unit is not None}]])

        # Primär-Achse Traces
        for col in groups.get(primary_unit, []):
            name = f"{typ}.{col}" + (f" [{primary_unit}]" if primary_unit else "")
            fig.add_trace(
                go.Scatter(x=df["t_sec"], y=df[col], mode="lines", name=name),
                secondary_y=False
            )

        # Sekundär-Achse Traces (alle übrigen Einheiten zusammen)
        if secondary_unit is not None:
            # Sammle alle nicht-primären Spalten
            secondary_cols = []
            for u, cols in groups.items():
                if u != primary_unit:
                    secondary_cols.extend(cols)
            for col in secondary_cols:
                u = col_units[col]
                name = f"{typ}.{col}" + (f" [{u}]" if u else "")
                fig.add_trace(
                    go.Scatter(x=df["t_sec"], y=df[col], mode="lines", name=name),
                    secondary_y=True
                )

        label = TYPE_NAMES.get(typ, typ)
        # Achsentitel
        y1_title = primary_unit or "Value"
        y2_title = (secondary_unit or "Value") if secondary_unit is not None else None

        fig.update_layout(
            title=f"{label} ({typ}) – Legend klicken zum Ein-/Ausblenden",
            xaxis_title="Time [s]",
            legend_title="Signals",
            height=460,
            margin=dict(l=60, r=60, t=60, b=50),
        )
        fig.update_yaxes(title_text=y1_title, secondary_y=False)
        if secondary_unit is not None:
            fig.update_yaxes(title_text=y2_title, secondary_y=True)

        html_parts.append(pio.to_html(fig, include_plotlyjs=False, full_html=False))

    template = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ArduPilot Log – Interactive Plots</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:20px}}
 h1{{margin:0 0 10px 0}}
 .plot{{margin:18px 0;}}
</style>
</head>
<body>
<h1>ArduPilot Log – Interactive Plots</h1>
<p>Relevante Signale: RCIN/RCOU C1–C3, Attitude (Roll/Pitch/Yaw), GPS (Spd, Sats, Alt, Heading), BARO Alt, RFND Dist, BAT Volt/Curr. Einheiten stehen in der Legende. Bei gemischten Einheiten werden zwei Y-Achsen verwendet.</p>
{plots}
</body>
</html>
"""
    content = template.format(plots="\n".join(f'<div class="plot">{part}</div>' for part in html_parts))
    out_html.write_text(content, encoding="utf-8")


# ------------------------------ Ziel-Nachweis/KPIs ------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math as m
    R = 6371.0
    dlat = m.radians(lat2 - lat1)
    dlon = m.radians(lon2 - lon1)
    a = m.sin(dlat/2)**2 + m.cos(m.radians(lat1))*m.cos(m.radians(lat2))*m.sin(dlon/2)**2
    c = 2*m.atan2(m.sqrt(1-a), m.sqrt(a))
    return R*c


def compute_summary(sheets: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: List[Tuple[str, str]] = []

    gps = sheets.get("GPS")
    if gps is not None:
        sats = gps.filter(regex=r"Sat|Sats|NSats", axis=1)
        spd_col = next((c for c in ["Spd", "Speed", "Vel", "Veln"] if c in gps.columns), None)
        lat_col = next((c for c in ["Lat", "lat", "LAT"] if c in gps.columns), None)
        lon_col = next((c for c in ["Lng", "Lon", "lon", "LON"] if c in gps.columns), None)
        alt_col = next((c for c in ["Alt", "AltMSL", "RelAlt"] if c in gps.columns), None)
        yaw_col = next((c for c in ["Yaw","Heading","Hdg"] if c in gps.columns), None)

        rows.append(("GPS: Messages", f"{len(gps)}"))
        if not sats.empty:
            sname = sats.columns[0]
            rows.append(("GPS: Satellites (Ø / min)", f"{sats[sname].mean():.1f} / {sats[sname].min()}"))

        if spd_col:
            rows.append(("GPS: Speed (Ø / max) [m/s]", f"{gps[spd_col].mean():.2f} / {gps[spd_col].max():.2f}"))
            moving_pct = (gps[spd_col] > 0.5).mean() * 100.0
            rows.append(("GPS: Anteil Zeit >0.5 m/s [%]", f"{moving_pct:.1f}"))

        if lat_col and lon_col:
            dist = 0.0
            lats = gps[lat_col].astype(float).to_numpy()
            lons = gps[lon_col].astype(float).to_numpy()
            for i in range(1, len(gps)):
                dist += haversine_km(lats[i-1], lons[i-1], lats[i], lons[i])
            rows.append(("GPS: zurückgelegte Strecke [km]", f"{dist:.3f}"))

        if alt_col:
            rows.append(("GPS: Höhe (Ø / min / max) [m]", f"{gps[alt_col].mean():.1f} / {gps[alt_col].min():.1f} / {gps[alt_col].max():.1f}"))

        if yaw_col:
            rows.append(("GPS: Heading (Ø / min / max) [deg]", f"{gps[yaw_col].mean():.1f} / {gps[yaw_col].min():.1f} / {gps[yaw_col].max():.1f}"))
    else:
        rows.append(("GPS", "nicht vorhanden"))

    baro = sheets.get("BARO")
    if baro is not None:
        altc = next((c for c in ["Alt", "AltFilt", "PressAlt"] if c in baro.columns), None)
        if altc:
            rows.append(("BARO: Höhe (Ø / min / max) [m]", f"{baro[altc].mean():.1f} / {baro[altc].min():.1f} / {baro[altc].max():.1f}"))
    else:
        rows.append(("BARO", "nicht vorhanden"))

    rfnd = sheets.get("RFND")
    if rfnd is not None:
        dc = next((c for c in ["Dist", "distance", "Range", "rng"] if c in rfnd.columns), None)
        if dc:
            rows.append(("RFND: Distanz (Ø / min / max) [m]", f"{rfnd[dc].mean():.2f} / {rfnd[dc].min():.2f} / {rfnd[dc].max():.2f}"))
    else:
        rows.append(("RFND (Lidar)", "nicht vorhanden"))

    att = sheets.get("ATT")
    if att is not None:
        for name, label in [("Roll","Roll"), ("Pitch","Pitch"), ("Yaw","Yaw")]:
            if name in att.columns:
                rows.append((f"ATT: {label} (Ø / min / max) [deg]",
                             f"{att[name].mean():.2f} / {att[name].min():.2f} / {att[name].max():.2f}"))

    bat = sheets.get("BAT")
    if bat is not None:
        vcol = next((c for c in ["Volt","Voltage","Vcc"] if c in bat.columns), None)
        ccol = next((c for c in ["Curr","Current","CurrTot"] if c in bat.columns), None)
        if vcol:
            rows.append(("BAT: Spannung (Ø / min / max) [V]", f"{bat[vcol].mean():.2f} / {bat[vcol].min():.2f} / {bat[vcol].max():.2f}"))
        if ccol:
            rows.append(("BAT: Strom (Ø / max) [A]", f"{bat[ccol].mean():.2f} / {bat[ccol].max():.2f}"))
    else:
        rows.append(("BAT", "nicht vorhanden"))

    mode = sheets.get("MODE")
    msg = sheets.get("MSG")
    ev  = sheets.get("EV")

    if mode is not None:
        rows.append(("MODE: Einträge", f"{len(mode)}"))
        name_col = next((c for c in ["Mode", "ModeNum", "mode", "DesMode"] if c in mode.columns), None)
        if name_col:
            first_modes = ", ".join(map(str, mode[name_col].head(5).tolist()))
            rows.append(("MODE: erste 5", first_modes))
    else:
        rows.append(("MODE", "nicht vorhanden"))

    fs_hits = 0
    fs_times = []
    if msg is not None:
        tcol = "t_sec" if "t_sec" in msg.columns else None
        mcol = next((c for c in ["Message", "Msg", "message", "Text"] if c in msg.columns), None)
        if mcol:
            mask = msg[mcol].astype(str).str.contains(r"failsafe|FS|FAILSAFE", case=False, regex=True)
            fs_hits += int(mask.sum())
            if tcol:
                fs_times += msg.loc[mask, tcol].tolist()
    if ev is not None:
        tcol = "t_sec" if "t_sec" in ev.columns else None
        for c in ev.columns:
            if ev[c].dtype == object:
                mask = ev[c].astype(str).str.contains(r"failsafe|FS|FAILSAFE", case=False, regex=True)
                fs_hits += int(mask.sum())
                if tcol:
                    fs_times += ev.loc[mask, tcol].tolist()
    rows.append(("Failsafe-Hinweise (MSG/EV)", f"{fs_hits}"))

    fs_to_mode_secs = []
    if fs_times and mode is not None and "t_sec" in mode.columns:
        mode_times = mode["t_sec"].astype(float).tolist()
        for t in fs_times:
            later = [mt for mt in mode_times if mt >= t]
            if later:
                fs_to_mode_secs.append(later[0] - t)
        if fs_to_mode_secs:
            s = pd.Series(fs_to_mode_secs)
            rows.append(("Δt Failsafe → nächster MODE [s] (Ø / max)", f"{s.mean():.2f} / {s.max():.2f}"))

    wp_hits = 0
    if msg is not None:
        mcol = next((c for c in ["Message", "Msg", "message", "Text"] if c in msg.columns), None)
        if mcol:
            wp_mask = msg[mcol].astype(str).str.contains(r"Reached|Waypoint|WP", case=False, regex=True)
            wp_hits = int(wp_mask.sum())
    rows.append(("Wegpunkte erreicht (MSG-Heuristik)", f"{wp_hits}"))

    land_detected, land_t = False, None
    if mode is not None:
        for c in mode.columns:
            if mode[c].dtype == object:
                mask = mode[c].astype(str).str.contains(r"LAND", case=False, regex=True)
                if mask.any():
                    land_detected = True
                    land_t = float(mode.loc[mask, "t_sec"].iloc[0]) if "t_sec" in mode.columns else None
                    break
    if not land_detected and msg is not None:
        mcol = next((c for c in ["Message", "Msg", "message", "Text"] if c in msg.columns), None)
        if mcol is not None:
            mask = msg[mcol].astype(str).str.contains(r"LAND", case=False, regex=True)
            if mask.any():
                land_detected = True
                land_t = float(msg.loc[mask, "t_sec"].iloc[0]) if "t_sec" in msg.columns else None
    rows.append(("LAND-Phase erkannt (MODE/MSG)", "ja" if land_detected else "nein"))

    rfnd = sheets.get("RFND")
    touchdown_ok = None
    if land_detected and rfnd is not None and "t_sec" in rfnd.columns:
        dc = next((c for c in ["Dist", "distance", "Range", "rng"] if c in rfnd.columns), None)
        if dc:
            window = rfnd if land_t is None else rfnd[rfnd["t_sec"] >= land_t]
            min_rfnd = window[dc].min() if not window.empty else float("nan")
            rows.append(("RFND minimal nach LAND [m]", f"{min_rfnd:.2f}" if pd.notna(min_rfnd) else "n/a"))
            gps_spd_ok = None
            if gps is not None and "t_sec" in gps.columns and spd_col:
                gwin = gps if land_t is None else gps[gps["t_sec"] >= land_t]
                min_spd = gwin[spd_col].min() if not gwin.empty else float("nan")
                rows.append(("GPS minimal Speed nach LAND [m/s]", f"{min_spd:.2f}" if pd.notna(min_spd) else "n/a"))
                gps_spd_ok = (pd.notna(min_spd) and min_spd < 1.0)
            if pd.notna(min_rfnd):
                touchdown_ok = (min_rfnd < 0.30) and (gps_spd_ok is None or gps_spd_ok)
    if touchdown_ok is not None:
        rows.append(("Touchdown-Heuristik (RFND<0.3m & Spd<1.0)", "erfüllt" if touchdown_ok else "nicht erfüllt"))

    xkf_msgs = sum(len(sheets[t]) for t in ["XKF1","XKF2","XKF3","XKF4","XKF5"] if t in sheets)
    rows.append(("EKF Datendichte (Summe XKF* Messages)", f"{xkf_msgs}"))

    return pd.DataFrame(rows, columns=["Kennzahl", "Wert"])


# ------------------------------ Main ------------------------------

def main():
    print("=== ArduPilot Log Export (Excel + interaktive Plots + Ziel-Nachweis) ===")
    print("Hinweis: Dieses Skript nutzt 'mavlogdump.py' aus pymavlink.\n")

    mavlogdump = find_mavlogdump()
    if not mavlogdump:
        print("❌ 'mavlogdump.py' wurde nicht gefunden. Bitte installiere/prüfe:  pip install pymavlink")
        return
    else:
        print(f"[i] Verwende mavlogdump unter: {mavlogdump}")

    log_path = ask_path("👉 Pfad zur .bin oder .tlog Datei ODER Ordner einfügen und Enter drücken:\n> ")
    if not log_path:
        return

    default_outdir = log_path.parent / "Auswertung"
    outdir_in = input(f"Optional: Ausgabeordner (Enter = '{default_outdir}'):\n> ").strip().strip('"')
    outdir = Path(outdir_in).expanduser() if outdir_in else default_outdir
    outdir.mkdir(parents=True, exist_ok=True)

    goal_types = ["ATT","GPS","POS","BARO","RFND","RCIN","RCOU","MODE","EV","MSG",
                  "XKF1","XKF2","XKF3","XKF4","XKF5","CTUN","NTUN","BAT"]
    use_goal_profile = input("Nur zielrelevante Typen exportieren? (J/N, Enter=J): ").strip().lower()
    if use_goal_profile in ("", "j", "y"):
        include = goal_types
        exclude: List[str] = []
        plot_types_in = input(f"Optional: Nur diese Typen im HTML plotten (Komma-Liste) – Enter = Default ({','.join(DEFAULT_PLOT_TYPES)}):\n> ").strip()
        plot_types = [t.strip().upper() for t in plot_types_in.split(",") if t.strip()] if plot_types_in else DEFAULT_PLOT_TYPES
    else:
        include_in = input("Optional: Nur diese Typen extrahieren (Komma-Liste) – Enter = alle:\n> ").strip()
        exclude_in = input("Optional: Diese Typen ausschließen (Komma-Liste) – Enter = keine:\n> ").strip()
        plot_types_in = input(f"Optional: Nur diese Typen im HTML plotten (Komma-Liste) – Enter = Default ({','.join(DEFAULT_PLOT_TYPES)}):\n> ").strip()
        include = [t.strip().upper() for t in include_in.split(",") if t.strip()] if include_in else []
        exclude = [t.strip().upper() for t in exclude_in.split(",") if t.strip()] if exclude_in else []
        plot_types = [t.strip().upper() for t in plot_types_in.split(",") if t.strip()] if plot_types_in else DEFAULT_PLOT_TYPES

    print(f"\n[i] Analysiere Typen in {log_path.name} …")
    try:
        types = run_mavlogdump_show_types(mavlogdump, log_path)
    except Exception as e:
        print(f"❌ Konnte Typen nicht ermitteln:\n{e}")
        return
    print(f"[i] Gefundene Typen ({len(types)}): {', '.join(types)}")

    if include:
        types = [t for t in types if t in include]
        print(f"[i] Gefiltert (include): {', '.join(types)}")
    if exclude:
        types = [t for t in types if t not in exclude]
        print(f"[i] Gefiltert (exclude): {', '.join(types)}")

    if not types:
        print("❌ Nach Filterung sind keine Typen übrig.")
        return

    sheets: Dict[str, pd.DataFrame] = {}
    for t in types:
        print(f"[i] Exportiere {t} …")
        try:
            df = run_mavlogdump_csv_for_type(mavlogdump, log_path, t)
        except Exception:
            df = None
        if df is None or df.empty:
            print(f"[!] {t} übersprungen (keine/ungültige Daten).")
            continue
        sheets[t] = df

    if not sheets:
        print("❌ Keine verwertbaren Typen gefunden.")
        return

    print("[i] Erzeuge Ziel-Nachweis (SUMMARY) …")
    summary_df = compute_summary(sheets)

    out_xlsx = outdir / (log_path.stem + ".xlsx")
    to_excel(sheets, summary_df, out_xlsx)
    print(f"[✓] Excel geschrieben: {out_xlsx}")

    out_html = outdir / (log_path.stem + ".html")
    make_plots_html(sheets, out_html, selected_types=plot_types)
    print(f"[✓] Interaktive Plots geschrieben: {out_html}")

    print("\nFertig ✅")
    print("- Excel: SUMMARY (Kennzahlen), INDEX, je Typ ein Sheet (t_sec = Sekunden ab 0, 2 Nachkommastellen).")
    print("- HTML: Klartext + Kürzel im Titel, Einheiten in der Legende, 2 Y-Achsen bei gemischten Einheiten.")
    print("- Standardplots: RCIN/RCOU C1–C3, Attitude, GPS (Spd/Sats/Alt/Heading), BARO Alt, RFND Dist, BAT Volt/Curr.")
    print("- Du kannst die geplotteten Typen beim Start überschreiben (Prompt).")


if __name__ == "__main__":
    main()
