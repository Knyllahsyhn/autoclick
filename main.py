# main.py
"""
Popup autoclicker with live status view.
---------------------------------------
F8  → Pause/Resume
F9  → Stop
Put button images into  „buttons“- subfolder. 


Johannes Müller, 02.08.2025

"""

import os
import time
from pathlib import Path

import keyboard           # pip install keyboard
import pyautogui          # pip install pyautogui>=0.9
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ---------------- Config ----------------
BUTTONS_FOLDER = Path("buttons")  # Folder for button images
SCAN_INTERVAL   = 0.1            # seconds between scans
RELOAD_INTERVAL = 5               # folder rescan interval (for adding pictures on the fly)
CONFIDENCE      = 0.8            # pyautogui confidence

# --------------- Globale Variablen -------------
console        = Console()
log_lines: list[Text] = []

button_images: list[str] = []
last_pic_count = 0

paused  = False
running = True

last_action = "-"
last_error  = "-"

last_reload = 0.0



# ------------------- Utils ---------------------
def log(msg: str) -> None:
    """Add a line to the log(Rich markup allowed)."""
    timestamp = time.strftime("[%H:%M:%S]")
    log_lines.append(Text.from_markup(f"{timestamp} {msg}"))


def reload_button_images() -> list[str]:
    """Rescan all files in picture folder."""
    return sorted(
        [
            str(p)                       # ①  Pfad sofort in String wandeln
            for p in BUTTONS_FOLDER.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ],
        key=os.path.getmtime,
    )

def toggle_pause() -> None:
    global paused, last_action
    paused = not paused
    state = "[yellow]PAUSED[/yellow]" if paused else "[green]ACTIVE[/green]"
    last_action = state
    log(f"Status changed → {state}")


def stop() -> None:
    global running
    running = False
    log("[red]Exit requested[/red]")


# --------------- Rich-Layout -------------------
def make_layout():
    """Erzeugt das gesamte Layout (Status- & Log-Panel)."""
    status_text = (
        f"[bold]Hotkeys:[/bold] [magenta]F8[/magenta] Pause/Resume | "
        f"[magenta]F9[/magenta] Exit\n"
        f"[bold]Status:[/bold] {'[yellow]PAUSED[/yellow]' if paused else '[green]ACTIVE[/green]'}\n"
        f"[bold]Last action:[/bold] {last_action}\n"
        f"[bold]Last exception:[/bold] {last_error if last_error != '-' else '[dim]-[/dim]'}\n"
        f"\n[bold]Found elements:[/bold] {len(button_images)}"
    )

    status_panel = Panel(Text.from_markup(status_text), border_style="cyan", title="Status")

    if log_lines:
        # max. 100 Logzeilen, sauber mit Zeilenumbruch verbinden
        log_content = Text("\n").join(log_lines[-100:])
    else:
        log_content = Text.from_markup("[dim]No actions yet[/dim]")

    log_panel = Panel(log_content, title="Log", border_style="magenta")

    grid = Table.grid(padding=1)
    grid.add_row(status_panel, log_panel)
    return grid


# ---------------- Hauptprogramm ----------------
def main() -> None:
    global button_images, last_pic_count, last_reload, last_action, last_error

    BUTTONS_FOLDER.mkdir(exist_ok=True)

    # Hotkeys registrieren
    keyboard.add_hotkey("f8", toggle_pause)
    keyboard.add_hotkey("f9", stop)

    # Erste Bildliste laden
    button_images = reload_button_images()
    last_pic_count = len(button_images)

    log("[cyan]Popup Autoclicker starting…[/cyan]")
    log(f"Put images in '[bold]{BUTTONS_FOLDER}[/bold]' !")

    with Live(make_layout(), console=console, refresh_per_second=4, screen=True) as live:
        while running:
            # Ordner regelmäßig neu einlesen
            if time.time() - last_reload > RELOAD_INTERVAL:
                button_images = reload_button_images()
                last_reload = time.time()
                if len(button_images) != last_pic_count:
                    last_pic_count = len(button_images)
                    log(f"[green]Folder Reloaded – {last_pic_count} Images available![/green]")

            if not paused:
                try:
                    for img_path in button_images:
                        try:
                            location = pyautogui.locateCenterOnScreen(img_path, confidence=CONFIDENCE)
                        except pyautogui.ImageNotFoundException:
                            location = None  
                        if location:
                            pyautogui.click(location)
                            last_action = f"[green]Clicked:[/green] {img_path}"
                            log(last_action)
                            break  # nur einen Button pro Zyklus
                    else:
                        last_action = "[dim]No Button found![/dim]"
                
                except Exception as exc:
                    last_error = f"[red]{type(exc).__name__}: {exc}[/red]"
                    log(last_error)

            live.update(make_layout())          # Layout neu zeichnen
            time.sleep(SCAN_INTERVAL)

    console.print("[bold green]Programm terminated.[/bold green]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Keyboard interrupt caught, exiting...[/red]")
