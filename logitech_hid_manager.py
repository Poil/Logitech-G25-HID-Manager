import hid
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional, Dict, List, Tuple
import json
import os
import argparse
import time
import threading
import queue
from dataclasses import dataclass, field

# Immutable Hardware Constants
VENDOR_ID: int = 0x046D
NATIVE_PID_G25: int = 0xC299
NATIVE_PID_G27: int = 0xC29B
LEGACY_PID: int = 0xC294

G25_UNLOCK_PACKET: List[int] = [0x00, 0xF8, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00]
G27_UNLOCK_PACKET: List[int] = [0x00, 0xF8, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00]

@dataclass
class WheelTelemetry:
    """Immutable data container for raw USB parsing."""
    raw: bytes
    wheel_type: str

    steering_pct: float = 50.0
    gas_pct: float = 0.0
    brake_pct: float = 0.0
    clutch_pct: float = 0.0
    buttons: Dict[str, bool] = field(default_factory=dict)
    pov: int = 15
    gear: str = "N"

    def __post_init__(self):
        if len(self.raw) >= 12:
            self.steering_pct = ((self.raw[3] | (self.raw[4] << 8)) / 65535.0) * 100.0
            self.gas_pct = ((255 - self.raw[5]) / 255.0) * 100.0
            self.brake_pct = ((255 - self.raw[6]) / 255.0) * 100.0
            self.clutch_pct = ((255 - self.raw[11]) / 255.0) * 100.0

            w_btn, t_btn, red_btn = self.raw[1], self.raw[2], self.raw[0]
            is_g25, is_g27 = self.wheel_type == "G25", self.wheel_type == "G27"

            self.buttons = {
                "G25_Paddle_L": bool(w_btn & 0x02) if is_g25 else False,
                "G25_Paddle_R": bool(w_btn & 0x01) if is_g25 else False,
                "G25_A": bool(w_btn & 0x08) if is_g25 else False,
                "G25_B": bool(w_btn & 0x04) if is_g25 else False,
                "G27_Paddle_L": bool(w_btn & 0x02) if is_g27 else False,
                "G27_Paddle_R": bool(w_btn & 0x01) if is_g27 else False,
                "G27_1": bool(w_btn & 0x04) if is_g27 else False,
                "G27_2": bool(w_btn & 0x08) if is_g27 else False,
                "G27_3": bool(w_btn & 0x10) if is_g27 else False,
                "G27_4": bool(w_btn & 0x20) if is_g27 else False,
                "G27_5": bool(w_btn & 0x40) if is_g27 else False,
                "G27_6": bool(w_btn & 0x80) if is_g27 else False,
                "Top": bool(t_btn & 0x08),
                "Left": bool(t_btn & 0x10),
                "Bottom": bool(t_btn & 0x20),
                "Right": bool(t_btn & 0x40),
                "Red_1": bool(red_btn & 0x10),
                "Red_2": bool(red_btn & 0x20),
                "Red_3": bool(red_btn & 0x40),
                "Red_4": bool(red_btn & 0x80)
            }
            self.pov = red_btn & 0x0F
            self.gear = self._calc_gear(self.raw[8], self.raw[9])

    def _calc_gear(self, x: int, y: int) -> str:
        if 80 < y < 180: return "N"
        if x < 110: return "1" if y > 180 else "2"
        if 110 <= x <= 170: return "3" if y > 180 else "4"
        if 171 <= x <= 195: return "5" if y > 180 else "6"
        return "R" if (x > 195 and y < 80) else "N"


class LogitechRawController:
    """Thread-safe hardware controller layer."""
    def __init__(self) -> None:
        self.vendor_id = VENDOR_ID
        self.device: Optional[hid.device] = None
        self.wheel_type: Optional[str] = None
        self.lock = threading.Lock()

    def connect(self) -> bool:
        # Quick check without locking
        if self.device: return True

        # --- AUTO-UNLOCK FIX (NO LOCK) ---
        # We process the legacy unlock and sleep WITHOUT holding self.lock.
        # This allows the GUI to stay completely snappy while the wheel boots.
        try:
            legacy = hid.device()
            legacy.open(self.vendor_id, LEGACY_PID)
            legacy.set_nonblocking(1)
            legacy.write(bytes(G25_UNLOCK_PACKET))
            legacy.write(bytes(G27_UNLOCK_PACKET))
            legacy.close()
            time.sleep(1.2)
        except IOError:
            pass

        # Now look for the Native Device
        for pid, model in [(NATIVE_PID_G25, "G25"), (NATIVE_PID_G27, "G27")]:
            try:
                d = hid.device()
                d.open(self.vendor_id, pid)
                d.set_nonblocking(1)

                # Device opened successfully. NOW we lock to update state safely.
                with self.lock:
                    self.device = d
                    self.wheel_type = model
                return True
            except IOError:
                continue
        return False

    def check_hardware_presence(self) -> bool:
        """Asks the OS USB tree if the wheel is physically plugged in."""
        if not self.wheel_type: return False

        target_pid = NATIVE_PID_G25 if self.wheel_type == "G25" else NATIVE_PID_G27

        try:
            # hid.enumerate safely scans the USB bus without touching open handles
            for d in hid.enumerate(self.vendor_id):
                if d.get('product_id') == target_pid:
                    return True
        except Exception:
            pass

        # If the loop finishes and didn't return True, the wheel is physically gone
        self.disconnect()
        return False

    def disconnect(self) -> None:
        """Safely drop the handle and dispose of it without freezing the app."""
        dev = None
        # Step 1: Claim the device and wipe it from the app immediately
        with self.lock:
            if self.device:
                dev = self.device
                self.device = None
                self.wheel_type = None

        # Step 2: Throw the dangerous close() operation into a disposable thread.
        # If Windows deadlocks during the close, only this invisible thread dies!
        if dev:
            def safe_close(d):
                try: d.close()
                except Exception: pass
            threading.Thread(target=safe_close, args=(dev,), daemon=True).start()

    def send_command(self, packet: List[int]) -> bool:
        if not self.device: return False

        write_failed = False
        with self.lock:
            try:
                res = self.device.write(bytes(packet))
                if res is not None and res < 0:
                    write_failed = True
            except Exception:
                write_failed = True

        # Disconnect OUTSIDE the lock to prevent deadlocks
        if write_failed:
            self.disconnect()
            return False

        return True

    def read_input(self) -> Optional[bytes]:
        if not self.device: return None

        read_failed = False
        latest_data = None

        with self.lock:
            try:
                while True:
                    data = self.device.read(24)
                    if data: latest_data = bytes(data)
                    else: break
            except Exception:
                read_failed = True

        # Disconnect OUTSIDE the lock to prevent deadlocks
        if read_failed:
            self.disconnect()
            return None

        return latest_data

    def init_native_mode(self) -> bool:
        self.disconnect()
        try:
            legacy_device = hid.device()
            legacy_device.open(self.vendor_id, LEGACY_PID)
            legacy_device.set_nonblocking(1)
            legacy_device.write(bytes(G25_UNLOCK_PACKET))
            legacy_device.write(bytes(G27_UNLOCK_PACKET))
            legacy_device.close()
            return True
        except IOError:
            return False

    def set_degrees(self, degrees: int) -> bool:
        deg = max(40, min(900, int(degrees)))
        return self.send_command([0x00, 0xF8, 0x81, deg & 0xFF, (deg >> 8) & 0xFF, 0x00, 0x00, 0x00])

    def set_autocenter(self, strength_pct: int) -> bool:
        mag = int((max(0, min(100, int(strength_pct))) / 100.0) * 65535)
        return self.send_command([0x00, 0xFE, 0x0D, mag >> 13, mag >> 13, mag >> 8, 0x00, 0x00])

    def set_g27_leds(self, num_leds: int) -> bool:
        mask = sum(1 << i for i in range(min(num_leds, 5)))
        return self.send_command([0x00, 0x12, mask, 0x00, 0x00, 0x00, 0x00, 0x00])


class RawWheelConfigApp:
    def __init__(self, root: tk.Tk, wheel: LogitechRawController, cli_args: Optional[argparse.Namespace] = None) -> None:
        self.root = root
        self.wheel = wheel
        self.cli_args = cli_args

        self.root.title("Logitech Hardware Manager Dashboard")
        self.root.geometry("920x660")
        self.root.resizable(False, False)

        # UI State caching for Delta-Rendering (Performance optimization)
        self.ui_state = {
            "steer": -1.0, "gas": -1.0, "brake": -1.0, "clutch": -1.0,
            "gear": "", "pov": -1, "rpm": -1
        }

        # Threading mechanisms
        self.telemetry_queue = queue.Queue(maxsize=5)
        self.is_running = True
        self.hardware_thread = threading.Thread(target=self._hardware_worker, daemon=True)

        self.debug_window: Optional[tk.Toplevel] = None
        self.debug_labels = []
        self.gear_indicators = {}
        self.btn_indicators = {}
        self.rpm_indicators = []
        self.dpad_dots = {}

        self._build_ui()

        # Clean shutdown hook
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        if self.cli_args and self.cli_args.launch:
            self.root.iconify()

        self.root.after(200, self.delayed_init)

    def _build_ui(self) -> None:
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        self.left_pane = ttk.Frame(self.main_frame, width=280)
        self.left_pane.pack(side="left", fill="y", padx=(0, 10))
        self.right_pane = ttk.Frame(self.main_frame)
        self.right_pane.pack(side="right", fill="both", expand=True)

        self.setup_left_pane()
        self.setup_right_pane()

        self.status_label = ttk.Label(self.root, text="Starting engine...", font=("Arial", 9, "bold"))
        self.status_label.pack(side="bottom", pady=5)

    def delayed_init(self) -> None:
        if self.cli_args:
            if self.cli_args.profile: self.load_profile_from_path(self.cli_args.profile)
            if self.cli_args.degrees is not None: self.degrees_var.set(self.cli_args.degrees)
            if self.cli_args.autocenter is not None: self.centering_var.set(self.cli_args.autocenter)

        self.hardware_thread.start()
        self.apply_settings()

        if self.cli_args and self.cli_args.launch:
            try: os.startfile(self.cli_args.launch)
            except Exception as e: print(f"Launcher Error: {e}")

        self.process_queue()

    def on_closing(self):
        """Gracefully release hardware on exit to prevent wheel lockups."""
        self.is_running = False

        if self.wheel.device:
            # BUG FIX: Sending G27 LED commands to a G25 crashes its firmware!
            if self.wheel.wheel_type == "G27":
                self.wheel.set_g27_leds(0)

            # BUG FIX: Release the Force Feedback so it doesn't snap right and lock up
            self.wheel.set_autocenter(0)

        self.wheel.disconnect()
        # Give the USB bus 100ms to clear the final commands before killing the window
        self.root.after(100, self.root.destroy)

    def trigger_ffb_test(self):
        """Simulates a Sidewinder-style FFB test using safe raw commands."""
        if not self.wheel.device: return

        def _test_sequence():
            original_center = int(self.centering_var.get())

            # 1. The "Heavy Spring" Test
            # Turn the wheel slightly with your hands, then click the test button!
            self.wheel.set_autocenter(100)
            time.sleep(0.6)

            # 2. The "Rumble Strip" Test
            # Rapidly pulse the motors on and off to create a vibration
            for _ in range(8):
                self.wheel.set_autocenter(0)
                time.sleep(0.04)
                self.wheel.set_autocenter(80)
                time.sleep(0.04)

            # 3. Safely restore the user's slider settings
            self.wheel.set_autocenter(original_center)

        # Run in a disposable background thread so the GUI doesn't freeze during the time.sleep()
        threading.Thread(target=_test_sequence, daemon=True).start()

    def _hardware_worker(self):
        """Dedicated background thread for USB polling. Never blocks the GUI."""
        last_conn_attempt = 0
        last_heartbeat = 0
        was_connected = False

        while self.is_running:
            if not self.wheel.device:
                was_connected = False
                # Throttle reconnection attempts to once every 2 seconds
                if time.time() - last_conn_attempt > 2.0:
                    last_conn_attempt = time.time()
                    self.wheel.connect()
                time.sleep(0.5)
                continue

            if not was_connected:
                was_connected = True
                self.root.after(0, self.apply_settings)

            # --- BULLETPROOF UNPLUG DETECTION ---
            # We send a standard write command. If the wheel is unplugged,
            # the write fails, which safely triggers our new threaded disconnect.
            if time.time() - last_heartbeat > 1.0:
                last_heartbeat = time.time()
                # Sending the current autocenter value acts as a harmless ping
                if not self.wheel.set_autocenter(int(self.centering_var.get())):
                    was_connected = False
                    continue

            raw_bytes = self.wheel.read_input()
            if raw_bytes:
                telemetry = WheelTelemetry(raw_bytes, self.wheel.wheel_type)
                try:
                    while not self.telemetry_queue.empty():
                        self.telemetry_queue.get_nowait()
                    self.telemetry_queue.put_nowait(telemetry)
                except queue.Full:
                    pass
            time.sleep(0.01) # ~100Hz hardware poll rate

    def process_queue(self):
        """GUI thread: Fetches latest telemetry and paints the UI via Deltas."""
        try:
            telemetry: WheelTelemetry = self.telemetry_queue.get_nowait()
            self._render_ui(telemetry)
            self.status_label.config(text=f"Status: {telemetry.wheel_type} Connected (Active)", foreground="green")
        except queue.Empty:
            if not self.wheel.device:
                self.status_label.config(text="Status: Wheel NOT detected! (Sleeping...)", foreground="red")

        # ~60 FPS UI refresh
        self.root.after(16, self.process_queue)

    def _render_ui(self, t: WheelTelemetry):
        """Delta-renderer: Only updates widgets if the value actually changed."""
        self.update_debug_window(t.raw)

        if self.ui_state["steer"] != t.steering_pct:
            self.steer_bar['value'] = t.steering_pct
            self.steer_val_label.config(text=f"{t.steering_pct:05.1f}%")
            self.ui_state["steer"] = t.steering_pct

        is_g25, is_g27 = t.wheel_type == "G25", t.wheel_type == "G27"
        for btn_name, label_obj in self.btn_indicators.items():
            if btn_name in t.buttons:
                is_enabled = True
                if btn_name.startswith("G25_"): is_enabled = is_g25
                elif btn_name.startswith("G27_"): is_enabled = is_g27
                self.set_led(btn_name, t.buttons[btn_name], is_enabled)

        if self.ui_state["pov"] != t.pov:
            self.update_dpad_visual(t.pov)
            self.ui_state["pov"] = t.pov

        if self.ui_state["gear"] != t.gear:
            self.update_gear_visual(t.gear)
            self.ui_state["gear"] = t.gear

        # Process RPM Shift Lights
        num_leds = 0
        if is_g27:
            if t.gas_pct > 90: num_leds = 5
            elif t.gas_pct > 70: num_leds = 4
            elif t.gas_pct > 50: num_leds = 3
            elif t.gas_pct > 30: num_leds = 2
            elif t.gas_pct > 10: num_leds = 1

        if self.ui_state["rpm"] != num_leds:
            if is_g27: self.wheel.set_g27_leds(num_leds)
            self.update_rpm_led_visual(num_leds)
            self.ui_state["rpm"] = num_leds

        # Pedals
        if self.combined_pedals_var.get():
            combined = 50.0 + (t.gas_pct / 2.0) - (t.brake_pct / 2.0)
            if self.ui_state["gas"] != combined:
                self.gas_title.config(text="Combined")
                self.gas_lbl.config(text=f"{int(combined)}%")
                self.gas_bar['value'] = combined
                self.brake_title.config(text="Brake (Off)")
                self.brake_lbl.config(text="N/A")
                self.brake_bar['value'] = 0
                self.ui_state["gas"] = combined
        else:
            if self.ui_state["gas"] != t.gas_pct:
                self.gas_title.config(text="Gas")
                self.gas_bar['value'] = t.gas_pct
                self.gas_lbl.config(text=f"{int(t.gas_pct)}%")
                self.ui_state["gas"] = t.gas_pct

            if self.ui_state["brake"] != t.brake_pct:
                self.brake_title.config(text="Brake")
                self.brake_bar['value'] = t.brake_pct
                self.brake_lbl.config(text=f"{int(t.brake_pct)}%")
                self.ui_state["brake"] = t.brake_pct

        if self.ui_state["clutch"] != t.clutch_pct:
            self.clutch_bar['value'] = t.clutch_pct
            self.clutch_lbl.config(text=f"{int(t.clutch_pct)}%")
            self.ui_state["clutch"] = t.clutch_pct

    # --- UI Setup Methods ---

    def setup_left_pane(self) -> None:
        self.init_frame = ttk.LabelFrame(self.left_pane, text="Hardware Controls")
        self.init_frame.pack(fill="x", pady=(0, 10), ipady=5)

        ttk.Button(self.init_frame, text="Unlock Native Mode", command=self.trigger_native_mode).pack(padx=10, pady=5, fill="x")
        ttk.Button(self.init_frame, text="Open Raw USB Debugger", command=self.open_debug_window).pack(padx=10, pady=5, fill="x")

        self.ffb_frame = ttk.LabelFrame(self.left_pane, text="Force Feedback")
        self.ffb_frame.pack(fill="x", pady=(0, 10), ipady=5)
        self.centering_var = tk.DoubleVar(value=20)
        self.create_slider_row(self.ffb_frame, "Spring Strength", 0, 100, self.centering_var, "%")

        ttk.Button(self.ffb_frame, text="Test FFB (Rumble & Spring)", command=self.trigger_ffb_test).pack(padx=10, pady=(5, 0), fill="x")

        self.wheel_frame = ttk.LabelFrame(self.left_pane, text="Steering Wheel Settings")
        self.wheel_frame.pack(fill="x", pady=(5, 10), ipady=5)
        self.combined_pedals_var = tk.BooleanVar(value=False)
        self.combined_cb = ttk.Checkbutton(self.wheel_frame, text="Report Combined Pedals", variable=self.combined_pedals_var)
        self.combined_cb.pack(anchor="w", padx=10, pady=(5, 5))
        self.degrees_var = tk.DoubleVar(value=900)
        self.create_slider_row(self.wheel_frame, "Rotation", 40, 900, self.degrees_var, "°")

        ttk.Button(self.left_pane, text="Apply FFB & Rotation", command=self.apply_settings).pack(pady=(5, 10), fill="x")

        self.profile_frame = ttk.LabelFrame(self.left_pane, text="Profile Management")
        self.profile_frame.pack(fill="x", pady=(5, 10), ipady=5)
        ttk.Button(self.profile_frame, text="Load JSON Profile", command=self.load_profile).pack(padx=10, pady=4, fill="x")
        ttk.Button(self.profile_frame, text="Save JSON Profile", command=self.save_profile).pack(padx=10, pady=4, fill="x")

    def create_slider_row(self, parent, label_text, min_val, max_val, var, unit="%"):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=2)
        ttk.Label(frame, text=label_text, width=15).pack(side="left")

        entry_var = tk.StringVar(value=f"{int(var.get())}{unit}")
        entry = ttk.Entry(frame, width=6, justify="right", textvariable=entry_var)
        entry.pack(side="right")
        var.trace_add("write", lambda *args: entry_var.set(f"{int(var.get())}{unit}"))

        def on_entry_type(event):
            try:
                v = int(float(entry_var.get().replace(unit, "").strip()))
                var.set(max(min_val, min(max_val, v)))
            except ValueError:
                var.set(int(var.get()))

        entry.bind("<Return>", on_entry_type)
        entry.bind("<FocusOut>", on_entry_type)

        slider = ttk.Scale(frame, from_=min_val, to=max_val, variable=var)
        slider.pack(side="left", fill="x", expand=True, padx=5)
        return slider

    def setup_right_pane(self) -> None:
        self.top_dash = ttk.Frame(self.right_pane)
        self.top_dash.pack(fill="x", pady=(0, 10))

        steer_frame = ttk.LabelFrame(self.top_dash, text="Steering")
        steer_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.steer_val_label = ttk.Label(steer_frame, text="50.0%", font=("Courier", 11, "bold"))
        self.steer_val_label.pack(pady=(10, 0))
        self.steer_bar = ttk.Progressbar(steer_frame, orient="horizontal", length=180, mode="determinate")
        self.steer_bar.pack(pady=(5, 10), padx=10)

        pedals_frame = ttk.LabelFrame(self.top_dash, text="Pedals")
        pedals_frame.pack(side="right", fill="both", expand=True)
        self.gas_bar, self.gas_lbl, self.gas_title = self.create_vertical_bar(pedals_frame, "Gas")
        self.brake_bar, self.brake_lbl, self.brake_title = self.create_vertical_bar(pedals_frame, "Brake")
        self.clutch_bar, self.clutch_lbl, self.clutch_title = self.create_vertical_bar(pedals_frame, "Clutch")

        self.bot_dash = ttk.Frame(self.right_pane)
        self.bot_dash.pack(fill="both", expand=True)

        gear_frame = ttk.LabelFrame(self.bot_dash, text="H-Pattern Gearbox")
        gear_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.gear_canvas = tk.Canvas(gear_frame, width=180, height=150, bg="#222")
        self.gear_canvas.pack(pady=10)
        self.draw_h_pattern()

        btn_frame = ttk.LabelFrame(self.bot_dash, text="Hardware Buttons")
        btn_frame.pack(side="right", fill="both", expand=True)
        self.setup_button_indicators(btn_frame)

    def draw_h_pattern(self):
        c = self.gear_canvas
        c.create_line(40, 30, 40, 120, fill="gray", width=4)
        c.create_line(90, 30, 90, 120, fill="gray", width=4)
        c.create_line(140, 30, 140, 120, fill="gray", width=4)
        c.create_line(40, 75, 140, 75, fill="gray", width=4)
        c.create_line(140, 75, 170, 75, fill="gray", width=4)
        c.create_line(170, 75, 170, 120, fill="gray", width=4)
        coords = {"1": (40,30), "2": (40,120), "3": (90,30), "4": (90,120),
                  "5": (140,30), "6": (140,120), "R": (170,120), "N": (90,75)}
        for gear, (x, y) in coords.items():
            circle = c.create_oval(x-12, y-12, x+12, y+12, fill="#444", outline="white")
            c.create_text(x, y, text=gear, fill="white", font=("Arial", 10, "bold"))
            self.gear_indicators[gear] = circle

    def setup_button_indicators(self, parent):
        ttk.Label(parent, text="Wheel (G25):", font=("Arial", 9, "bold")).grid(row=0, column=0, pady=2, padx=5, sticky="w")
        self.btn_indicators["G25_Paddle_L"] = self.make_led(parent, "L-Paddle", 0, 1)
        self.btn_indicators["G25_Paddle_R"] = self.make_led(parent, "R-Paddle", 0, 2)
        self.btn_indicators["G25_A"] = self.make_led(parent, "Btn A", 0, 3)
        self.btn_indicators["G25_B"] = self.make_led(parent, "Btn B", 0, 4)

        ttk.Label(parent, text="Wheel (G27):", font=("Arial", 9, "bold")).grid(row=1, column=0, pady=2, padx=5, sticky="w")
        g27_frame = ttk.Frame(parent)
        g27_frame.grid(row=1, column=1, columnspan=4, sticky="w")
        self.btn_indicators["G27_Paddle_L"] = self.make_led(g27_frame, "L-Pad", 0, 0, width=5)
        self.btn_indicators["G27_Paddle_R"] = self.make_led(g27_frame, "R-Pad", 0, 1, width=5)
        for i in range(1, 7):
            self.btn_indicators[f"G27_{i}"] = self.make_led(g27_frame, f"B{i}", 0, i+1, width=3)

        ttk.Label(parent, text="G27 RPM LEDs:", font=("Arial", 9, "bold")).grid(row=2, column=0, pady=2, padx=5, sticky="w")
        rpm_frame = ttk.Frame(parent)
        rpm_frame.grid(row=2, column=1, columnspan=4, sticky="w")
        self.rpm_colors_off = ["#1a331a", "#1a331a", "#33261a", "#33261a", "#331a1a"]
        self.rpm_colors_on = ["#00ff00", "#00ff00", "#ff9900", "#ff9900", "#ff0000"]
        for i in range(5):
            lbl = tk.Label(rpm_frame, text="●", fg=self.rpm_colors_off[i], bg="#222", font=("Arial", 12, "bold"), width=3)
            lbl.pack(side="left", padx=1)
            self.rpm_indicators.append(lbl)

        ttk.Label(parent, text="Shifter:", font=("Arial", 9, "bold")).grid(row=3, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Top"] = self.make_led(parent, "Top", 3, 1)
        self.btn_indicators["Left"] = self.make_led(parent, "Left", 3, 2)
        self.btn_indicators["Bottom"] = self.make_led(parent, "Bottom", 3, 3)
        self.btn_indicators["Right"] = self.make_led(parent, "Right", 3, 4)

        ttk.Label(parent, text="Red Row:", font=("Arial", 9, "bold")).grid(row=4, column=0, pady=5, padx=5, sticky="w")
        for i in range(1, 5):
            self.btn_indicators[f"Red_{i}"] = self.make_led(parent, f"Red {i}", 4, i)

        ttk.Label(parent, text="D-Pad POV:", font=("Arial", 9, "bold")).grid(row=5, column=0, pady=10, padx=5, sticky="w")
        self.dpad_canvas = tk.Canvas(parent, width=80, height=80, bg="#222", highlightthickness=0)
        self.dpad_canvas.grid(row=5, column=1, columnspan=4, pady=5)
        self.dpad_canvas.create_oval(10, 10, 70, 70, fill="#333", outline="#111", width=2)
        self.dpad_canvas.create_oval(30, 30, 50, 50, fill="#2a2a2a", outline="#111")
        coords = {0:(40,18), 1:(55,25), 2:(62,40), 3:(55,55), 4:(40,62), 5:(25,55), 6:(18,40), 7:(25,25)}
        for pov_val, (cx, cy) in coords.items():
            self.dpad_dots[pov_val] = self.dpad_canvas.create_oval(cx-5, cy-5, cx+5, cy+5, fill="#222", outline="#111")

    def update_dpad_visual(self, pov: int):
        for dot_id in self.dpad_dots.values():
            self.dpad_canvas.itemconfig(dot_id, fill="#222", outline="#111")
        if pov in self.dpad_dots:
            self.dpad_canvas.itemconfig(self.dpad_dots[pov], fill="red", outline="white")

    def update_rpm_led_visual(self, active_count: int):
        for i in range(5):
            color = self.rpm_colors_on[i] if i < active_count else self.rpm_colors_off[i]
            if self.rpm_indicators[i].cget("fg") != color:
                self.rpm_indicators[i].config(fg=color)

    def make_led(self, parent, text, r, c, width=8):
        lbl = tk.Label(parent, text=text, bg="#555", fg="white", width=width, relief="ridge")
        lbl.grid(row=r, column=c, padx=2, pady=2)
        return lbl

    def set_led(self, name, is_on, enabled=True):
        color = "red" if is_on else "#555"
        if not enabled: color = "#2c2c2c"
        if self.btn_indicators[name].cget("bg") != color:
            self.btn_indicators[name].config(bg=color, fg="white" if enabled else "#555")

    def update_gear_visual(self, active_gear: str):
        for gear, oval_id in self.gear_indicators.items():
            color = "red" if gear == active_gear else "#444"
            if self.gear_canvas.itemcget(oval_id, "fill") != color:
                self.gear_canvas.itemconfig(oval_id, fill=color)

    def create_vertical_bar(self, parent, label_text):
        frame = ttk.Frame(parent)
        frame.pack(side="left", expand=True, fill="y", pady=10)
        bar = ttk.Progressbar(frame, orient="vertical", length=90, mode="determinate")
        bar.pack(pady=(0, 5))
        val_label = ttk.Label(frame, text="0%", font=("Courier", 9))
        val_label.pack()
        ttk.Label(frame, text=label_text, font=("Arial", 9, "bold")).pack()
        return bar, val_label, frame.winfo_children()[-1]

    def load_profile(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Config", "*.json")])
        if path: self.load_profile_from_path(path)

    def load_profile_from_path(self, path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if "degrees" in data: self.degrees_var.set(data["degrees"])
            if "autocenter" in data: self.centering_var.set(data["autocenter"])
            if "combined_pedals" in data: self.combined_pedals_var.set(data["combined_pedals"])
            self.apply_settings()
        except Exception as e:
            print(f"Profile Error: {e}")

    def save_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Config", "*.json")])
        if path:
            with open(path, "w") as f:
                json.dump({"degrees": int(self.degrees_var.get()), "autocenter": int(self.centering_var.get()), "combined_pedals": self.combined_pedals_var.get()}, f, indent=4)

    def trigger_native_mode(self):
        self.wheel.init_native_mode()
        self.root.after(2500, self.apply_settings)

    def apply_settings(self):
        self.wheel.set_degrees(int(self.degrees_var.get()))
        self.wheel.set_autocenter(int(self.centering_var.get()))

    def open_debug_window(self):
        if self.debug_window and self.debug_window.winfo_exists():
            self.debug_window.lift()
            return
        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Raw USB")
        self.debug_window.geometry("350x450")
        f = ttk.Frame(self.debug_window)
        f.pack(fill="both", expand=True, padx=10, pady=5)
        for i in range(16):
            ttk.Label(f, text=f"data[{i}]", font=("Courier", 9)).grid(row=i, column=0)
            ld, lh, lb = [ttk.Label(f, text=t, font=("Courier", 9)) for t in ("000", "0x00", "00000000")]
            ld.grid(row=i, column=1); lh.grid(row=i, column=2); lb.grid(row=i, column=3)
            self.debug_labels.append((ld, lh, lb))

    def update_debug_window(self, data: bytes):
        if self.debug_window and self.debug_window.winfo_exists():
            for i in range(min(len(data), 16)):
                self.debug_labels[i][0].config(text=f"{data[i]:03d}")
                self.debug_labels[i][1].config(text=f"0x{data[i]:02X}")
                self.debug_labels[i][2].config(text=f"{data[i]:08b}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--degrees", type=int)
    parser.add_argument("--autocenter", type=int)
    parser.add_argument("--profile", type=str)
    parser.add_argument("--launch", type=str)
    args, _ = parser.parse_known_args()

    root = tk.Tk()
    app = RawWheelConfigApp(root, LogitechRawController(), cli_args=args)
    root.mainloop()
