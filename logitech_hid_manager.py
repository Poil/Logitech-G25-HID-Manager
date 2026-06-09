import hid
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import json
import os
import argparse

# USB IDs for Logitech G25 & G27
VENDOR_ID = 0x046D
NATIVE_PID_G25 = 0xC299
NATIVE_PID_G27 = 0xC29B
LEGACY_PID = 0xC294

class LogitechRawController:
    def __init__(self):
        self.vendor_id = VENDOR_ID
        self.device = None
        self.wheel_type = None

    def connect(self):
        if self.device: return True

        # Try finding G25
        try:
            d = hid.device()
            d.open(self.vendor_id, NATIVE_PID_G25)
            d.set_nonblocking(1)
            self.device = d
            self.wheel_type = "G25"
            return True
        except IOError:
            pass

        # Try finding G27
        try:
            d = hid.device()
            d.open(self.vendor_id, NATIVE_PID_G27)
            d.set_nonblocking(1)
            self.device = d
            self.wheel_type = "G27"
            return True
        except IOError:
            pass

        self.device = None
        self.wheel_type = None
        return False

    def disconnect(self):
        if self.device:
            try: self.device.close()
            except: pass
            self.device = None
            self.wheel_type = None

    def send_command(self, packet):
        if not self.connect(): return False
        try:
            self.device.write(packet)
            return True
        except IOError:
            self.disconnect()
            return False

    def read_input(self):
        if not self.connect(): return None
        try:
            latest_data = None
            while True:
                # Drains the USB buffer by reading until it's empty
                data = self.device.read(24)
                if data:
                    latest_data = data
                else:
                    break # Buffer is empty, we have the newest packet!
            return latest_data
        except IOError:
            self.disconnect()
            return None

    def init_native_mode(self):
        self.disconnect()
        try:
            legacy_device = hid.device()
            legacy_device.open(self.vendor_id, LEGACY_PID)
            legacy_device.set_nonblocking(1)
            # Send G25 unlock packet
            legacy_device.write([0x00, 0xF8, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00])
            # Send G27 unlock packet
            legacy_device.write([0x00, 0xF8, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00])
            legacy_device.close()
            return True
        except IOError:
            return False

    def set_degrees(self, degrees):
        degrees = max(40, min(900, int(degrees)))
        low_byte = degrees & 0xFF
        high_byte = (degrees >> 8) & 0xFF
        return self.send_command([0x00, 0xF8, 0x81, low_byte, high_byte, 0x00, 0x00, 0x00])

    def set_autocenter(self, strength_percent):
        mag = int((max(0, min(100, int(strength_percent))) / 100.0) * 65535)
        return self.send_command([0x00, 0xFE, 0x0D, mag >> 13, mag >> 13, mag >> 8, 0x00, 0x00])

    def set_g27_leds(self, num_leds):
        # Maps 0-5 active LEDs into the hardware bitmask expected by G27 firmware
        mask = 0
        if num_leds >= 1: mask |= 0x01
        if num_leds >= 2: mask |= 0x02
        if num_leds >= 3: mask |= 0x04
        if num_leds >= 4: mask |= 0x08
        if num_leds >= 5: mask |= 0x10
        return self.send_command([0x00, 0x12, mask, 0x00, 0x00, 0x00, 0x00, 0x00])


class RawWheelConfigApp:
    def __init__(self, root, wheel, cli_args=None):
        self.root = root
        self.wheel = wheel
        self.cli_args = cli_args
        self.root.title("Logitech Hardware Manager Dashboard")
        self.root.geometry("920x660")
        self.root.resizable(False, False)

        self.debug_window = None
        self.debug_labels = []
        self.gear_indicators = {}
        self.btn_indicators = {}
        self.rpm_indicators = []
        self.dpad_dots = {}
        self.last_rpm_leds = -1

        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        self.left_pane = ttk.Frame(self.main_frame, width=280)
        self.left_pane.pack(side="left", fill="y", padx=(0, 10))

        self.right_pane = ttk.Frame(self.main_frame)
        self.right_pane.pack(side="right", fill="both", expand=True)

        self.setup_left_pane()
        self.setup_right_pane()

        self.status_label = ttk.Label(self.root, text="Checking connection...", font=("Arial", 9, "bold"))
        self.status_label.pack(side="bottom", pady=5)

        # Handle headless window visibility state if executed via --launch CLI
        if self.cli_args and self.cli_args.launch:
            self.root.iconify()

        self.root.after(500, self.delayed_init)

    def delayed_init(self):
        # Process programmatic Profile configurations first if specified
        if self.cli_args:
            if self.cli_args.profile:
                self.load_profile_from_path(self.cli_args.profile)

            # Direct CLI flags prioritize over conflicting Profile values
            if self.cli_args.degrees is not None:
                self.degrees_var.set(self.cli_args.degrees)
            if self.cli_args.autocenter is not None:
                self.centering_var.set(self.cli_args.autocenter)

        self.apply_settings()

        # Handle URI/Exec target instantiation
        if self.cli_args and self.cli_args.launch:
            try:
                os.startfile(self.cli_args.launch)
            except Exception as e:
                print(f"CLI Launcher Error: {e}")

        self.hardware_loop()

    def setup_left_pane(self):
        self.init_frame = ttk.LabelFrame(self.left_pane, text="Hardware Controls")
        self.init_frame.pack(fill="x", pady=(0, 10), ipady=5)

        ttk.Button(self.init_frame, text="Unlock Native Mode", command=self.trigger_native_mode).pack(padx=10, pady=5, fill="x")
        ttk.Button(self.init_frame, text="Open Raw USB Debugger", command=self.open_debug_window).pack(padx=10, pady=5, fill="x")

        self.ffb_frame = ttk.LabelFrame(self.left_pane, text="Force Feedback")
        self.ffb_frame.pack(fill="x", pady=(0, 10), ipady=5)
        self.centering_var = tk.DoubleVar(value=20)
        self.create_slider_row(self.ffb_frame, "Spring Strength", 0, 100, self.centering_var, "%")

        self.wheel_frame = ttk.LabelFrame(self.left_pane, text="Steering Wheel Settings")
        self.wheel_frame.pack(fill="x", pady=(5, 10), ipady=5)

        self.combined_pedals_var = tk.BooleanVar(value=False)
        self.combined_cb = ttk.Checkbutton(self.wheel_frame, text="Report Combined Pedals", variable=self.combined_pedals_var)
        self.combined_cb.pack(anchor="w", padx=10, pady=(5, 5))

        self.degrees_var = tk.DoubleVar(value=900)
        self.create_slider_row(self.wheel_frame, "Rotation", 40, 900, self.degrees_var, "°")

        ttk.Button(self.left_pane, text="Apply FFB & Rotation", command=self.apply_settings).pack(pady=(5, 10), fill="x")

        # Profiles Section
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

        def on_var_change(*args):
            entry_var.set(f"{int(var.get())}{unit}")
        var.trace_add("write", on_var_change)

        def on_entry_type(event):
            text = entry_var.get().replace(unit, "").strip()
            try:
                v = int(float(text))
                var.set(max(min_val, min(max_val, v)))
            except ValueError:
                var.set(int(var.get()))

        entry.bind("<Return>", on_entry_type)
        entry.bind("<FocusOut>", on_entry_type)

        slider = ttk.Scale(frame, from_=min_val, to=max_val, variable=var)
        slider.pack(side="left", fill="x", expand=True, padx=5)
        return slider

    def setup_right_pane(self):
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
            text = c.create_text(x, y, text=gear, fill="white", font=("Arial", 10, "bold"))
            self.gear_indicators[gear] = circle

    def setup_button_indicators(self, parent):
        # ROW 0: G25 Rim Mapping
        lbl_w1 = ttk.Label(parent, text="Wheel (G25):", font=("Arial", 9, "bold"))
        lbl_w1.grid(row=0, column=0, pady=2, padx=5, sticky="w")
        self.btn_indicators["G25_Paddle_L"] = self.make_led(parent, "L-Paddle", 0, 1)
        self.btn_indicators["G25_Paddle_R"] = self.make_led(parent, "R-Paddle", 0, 2)
        self.btn_indicators["G25_A"] = self.make_led(parent, "Btn A", 0, 3)
        self.btn_indicators["G25_B"] = self.make_led(parent, "Btn B", 0, 4)

        # ROW 1: G27 Rim Mapping
        lbl_w2 = ttk.Label(parent, text="Wheel (G27):", font=("Arial", 9, "bold"))
        lbl_w2.grid(row=1, column=0, pady=2, padx=5, sticky="w")

        g27_frame = ttk.Frame(parent)
        g27_frame.grid(row=1, column=1, columnspan=4, sticky="w")

        self.btn_indicators["G27_Paddle_L"] = self.make_led(g27_frame, "L-Pad", 0, 0, width=5)
        self.btn_indicators["G27_Paddle_R"] = self.make_led(g27_frame, "R-Pad", 0, 1, width=5)
        self.btn_indicators["G27_1"] = self.make_led(g27_frame, "B1", 0, 2, width=3)
        self.btn_indicators["G27_2"] = self.make_led(g27_frame, "B2", 0, 3, width=3)
        self.btn_indicators["G27_3"] = self.make_led(g27_frame, "B3", 0, 4, width=3)
        self.btn_indicators["G27_4"] = self.make_led(g27_frame, "B4", 0, 5, width=3)
        self.btn_indicators["G27_5"] = self.make_led(g27_frame, "B5", 0, 6, width=3)
        self.btn_indicators["G27_6"] = self.make_led(g27_frame, "B6", 0, 7, width=3)

        # ROW 2: G27 RPM LED Mock Arrays
        lbl_rpm = ttk.Label(parent, text="G27 RPM LEDs:", font=("Arial", 9, "bold"))
        lbl_rpm.grid(row=2, column=0, pady=2, padx=5, sticky="w")

        rpm_frame = ttk.Frame(parent)
        rpm_frame.grid(row=2, column=1, columnspan=4, sticky="w")
        self.rpm_colors_off = ["#1a331a", "#1a331a", "#33261a", "#33261a", "#331a1a"]
        self.rpm_colors_on = ["#00ff00", "#00ff00", "#ff9900", "#ff9900", "#ff0000"]
        for i in range(5):
            lbl = tk.Label(rpm_frame, text="●", fg=self.rpm_colors_off[i], bg="#222", font=("Arial", 12, "bold"), width=3)
            lbl.pack(side="left", padx=1)
            self.rpm_indicators.append(lbl)

        # ROW 3: Shifter Buttons
        shifter_lbl = ttk.Label(parent, text="Shifter:", font=("Arial", 9, "bold"))
        shifter_lbl.grid(row=3, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Top"] = self.make_led(parent, "Top", 3, 1)
        self.btn_indicators["Left"] = self.make_led(parent, "Left", 3, 2)
        self.btn_indicators["Bottom"] = self.make_led(parent, "Bottom", 3, 3)
        self.btn_indicators["Right"] = self.make_led(parent, "Right", 3, 4)

        # ROW 4: Base Button Matrix
        red_lbl = ttk.Label(parent, text="Red Row:", font=("Arial", 9, "bold"))
        red_lbl.grid(row=4, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Red_1"] = self.make_led(parent, "Red 1", 4, 1)
        self.btn_indicators["Red_2"] = self.make_led(parent, "Red 2", 4, 2)
        self.btn_indicators["Red_3"] = self.make_led(parent, "Red 3", 4, 3)
        self.btn_indicators["Red_4"] = self.make_led(parent, "Red 4", 4, 4)

        # ROW 5: Shifter D-Pad Directional Indicators
        dpad_lbl = ttk.Label(parent, text="D-Pad POV:", font=("Arial", 9, "bold"))
        dpad_lbl.grid(row=5, column=0, pady=10, padx=5, sticky="w")

        self.dpad_canvas = tk.Canvas(parent, width=80, height=80, bg="#222", highlightthickness=0)
        self.dpad_canvas.grid(row=5, column=1, columnspan=4, pady=5)

        self.dpad_canvas.create_oval(10, 10, 70, 70, fill="#333", outline="#111", width=2)
        self.dpad_canvas.create_oval(30, 30, 50, 50, fill="#2a2a2a", outline="#111")

        self.dpad_dots = {}
        coords = {
            0: (40, 18), 1: (55, 25), 2: (62, 40), 3: (55, 55),
            4: (40, 62), 5: (25, 55), 6: (18, 40), 7: (25, 25)
        }
        for pov_val, (cx, cy) in coords.items():
            r = 5
            dot = self.dpad_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="#222", outline="#111")
            self.dpad_dots[pov_val] = dot

    def update_dpad_visual(self, pov):
        for dot_id in self.dpad_dots.values():
            self.dpad_canvas.itemconfig(dot_id, fill="#222", outline="#111")
        if pov in self.dpad_dots:
            self.dpad_canvas.itemconfig(self.dpad_dots[pov], fill="red", outline="white")

    def update_rpm_led_visual(self, active_count):
        for i in range(5):
            color = self.rpm_colors_on[i] if i < active_count else self.rpm_colors_off[i]
            if self.rpm_indicators[i].cget("fg") != color:
                self.rpm_indicators[i].config(fg=color)

    def make_led(self, parent, text, r, c, width=8):
        lbl = tk.Label(parent, text=text, bg="#555", fg="white", width=width, relief="ridge")
        lbl.grid(row=r, column=c, padx=2, pady=2)
        return lbl

    def set_led(self, name, is_on, enabled=True):
        if not enabled:
            color = "#2c2c2c"
            fg_color = "#555"
        else:
            color = "red" if is_on else "#555"
            fg_color = "white"

        lbl = self.btn_indicators[name]
        if lbl.cget("bg") != color:
            lbl.config(bg=color, fg=fg_color)

    def update_gear_visual(self, active_gear):
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
        title_label = ttk.Label(frame, text=label_text, font=("Arial", 9, "bold"))
        title_label.pack()
        return bar, val_label, title_label

    def load_profile(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Configuration Profiles", "*.json")])
        if path:
            self.load_profile_from_path(path)

    def load_profile_from_path(self, path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if "degrees" in data: self.degrees_var.set(data["degrees"])
            if "autocenter" in data: self.centering_var.set(data["autocenter"])
            if "combined_pedals" in data: self.combined_pedals_var.set(data["combined_pedals"])
            self.apply_settings()
            self.status_label.config(text=f"Loaded Profile: {os.path.basename(path)}", foreground="green")
        except Exception as e:
            self.status_label.config(text=f"Profile Error: {e}", foreground="red")

    def save_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Configuration Profiles", "*.json")])
        if path:
            try:
                data = {
                    "degrees": int(self.degrees_var.get()),
                    "autocenter": int(self.centering_var.get()),
                    "combined_pedals": self.combined_pedals_var.get()
                }
                with open(path, "w") as f:
                    json.dump(data, f, indent=4)
                self.status_label.config(text=f"Saved Profile: {os.path.basename(path)}", foreground="green")
            except Exception as e:
                self.status_label.config(text=f"Save Error: {e}", foreground="red")

    def trigger_native_mode(self):
        if self.wheel.init_native_mode():
            self.root.after(2500, self.apply_settings)
        else:
            if self.wheel.connect():
                self.degrees_var.set(900)
                self.apply_settings()

    def apply_settings(self):
        deg = int(self.degrees_var.get())
        strength = int(self.centering_var.get())
        self.wheel.set_degrees(deg)
        self.wheel.set_autocenter(strength)

    def open_debug_window(self):
        if self.debug_window is not None and self.debug_window.winfo_exists():
            self.debug_window.lift()
            return
        self.debug_window = tk.Toplevel(self.root)
        self.debug_window.title("Raw USB Debugger")
        self.debug_window.geometry("350x450")
        table_frame = ttk.Frame(self.debug_window)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.debug_labels = []
        for i in range(16):
            lbl_byte = ttk.Label(table_frame, text=f"data[{i}]", font=("Courier", 9))
            lbl_byte.grid(row=i, column=0)
            lbl_dec = ttk.Label(table_frame, text="000", font=("Courier", 9))
            lbl_dec.grid(row=i, column=1)
            lbl_hex = ttk.Label(table_frame, text="0x00", font=("Courier", 9))
            lbl_hex.grid(row=i, column=2)
            lbl_bin = ttk.Label(table_frame, text="00000000", font=("Courier", 9))
            lbl_bin.grid(row=i, column=3)
            self.debug_labels.append((lbl_dec, lbl_hex, lbl_bin))

    def update_debug_window(self, data):
        if self.debug_window is not None and self.debug_window.winfo_exists():
            for i in range(min(len(data), 16)):
                val = data[i]
                self.debug_labels[i][0].config(text=f"{val:03d}")
                self.debug_labels[i][1].config(text=f"0x{val:02X}")
                self.debug_labels[i][2].config(text=f"{val:08b}")

    def hardware_loop(self):
        try:
            if self.wheel.connect():
                is_g25 = self.wheel.wheel_type == "G25"
                is_g27 = self.wheel.wheel_type == "G27"

                self.status_label.config(text=f"Status: {self.wheel.wheel_type} Connected", foreground="green")
                data = self.wheel.read_input()

                if data:
                    self.update_debug_window(data)

                    if len(data) >= 5:
                        steering_raw = data[3] | (data[4] << 8)
                        steering_pct = (steering_raw / 65535.0) * 100
                        self.steer_bar['value'] = steering_pct
                        self.steer_val_label.config(text=f"{steering_pct:05.1f}%")

                    if len(data) >= 11:
                        w_btn = data[1]

                        # --- G25 State Mapping ---
                        self.set_led("G25_Paddle_L", w_btn & 0x02, is_g25)
                        self.set_led("G25_Paddle_R", w_btn & 0x01, is_g25)
                        self.set_led("G25_A", w_btn & 0x08, is_g25)
                        self.set_led("G25_B", w_btn & 0x04, is_g25)

                        # --- G27 State Mapping ---
                        self.set_led("G27_Paddle_L", w_btn & 0x02, is_g27)
                        self.set_led("G27_Paddle_R", w_btn & 0x01, is_g27)
                        self.set_led("G27_1", w_btn & 0x04, is_g27)
                        self.set_led("G27_2", w_btn & 0x08, is_g27)
                        self.set_led("G27_3", w_btn & 0x10, is_g27)
                        self.set_led("G27_4", w_btn & 0x20, is_g27)
                        self.set_led("G27_5", w_btn & 0x40, is_g27)
                        self.set_led("G27_6", w_btn & 0x80, is_g27)

                        t_btn = data[2]
                        self.set_led("Top", t_btn & 0x08, True)
                        self.set_led("Left", t_btn & 0x10, True)
                        self.set_led("Bottom", t_btn & 0x20, True)
                        self.set_led("Right", t_btn & 0x40, True)

                        red_btn = data[0]
                        self.set_led("Red_1", red_btn & 0x10, True)
                        self.set_led("Red_2", red_btn & 0x20, True)
                        self.set_led("Red_3", red_btn & 0x40, True)
                        self.set_led("Red_4", red_btn & 0x80, True)

                        pov = red_btn & 0x0F
                        self.update_dpad_visual(pov)

                        x = data[8]
                        y = data[9]

                        gear = "N"
                        if 80 < y < 180: gear = "N"
                        elif x < 110: gear = "1" if y > 180 else "2"
                        elif 110 <= x <= 170: gear = "3" if y > 180 else "4"
                        elif 171 <= x <= 195: gear = "5" if y > 180 else "6"
                        elif x > 195: gear = "R" if y < 80 else "N"

                        self.update_gear_visual(gear)

                    if len(data) >= 7:
                        gas_pct = ((255 - data[5]) / 255.0) * 100
                        brake_pct = ((255 - data[6]) / 255.0) * 100

                        # Calculate and sync RPM Shift Lights dynamically via Gas percentage
                        if is_g27:
                            num_leds = 0
                            if gas_pct > 90: num_leds = 5
                            elif gas_pct > 70: num_leds = 4
                            elif gas_pct > 50: num_leds = 3
                            elif gas_pct > 30: num_leds = 2
                            elif gas_pct > 10: num_leds = 1

                            if num_leds != self.last_rpm_leds:
                                self.wheel.set_g27_leds(num_leds)
                                self.last_rpm_leds = num_leds
                            self.update_rpm_led_visual(num_leds)
                        else:
                            self.update_rpm_led_visual(0)

                        if self.combined_pedals_var.get():
                            combined_pct = 50.0 + (gas_pct / 2.0) - (brake_pct / 2.0)
                            self.gas_title.config(text="Combined")
                            self.gas_lbl.config(text=f"{int(combined_pct)}%")
                            self.gas_bar['value'] = combined_pct
                            self.brake_title.config(text="Brake (Off)")
                            self.brake_lbl.config(text="N/A")
                            self.brake_bar['value'] = 0
                        else:
                            self.gas_title.config(text="Gas")
                            self.gas_bar['value'] = gas_pct
                            self.gas_lbl.config(text=f"{int(gas_pct)}%")
                            self.brake_title.config(text="Brake")
                            self.brake_bar['value'] = brake_pct
                            self.brake_lbl.config(text=f"{int(brake_pct)}%")

                    if len(data) >= 12:
                        clutch_pct = ((255 - data[11]) / 255.0) * 100
                        self.clutch_bar['value'] = clutch_pct
                        self.clutch_lbl.config(text=f"{int(clutch_pct)}%")
            else:
                self.status_label.config(text="Status: Wheel NOT detected!", foreground="red")
                self.update_rpm_led_visual(0)
                self.last_rpm_leds = -1

        except Exception as e:
            self.status_label.config(text=f"Error: {e}", foreground="red")

        finally:
            self.root.after(15, self.hardware_loop)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Logitech Custom HID Driver Manager (G25/G27)")
    parser.add_argument("--degrees", type=int, help="Override steering threshold rotation degrees (40-900)")
    parser.add_argument("--autocenter", type=int, help="Override centering strength percentage (0-100)")
    parser.add_argument("--profile", type=str, help="Path to pre-configured JSON configuration profile")
    parser.add_argument("--launch", type=str, help="Application executable path target or game protocol URI string")

    # Parse known args to eliminate formatting errors when packaging via PyInstaller
    args, unknown = parser.parse_known_args()

    root = tk.Tk()
    app = RawWheelConfigApp(root, LogitechRawController(), cli_args=args)
    root.mainloop()
