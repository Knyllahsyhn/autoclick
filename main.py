# -*- coding: utf-8 -*-
# Anforderungen:
# pip install mss opencv-python pyautogui keyboard rich pygetwindow
# (pyscreeze ist oft schon via pyautogui da, hier zusätzlich importiert wie gewünscht)

import os
import time
import threading
import concurrent.futures as futures

import pyautogui
import pyscreeze  # auf Wunsch explizit importiert
import cv2
import numpy as np
import mss
import pygetwindow as gw
import keyboard

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.live import Live

# ----------------- Konfiguration -----------------
BUTTONS_FOLDER     = "buttons"
SCAN_EXTENSIONS    = ('.png', '.jpg', '.jpeg', '.bmp')
RELOAD_INTERVAL_S  = 10      # wie oft Templates neu laden
SCAN_INTERVAL_S    = 0.02     # kleine Pause pro Loop
THRESHOLD          = 0.86       # Match-Schwelle (0.80–0.92 justieren)
DOWNSCALE          = 0.90       # 1.0 = aus; 0.75–0.9 beschleunigt
WINDOW_TITLE_HINT  = "Bluestacks App Player 1 " # z.B. "BlueStacks", "Nox", "Memu", "Android"
MAX_LOG_LINES      = 12
MAX_WORKERS        = max(4, os.cpu_count() or 4)  # Threads für paralleles Matching
CLICK_COOLDOWN_S   = 0.2       # um Doppelklicks zu vermeiden

# ----------------- Zustände/Globals -----------------
console      = Console()
paused       = False
running      = True
last_action  = "-"
last_error   = "-"
log_lines    = []
templates    = []     # Liste Dicts: {name, img, w, h, img_ds, w_ds, h_ds}
bbox         = None   # Emulator-Fenster (left, top, width, height)
loop_ms      = 0.0
fps          = 0.0
last_reload  = 0.0

# ----------------- Utilities -----------------
def add_log(msg, style=None):
    global log_lines
    t = Text.from_markup(msg)
    if style:
        t.stylize(style)
    log_lines.append(t)
    if len(log_lines) > MAX_LOG_LINES:
        log_lines = log_lines[-MAX_LOG_LINES:]

def find_emulator_bbox():
    """Suche Fenster anhand Titel-Hint. Fallback: gesamte Primäranzeige."""
    try:
        candidates = [t for t in gw.getAllTitles() if WINDOW_TITLE_HINT.lower() in t.lower()]
        if candidates:
            win = gw.getWindowsWithTitle(candidates[0])[0]
            # Optional: fokusieren
            try:
                if not win.isActive:
                    win.activate()
                    time.sleep(0.15)
            except Exception:
                pass
            return {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
    except Exception:
        pass

    # Fallback auf gesamten Hauptmonitor per mss
    with mss.mss() as sct:
        mon = sct.monitors[1]  # 1 = Primary
        return {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}

def load_templates():
    """Lädt und preprocess't alle Templates (Graustufe + Downscale)."""
    ts = []
    if not os.path.isdir(BUTTONS_FOLDER):
        os.makedirs(BUTTONS_FOLDER, exist_ok=True)

    for f in os.listdir(BUTTONS_FOLDER):
        if not f.lower().endswith(SCAN_EXTENSIONS):
            continue
        path = os.path.join(BUTTONS_FOLDER, f)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        h, w = img.shape[:2]
        # Downscale Template, damit Matching zum downscaled Screenshot passt
        if DOWNSCALE != 1.0:
            tw = max(5, int(w * DOWNSCALE))
            th = max(5, int(h * DOWNSCALE))
            img_ds = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        else:
            img_ds = img
            tw, th = w, h

        ts.append({
            "name": f,
            "img": img,
            "w": w, "h": h,
            "img_ds": img_ds,
            "w_ds": tw, "h_ds": th
        })
    return ts

def capture_gray(mss_inst, roi):
    """Ein Screenshot (ROI) -> Graustufe, optional downscaled."""
    frame = np.array(mss_inst.grab(roi))  # BGRA
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    if DOWNSCALE != 1.0:
        gray = cv2.resize(gray, None, fx=DOWNSCALE, fy=DOWNSCALE, interpolation=cv2.INTER_AREA)
    return gray

def match_one(sgray, t):
    """Ein Template matchen. Rückgabe: (score, center_xy_ds) oder (None, None)."""
    tmpl = t["img_ds"]
    th, tw = tmpl.shape[:2]
    if sgray.shape[0] < th or sgray.shape[1] < tw:
        return None, None

    res = cv2.matchTemplate(sgray, tmpl, cv2.TM_CCOEFF_NORMED)
    # globales Maximum
    _, maxVal, _, maxLoc = cv2.minMaxLoc(res)
    if maxVal >= THRESHOLD:
        # Mittelpunkt im downscaled Screenshot
        cx_ds = maxLoc[0] + tw // 2
        cy_ds = maxLoc[1] + th // 2
        return maxVal, (cx_ds, cy_ds)
    return None, None

def parallel_match_first(sgray, templates):
    """Parallel über Templates matchen; gibt ersten Treffer (name, pos_abs) zurück."""
    # Wir sammeln Futures und brechen beim ersten guten Ergebnis ab
    with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(match_one, sgray, t): t for t in templates}
        for fut in futures.as_completed(future_map):
            t = future_map[fut]
            try:
                score, pos_ds = fut.result()
                if score is not None:
                    # zurückskalieren auf echte ROI-Koords
                    if DOWNSCALE != 1.0:
                        rx = int(pos_ds[0] / DOWNSCALE)
                        ry = int(pos_ds[1] / DOWNSCALE)
                    else:
                        rx, ry = pos_ds
                    return t["name"], (rx, ry)
            except Exception as e:
                # seltene Fehler im Matching stören nicht den Loop
                add_log(f"[red]Matching-Fehler in {t['name']}:[/red] {e}", style="red")
                continue
    return None, None

def click_abs(bbox, rel_xy):
    abs_x = bbox["left"] + rel_xy[0]
    abs_y = bbox["top"] + rel_xy[1]
    pyautogui.click(abs_x, abs_y)

def hotkey_thread():
    global paused, running
    add_log("[bold]Hotkeys:[/bold] [magenta]F8[/magenta]=Pause/Resume • [magenta]F9[/magenta]=Beenden")
    while running:
        try:
            if keyboard.is_pressed("F8"):
                paused = not paused
                add_log(f"[bold][Hotkey][/bold] {'[yellow]PAUSIERT[/yellow]' if paused else '[green]FORTGESETZT[/green]'}")
                time.sleep(0.45)  # debounce
            if keyboard.is_pressed("F9"):
                add_log("[bold red][Hotkey][/bold red] Beende Programm…", style="red")
                running = False
                break
        except:
            # Keyboard kann auf manchen Systemen Admin-Rechte brauchen
            pass
        time.sleep(0.08)

def render_ui():
    # Status
    stat = (
        f"[bold]Status:[/bold] {'[yellow]PAUSIERT[/yellow]' if paused else '[green]AKTIV[/green]'}\n"
        f"[bold]Templates:[/bold] {len(templates)}\n"
        f"[bold]Loop:[/bold] {loop_ms:.1f} ms • [bold]FPS:[/bold] {fps:.1f}\n"
        f"[bold]Letzte Aktion:[/bold] {last_action}\n"
        f"[bold]Letzter Fehler:[/bold] {last_error if last_error != '-' else '[dim]-[/dim]'}\n"
    )
    status_panel = Panel(stat, title="Status", border_style="cyan")

    # Templates-Tabelle
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Button-Datei", style="dim", overflow="fold")
    if templates:
        for t in templates:
            table.add_row(t["name"])
    else:
        table.add_row("[dim]Keine Templates gefunden[/dim]")
    tmpl_panel = Panel(table, title="Templates", border_style="blue")

    # Log
    if log_lines:
        log_render = Text("\n").join(log_lines)
    else:
        log_render = Text.from_markup("[dim]Noch keine Aktionen[/dim]")


    
    log_panel = Panel(log_render, title="Log", border_style="magenta")

    # Seite nebeneinander
    left = Table.grid(expand=True)
    left.add_row(status_panel)
    left.add_row(tmpl_panel)

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=2)
    grid.add_row(left, log_panel)
    return grid
# ----------------- Main -----------------
def main():
    global templates, bbox, last_reload, loop_ms, fps, last_action, last_error, running

    add_log(f"Starte [cyan]Popup-Autoklicker[/cyan]…")
    add_log(f"Bilder bitte in [bold]{BUTTONS_FOLDER}[/bold] ablegen.")

    bbox = find_emulator_bbox()
    add_log(f"ROI: left={bbox['left']} top={bbox['top']} w={bbox['width']} h={bbox['height']}")

    templates = load_templates()
    add_log(f"[dim]Templates geladen: {len(templates)}[/dim]")
    last_reload = time.time()

    # Hotkeys überwachen
    threading.Thread(target=hotkey_thread, daemon=True).start()

    with mss.mss() as sct, Live(render_ui(), refresh_per_second=12, console=console, screen=False) as live:
        roi = {"left": bbox["left"], "top": bbox["top"], "width": bbox["width"], "height": bbox["height"]}
        last_click_ts = 0.0

        while running:
            t0 = time.perf_counter()

            # dynamisch nachladen
            if time.time() - last_reload >= RELOAD_INTERVAL_S:
                templates = load_templates()
                last_reload = time.time()

            if not paused and templates:
                # capture
                sgray = capture_gray(sct, roi)
                # paralleles matching, erster Treffer reicht
                name, pos = parallel_match_first(sgray, templates)
                if name is not None and (time.time() - last_click_ts) >= CLICK_COOLDOWN_S:
                    try:
                        click_abs(bbox, pos)
                        last_action = f"[green]{name}[/green] erkannt & geklickt"
                        add_log(last_action)
                        last_error = "-"
                        last_click_ts = time.time()
                    except Exception as e:
                        last_error = f"Klickfehler: {e}"
                        add_log(f"[red]{last_error}[/red]", style="red")
                elif name is None:
                    # kein Treffer – nichts loggen (ruhig bleiben)
                    pass
            else:
                # pausiert
                pass

            # Metriken
            t1 = time.perf_counter()
            loop_ms = (t1 - t0) * 1000.0
            fps = 1000.0 / loop_ms if loop_ms > 0 else 0.0
        

            # UI-Refresh
            # (Live aktualisiert automatisch; optional könnten wir live.update(render_ui()) callen,
            #  aber da sich Variablen ändern, reicht der refresh_per_second in der Regel)
            live.update(render_ui())
            time.sleep(SCAN_INTERVAL_S)

    console.print("[bold green]Programm beendet.[/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Keyboard interrupt caught, exiting...[/red]")