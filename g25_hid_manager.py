import hid
import tkinter as tk
from tkinter import ttk

# USB IDs for Logitech G25
VENDOR_ID = 0x046D
NATIVE_PID = 0xC299
LEGACY_PID = 0xC294

class G25RawController:
    def __init__(self):
        self.vendor_id = VENDOR_ID
        self.product_id = NATIVE_PID
        self.device = None

    def connect(self):
        if self.device: return True
        try:
            self.device = hid.device()
            self.device.open(self.vendor_id, self.product_id)
            self.device.set_nonblocking(1)
            return True
        except IOError:
            self.device = None
            return False

    def disconnect(self):
        if self.device:
            try: self.device.close()
            except: pass
            self.device = None

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
            packet = [0x00, 0xF8, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00]
            legacy_device.write(packet)
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

class RawWheelConfigApp:
    def __init__(self, root, wheel):
        self.root = root
        self.wheel = wheel
        self.root.title("G25 Hardware Manager Dashboard")
        self.root.geometry("850x580")
        self.root.resizable(False, False)

        self.debug_window = None
        self.debug_labels = []
        self.gear_indicators = {}
        self.btn_indicators = {}
        self.dpad_dots = {}

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

        self.root.after(500, self.delayed_init)

    def delayed_init(self):
        self.apply_settings()
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

        # --- NEW: COMBINED PEDALS CHECKBOX ---
        self.combined_pedals_var = tk.BooleanVar(value=False)
        self.combined_cb = ttk.Checkbutton(self.wheel_frame, text="Report Combined Pedals", variable=self.combined_pedals_var)
        self.combined_cb.pack(anchor="w", padx=10, pady=(5, 5))

        self.degrees_var = tk.DoubleVar(value=900)
        self.create_slider_row(self.wheel_frame, "Rotation", 40, 900, self.degrees_var, "°")

        ttk.Button(self.left_pane, text="Apply FFB & Rotation", command=self.apply_settings).pack(pady=(10, 0), fill="x")

    def create_slider_row(self, parent, label_text, min_val, max_val, var, unit="%"):
        # --- RESTORED: THE TEXT INPUT BOXES! ---
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
        wheel_lbl = ttk.Label(parent, text="Wheel:", font=("Arial", 9, "bold"))
        wheel_lbl.grid(row=0, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Paddle_L"] = self.make_led(parent, "L-Paddle", 0, 1)
        self.btn_indicators["Paddle_R"] = self.make_led(parent, "R-Paddle", 0, 2)
        self.btn_indicators["Btn_A"] = self.make_led(parent, "Btn 1 (A)", 0, 3)
        self.btn_indicators["Btn_B"] = self.make_led(parent, "Btn 2 (B)", 0, 4)

        shifter_lbl = ttk.Label(parent, text="Shifter:", font=("Arial", 9, "bold"))
        shifter_lbl.grid(row=1, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Top"] = self.make_led(parent, "Top", 1, 1)
        self.btn_indicators["Left"] = self.make_led(parent, "Left", 1, 2)
        self.btn_indicators["Bottom"] = self.make_led(parent, "Bottom", 1, 3)
        self.btn_indicators["Right"] = self.make_led(parent, "Right", 1, 4)

        red_lbl = ttk.Label(parent, text="Red Row:", font=("Arial", 9, "bold"))
        red_lbl.grid(row=2, column=0, pady=5, padx=5, sticky="w")
        self.btn_indicators["Red_1"] = self.make_led(parent, "Red 1", 2, 1)
        self.btn_indicators["Red_2"] = self.make_led(parent, "Red 2", 2, 2)
        self.btn_indicators["Red_3"] = self.make_led(parent, "Red 3", 2, 3)
        self.btn_indicators["Red_4"] = self.make_led(parent, "Red 4", 2, 4)

        dpad_lbl = ttk.Label(parent, text="D-Pad POV:", font=("Arial", 9, "bold"))
        dpad_lbl.grid(row=3, column=0, pady=10, padx=5, sticky="w")

        self.dpad_canvas = tk.Canvas(parent, width=80, height=80, bg="#222", highlightthickness=0)
        self.dpad_canvas.grid(row=3, column=1, columnspan=4, pady=5)

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

    def make_led(self, parent, text, r, c):
        lbl = tk.Label(parent, text=text, bg="#555", fg="white", width=8, relief="ridge")
        lbl.grid(row=r, column=c, padx=2, pady=2)
        return lbl

    def set_led(self, name, is_on):
        color = "red" if is_on else "#555"
        if self.btn_indicators[name].cget("bg") != color:
            self.btn_indicators[name].config(bg=color)

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
                self.status_label.config(text="Status: G25 Connected", foreground="green")
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
                        self.set_led("Btn_A", w_btn & 0x08)
                        self.set_led("Btn_B", w_btn & 0x04)
                        self.set_led("Paddle_L", w_btn & 0x02)
                        self.set_led("Paddle_R", w_btn & 0x01)

                        t_btn = data[2]
                        self.set_led("Top", t_btn & 0x08)
                        self.set_led("Left", t_btn & 0x10)
                        self.set_led("Bottom", t_btn & 0x20)
                        self.set_led("Right", t_btn & 0x40)

                        red_btn = data[0]
                        self.set_led("Red_1", red_btn & 0x10)
                        self.set_led("Red_2", red_btn & 0x20)
                        self.set_led("Red_3", red_btn & 0x40)
                        self.set_led("Red_4", red_btn & 0x80)

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

                        # --- THE NEW COMBINED PEDALS LOGIC ---
                        if self.combined_pedals_var.get():
                            # Math: Rests at 50. Gas drives it up to 100. Brake pulls it down to 0.
                            combined_pct = 50.0 + (gas_pct / 2.0) - (brake_pct / 2.0)

                            self.gas_title.config(text="Combined")
                            self.gas_lbl.config(text=f"{int(combined_pct)}%")
                            self.gas_bar['value'] = combined_pct

                            # Hide Brake text
                            self.brake_title.config(text="Brake (Off)")
                            self.brake_lbl.config(text="N/A")
                            self.brake_bar['value'] = 0
                        else:
                            # Standard Split Logic
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

        except Exception as e:
            self.status_label.config(text=f"Error: {e}", foreground="red")

        finally:
            self.root.after(15, self.hardware_loop)

if __name__ == "__main__":
    root = tk.Tk()
    app = RawWheelConfigApp(root, G25RawController())
    root.mainloop()
