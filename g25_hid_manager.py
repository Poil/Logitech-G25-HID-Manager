import hid
import tkinter as tk
from tkinter import ttk

# USB IDs for Logitech G25
VENDOR_ID = 0x046D
PRODUCT_ID = 0xC299

class G25RawController:
    def __init__(self):
        self.vendor_id = VENDOR_ID
        self.product_id = PRODUCT_ID

    def is_connected(self):
        try:
            device = hid.device()
            device.open(self.vendor_id, self.product_id)
            device.close()
            return True
        except IOError:
            return False

    def send_command(self, packet):
        try:
            device = hid.device()
            device.open(self.vendor_id, self.product_id)
            device.set_nonblocking(1)
            device.write(packet)
            device.close()
            return True
        except IOError:
            return False

    def set_degrees(self, degrees):
        degrees = max(40, min(900, int(degrees)))
        low_byte = degrees & 0xFF
        high_byte = (degrees >> 8) & 0xFF
        packet = [0x00, 0xF8, 0x81, low_byte, high_byte, 0x00, 0x00, 0x00]
        return self.send_command(packet)

    def set_autocenter(self, strength_percent):
        strength_percent = max(0, min(100, int(strength_percent)))
        mag = int((strength_percent / 100.0) * 65535)
        b2 = mag >> 13
        b3 = mag >> 13
        b4 = mag >> 8
        packet = [0x00, 0xFE, 0x0D, b2, b3, b4, 0x00, 0x00]
        return self.send_command(packet)

# --- User Interface Application ---
class RawWheelConfigApp:
    def __init__(self, root, wheel):
        self.root = root
        self.wheel = wheel
        self.root.title("G25 Hardware Controller (Raw USB)")
        self.root.geometry("500x320")
        self.root.resizable(False, False)

        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        self.left_pane = ttk.Frame(self.main_frame)
        self.left_pane.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.right_pane = ttk.Frame(self.main_frame)
        self.right_pane.pack(side="right", fill="y")

        self.setup_left_pane()
        self.setup_right_pane()

        self.status_label = ttk.Label(self.root, text="Waiting for UI to render...", font=("Arial", 9, "bold"))
        self.status_label.pack(side="bottom", pady=5)

        self.root.after(500, self.delayed_init)

    def delayed_init(self):
        self.root.focus_force()
        self.root.update()
        self.apply_settings()
        self.connection_loop()

    def setup_left_pane(self):
        # Auto-Centering Frame
        self.ffb_frame = ttk.LabelFrame(self.left_pane, text="Force Feedback Hardware Settings")
        self.ffb_frame.pack(fill="x", pady=(0, 10), ipady=10)

        self.enable_centering_var = tk.BooleanVar(value=True)
        self.enable_centering_cb = ttk.Checkbutton(self.ffb_frame, text="Enable Hardware Centering Spring", variable=self.enable_centering_var, command=self.toggle_centering_state)
        self.enable_centering_cb.pack(anchor="w", padx=10, pady=(10, 5))

        self.centering_var = tk.DoubleVar(value=20)
        self.centering_slider, self.centering_entry = self.create_slider_row(self.ffb_frame, "Spring Strength", 0, 100, self.centering_var, unit="%")

        # Wheel Range Frame
        self.wheel_frame = ttk.LabelFrame(self.left_pane, text="Steering Wheel Range")
        self.wheel_frame.pack(fill="x", pady=(10, 10), ipady=10)

        self.degrees_var = tk.DoubleVar(value=900)
        self.degrees_slider, self.degrees_entry = self.create_slider_row(self.wheel_frame, "Degrees Of Rotation", 40, 900, self.degrees_var, unit="°")

    def setup_right_pane(self):
        btn_width = 15
        ttk.Button(self.right_pane, text="Apply to Wheel", width=btn_width, command=self.apply_settings).pack(pady=(15, 5))
        ttk.Button(self.right_pane, text="Cancel", width=btn_width, command=self.root.destroy).pack(pady=(0, 15))
        ttk.Button(self.right_pane, text="Defaults", width=btn_width, command=self.apply_defaults).pack(pady=(0, 5))

    def create_slider_row(self, parent, label_text, min_val, max_val, var, unit="%"):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=10, pady=2)

        ttk.Label(frame, text=label_text, width=20).pack(side="left")

        entry = ttk.Entry(frame, width=7, justify="right")
        entry.pack(side="right")

        def update_entry(v):
            """Safely updates the text box without triggering a recursive loop."""
            entry.delete(0, tk.END)
            entry.insert(0, f"{v}{unit}")

        def on_slider_drag(val):
            """Triggered when the mouse drags the slider."""
            v = int(float(val))
            var.set(v)
            update_entry(v)

        def on_entry_type(event):
            """Triggered when you press Enter in the text box or click away."""
            text = entry.get().replace(unit, "").strip()
            try:
                v = int(float(text))
                v = max(min_val, min(max_val, v)) # Clamp between min and max
                var.set(v)
                update_entry(v)
            except ValueError:
                # If the user typed garbage (like "abc"), just revert to current valid number
                update_entry(int(var.get()))

        def step_slider(amount):
            """Triggered by Arrow Keys to increment perfectly by 1."""
            v = int(var.get()) + amount
            v = max(min_val, min(max_val, v))
            var.set(v)
            update_entry(v)
            return "break" # Stops Tkinter from applying its own weird decimal steps

        slider = ttk.Scale(frame, from_=min_val, to=max_val, variable=var, command=on_slider_drag)
        slider.pack(side="left", fill="x", expand=True, padx=10)

        # Initialize the entry box value
        update_entry(int(var.get()))

        # --- NEW BINDINGS ---
        # 1. Bind Arrow Keys to the Slider
        slider.bind("<Left>", lambda e: step_slider(-1))
        slider.bind("<Right>", lambda e: step_slider(1))

        # 2. Bind Text Box Typing
        entry.bind("<Return>", on_entry_type)   # When pressing Enter
        entry.bind("<FocusOut>", on_entry_type) # When clicking away from the box

        return slider, entry

    def toggle_centering_state(self):
        state_flag = ['!disabled'] if self.enable_centering_var.get() else ['disabled']
        self.centering_slider.state(state_flag)
        self.centering_entry.state(state_flag)

    def apply_defaults(self):
        self.enable_centering_var.set(True)
        self.centering_var.set(20)
        self.centering_slider.set(20)
        self.create_slider_row_update(self.centering_entry, 20, "%")
        
        self.degrees_var.set(900)
        self.degrees_slider.set(900)
        self.create_slider_row_update(self.degrees_entry, 900, "°")
        
        self.toggle_centering_state()
        self.apply_settings()

    def create_slider_row_update(self, entry, val, unit):
        entry.delete(0, tk.END)
        entry.insert(0, f"{val}{unit}")

    def apply_settings(self):
        deg_success = self.wheel.set_degrees(int(self.degrees_var.get()))
        
        strength = int(self.centering_var.get()) if self.enable_centering_var.get() else 0
        spring_success = self.wheel.set_autocenter(strength)

        if deg_success and spring_success:
            print(f"Successfully applied: {int(self.degrees_var.get())}° | Spring: {strength}%")
        else:
            print("Failed to apply settings. Is the wheel plugged in and LGS closed?")

    def connection_loop(self):
        if self.wheel.is_connected():
            self.status_label.config(text="Status: Hardware Connected & Active (No LGS Required!)", foreground="green")
        else:
            self.status_label.config(text="Status: Wheel NOT detected! Close LGS or plug in USB.", foreground="red")
        self.root.after(2000, self.connection_loop)

if __name__ == "__main__":
    my_wheel = G25RawController()
    root = tk.Tk()
    app = RawWheelConfigApp(root, my_wheel)
    root.mainloop()
