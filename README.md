# G25 & G27 HID Manager for Windows

This tool allows you to configure your Logitech G25/G27 steering wheels by sending raw USB commands directly to the hardware. It is designed to work as a standalone GUI dashboard or as a CLI utility for game launchers.

## Features
* **Native Mode Unlock:** Initialize the wheel without external drivers.
* **Persistent Settings:** Configure Steering Lock (40-900°) and Auto-Center spring force.
* **Telemetry:** Real-time monitoring of steering axis, pedals, H-pattern shifter, and buttons.
* **CLI Integration:** Automate wheel configuration when launching your favorite driving simulators.

![g25 HID Manager screenshot](https://github.com/Poil/Logitech-G25-config/raw/refs/heads/main/logitech_hid_manager.webp)
![g25 HID Manager screenshot](https://github.com/Poil/Logitech-G25-config/raw/refs/heads/main/g25_hid_manager.webp)

## How to Build
Ensure you have `poetry` installed, then:
```bash
poetry install
poetry run pyinstaller --noconsole --onefile logitech_hid_manager.py

# or in poetry env
pyinstaller --noconsole --onefile logitech_hid_manager.py
```

## CLI Usage
You can use the executable as a command-line tool to automate your setup before launching a game.

### Arguments
| Argument | Description |
| :--- | :--- |
| --degrees | Set the wheel rotation limit (40 to 900). |
| --autocenter | Set the spring centering force percentage (0 to 100). |
| --profile | Path to a custom JSON profile file. |
| --launch | Path to an executable or a URI (e.g., a Steam game link) to launch after applying settings. |

### Examples
**1. Configure and launch a game directly:**

    logitech_hid_manager.exe --degrees 540 --autocenter 15 --launch "steam://rungameid/310560"

**2. Just apply settings for a session:**

    logitech_hid_manager.exe --degrees 900

## Profiles
The application automatically creates a settings.json file in the same directory as the executable. This file persists your GUI slider preferences between launches. You can create multiple JSON files and load them using the --profile argument.