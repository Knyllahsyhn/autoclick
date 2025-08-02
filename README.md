# Popup-AutoClicker ⏱️🖱️

A lightweight, keyboard-controlled auto-clicker that hunts for pop-ups on your screen and dismisses them in real time—while showing a live status dashboard in your terminal powered by [Rich](https://github.com/Textualize/rich).


---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Template matching with confidence** | Finds buttons or pop-ups on the screen by image similarity (OpenCV under the hood). |
| **Live dashboard** | Real-time panel with current status, last action, error log, and button count—no more guessing what the script is doing. |
| **Hotkeys** | <kbd>F8</kbd> = pause/resume, <kbd>F9</kbd> = graceful shutdown. |
| **Auto-reload** | Detects new / deleted button screenshots dropped into the `buttons/` folder without restart. |
| **Cross-platform** | Works on Windows, macOS, and most Linux desktop environments. |

---

## 🚀 Quick start

### 1. Clone & install

```bash
git clone https://github.com/Knyllahsyhn/autoclicker.git
cd pautoclicker
python -m venv .venv && source .venv/bin/activate  # PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
