# G25 Hid Manager for Windows 11 (and older)

* The physical hardware chip inside the G25 only has memory to store two things persistently:
  * Degrees of Rotation (The physical steering lock limit)
  * Auto-Center Spring (The background centering pull)

This little Python program allow to send configuration via RAW USB command

![g25 HID Manager screenshot](https://github.com/Poil/Logitech-G25-config/raw/refs/heads/main/g25_hid_manager.webp)

# Howto Build

```
pyinstaller --noconsole --onefile g25_hid_manager.py
```

