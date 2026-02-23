import ctypes
import tkinter as tk
from tkinter import ttk
import atexit
import os

# --- 1. Load the Logitech SDK DLL ---
DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "LogitechSteeringWheel.dll")

try:
    logi_dll = ctypes.WinDLL(DLL_PATH)
except OSError as e:
    print(f"Error loading DLL. Make sure LogitechSteeringWheel.dll is in this folder: {os.path.dirname(os.path.abspath(__file__))}")
    exit()

# --- 2. Build the C-Struct to read from the driver ---
# This matches the C++ struct exactly as found in LuaWheel's source code
class LogiControllerPropertiesData(ctypes.Structure):
    _fields_ = [
        ("forceEnable", ctypes.c_bool),
        ("overallGain", ctypes.c_int),
        ("springGain", ctypes.c_int),
        ("damperGain", ctypes.c_int),
        ("defaultSpringEnabled", ctypes.c_bool),
        ("defaultSpringGain", ctypes.c_int),
        ("combinePedals", ctypes.c_bool),
        ("wheelRange", ctypes.c_int),
        ("gameSettingsEnabled", ctypes.c_bool),
        ("allowGameSettings", ctypes.c_bool)
    ]

# --- 3. Define C-types Signatures ---
logi_dll.LogiSteeringInitialize.argtypes = [ctypes.c_bool]
logi_dll.LogiSteeringInitialize.restype = ctypes.c_bool

logi_dll.LogiUpdate.argtypes = []
logi_dll.LogiUpdate.restype = ctypes.c_bool

logi_dll.LogiSetOperatingRange.argtypes = [ctypes.c_int, ctypes.c_int]
logi_dll.LogiSetOperatingRange.restype = ctypes.c_bool

# New Read Functions!
logi_dll.LogiGetCurrentControllerProperties.argtypes = [ctypes.c_int, ctypes.POINTER(LogiControllerPropertiesData)]
logi_dll.LogiGetCurrentControllerProperties.restype = ctypes.c_bool

logi_dll.LogiGetOperatingRange.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
logi_dll.LogiGetOperatingRange.restype = ctypes.c_bool

logi_dll.LogiPlaySpringForce.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
logi_dll.LogiPlaySpringForce.restype = ctypes.c_bool

logi_dll.LogiPlayDamperForce.argtypes = [ctypes.c_int, ctypes.c_int]
logi_dll.LogiPlayDamperForce.restype = ctypes.c_bool

logi_dll.LogiIsConnected.argtypes = [ctypes.c_int]
logi_dll.LogiIsConnected.restype = ctypes.c_bool

logi_dll.LogiSteeringShutdown.argtypes = []
logi_dll.LogiSteeringShutdown.restype = None

# The holy grail configuration function! Note: it passes the struct by value, not by reference.
logi_dll.LogiSetPreferredControllerProperties.argtypes = [LogiControllerPropertiesData]
logi_dll.LogiSetPreferredControllerProperties.restype = ctypes.c_bool

# --- 4. Wheel Controller Class ---
class LogitechWheel:
    def __init__(self, index=0):
        self.index = index
        self.initialized = False
        atexit.register(self.shutdown)

    def initialize_sdk(self):
        # False is mandatory for older DirectInput wheels like the G25
        self.initialized = logi_dll.LogiSteeringInitialize(False)
        return self.initialized

    def is_connected(self):
        return logi_dll.LogiIsConnected(self.index) if self.initialized else False

    def update(self):
        if self.initialized: logi_dll.LogiUpdate()

    def set_preferred_properties(self, props):
        """Sends a global configuration struct directly to the driver."""
        if self.initialized:
            return logi_dll.LogiSetPreferredControllerProperties(props)
        return False

    def get_current_properties(self):
        """Reads the live properties from the Logitech Driver."""
        if not self.initialized:
            return None
        props = LogiControllerPropertiesData()
        success = logi_dll.LogiGetCurrentControllerProperties(self.index, ctypes.byref(props))
        if success:
            return props
        return None

    def get_operating_range(self):
        """Reads the live degree range from the Logitech Driver."""
        if not self.initialized:
            return 900
        range_val = ctypes.c_int()
        success = logi_dll.LogiGetOperatingRange(self.index, ctypes.byref(range_val))
        if success:
            return range_val.value
        return 900

    def set_degrees(self, degrees):
        if self.initialized: logi_dll.LogiSetOperatingRange(self.index, int(degrees))

    def set_spring_force(self, strength):
        if self.initialized: logi_dll.LogiPlaySpringForce(self.index, 0, 100, int(strength))

    def set_damper_force(self, strength):
        if self.initialized: logi_dll.LogiPlayDamperForce(self.index, int(strength))

    def shutdown(self):
        if self.initialized: logi_dll.LogiSteeringShutdown()

# --- 5. User Interface Application ---
class ClassicWheelConfigApp:
    def __init__(self, root, wheel):
        self.root = root
        self.wheel = wheel
        self.root.title("Specific Game Settings - Active")
        self.root.geometry("600x480")
        self.root.resizable(False, False)

        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        self.left_pane = ttk.Frame(self.main_frame)
        self.left_pane.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.right_pane = ttk.Frame(self.main_frame)
        self.right_pane.pack(side="right", fill="y")

        self.setup_left_pane()
        self.setup_right_pane()
        self.setup_description_box()

        self.status_label = ttk.Label(self.root, text="Waiting for UI to render before booting SDK...", font=("Arial", 9, "bold"))
        self.status_label.pack(side="bottom", pady=5)

        self.set_description("Move the mouse over a control to see more information for that item.")

        self.root.after(500, self.delayed_init)

    def delayed_init(self):
        self.root.focus_force()
        self.root.update()

        success = self.wheel.initialize_sdk()
        if success:
            self.sdk_loop()
            self.read_live_wheel_settings() # Auto-read from driver on boot!
        else:
            self.status_label.config(text="Status: DLL Initialization Failed!", foreground="red")

    def read_live_wheel_settings(self):
        """Asks the driver for its current configuration and sets the sliders to match."""
        props = self.wheel.get_current_properties()
        degrees = self.wheel.get_operating_range()

        if props:
            self.use_ffb_var.set(props.forceEnable)
            self.overall_var.set(props.overallGain)
            self.spring_var.set(props.springGain)
            self.damper_var.set(props.damperGain)
            self.enable_centering_var.set(props.defaultSpringEnabled)
            self.centering_var.set(props.defaultSpringGain)

            # Map values visually to sliders
            self.overall_slider.set(props.overallGain)
            self.spring_slider.set(props.springGain)
            self.damper_slider.set(props.damperGain)
            self.centering_slider.set(props.defaultSpringGain)

            print("Successfully read Force Feedback settings from driver.")
        else:
            print("Could not read FFB properties. Using UI defaults.")
            self.apply_defaults_values()

        if degrees:
            self.degrees_var.set(degrees)
            self.degrees_slider.set(degrees)
            print(f"Successfully read operating range: {degrees}°")

        self.toggle_ffb_state()
        self.toggle_wheel_state()

    def setup_left_pane(self):
        self.ffb_frame = ttk.Frame(self.left_pane)
        self.ffb_frame.pack(fill="x", pady=(0, 10))

        self.use_ffb_var = tk.BooleanVar(value=True)
        self.use_ffb_cb = ttk.Checkbutton(self.ffb_frame, text="Use Special Force Feedback Device Settings", variable=self.use_ffb_var, command=self.toggle_ffb_state)
        self.use_ffb_cb.pack(anchor="w", pady=(0, 5))

        self.overall_var = tk.DoubleVar()
        self.overall_slider, self.overall_entry = self.create_slider_row(
            self.ffb_frame, "Overall Effects Strength", 0, 150, self.overall_var, "Adjusts the overall strength of all force feedback effects.")

        self.spring_var = tk.DoubleVar()
        self.spring_slider, self.spring_entry = self.create_slider_row(
            self.ffb_frame, "Spring Effect Strength", 0, 150, self.spring_var, "Adjusts the strength of effects that pull the wheel toward a specific position.")

        self.damper_var = tk.DoubleVar()
        self.damper_slider, self.damper_entry = self.create_slider_row(
            self.ffb_frame, "Damper Effect Strength", 0, 150, self.damper_var, "Adjusts the friction feeling in the wheel, simulating tire weight.")

        self.enable_centering_var = tk.BooleanVar(value=True)
        self.enable_centering_cb = ttk.Checkbutton(self.ffb_frame, text="Enable Centering Spring", variable=self.enable_centering_var, command=self.toggle_centering_state)
        self.enable_centering_cb.pack(anchor="w", pady=(10, 0))

        self.centering_var = tk.DoubleVar()
        self.centering_slider, self.centering_entry = self.create_slider_row(
            self.ffb_frame, "Centering Spring Strength", 0, 150, self.centering_var, "Adjusts how strongly the wheel returns to the center.")

        ttk.Separator(self.left_pane, orient='horizontal').pack(fill='x', pady=10)

        self.wheel_frame = ttk.Frame(self.left_pane)
        self.wheel_frame.pack(fill="x", pady=(0, 10))

        self.use_wheel_var = tk.BooleanVar(value=True)
        self.use_wheel_cb = ttk.Checkbutton(self.wheel_frame, text="Use Special Steering Wheel Settings", variable=self.use_wheel_var, command=self.toggle_wheel_state)
        self.use_wheel_cb.pack(anchor="w", pady=(0, 5))

        self.degrees_var = tk.DoubleVar()
        self.degrees_slider, self.degrees_entry = self.create_slider_row(
            self.wheel_frame, "Degrees Of Rotation", 40, 900, self.degrees_var, "Limits the physical rotation range of the steering wheel.", unit="°")

    def setup_right_pane(self):
        btn_width = 12
        ttk.Button(self.right_pane, text="Apply", width=btn_width, command=self.apply_settings).pack(pady=(0, 5))
        ttk.Button(self.right_pane, text="Cancel", width=btn_width, command=self.root.destroy).pack(pady=(0, 15))
        ttk.Button(self.right_pane, text="Defaults", width=btn_width, command=self.apply_defaults).pack(pady=(0, 5))
        ttk.Button(self.right_pane, text="Help", width=btn_width, command=self.show_help).pack(pady=(0, 5))

    def setup_description_box(self):
        self.desc_frame = ttk.LabelFrame(self.root, text="Description")
        self.desc_frame.pack(fill="x", side="bottom", padx=10, pady=5)
        self.desc_label = ttk.Label(self.desc_frame, text="", wraplength=550)
        self.desc_label.pack(anchor="w", padx=5, pady=10)

    def create_slider_row(self, parent, label_text, min_val, max_val, var, desc, unit="%"):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=2)

        ttk.Label(frame, text=label_text, width=25).pack(side="left")

        def on_slider_move(val):
            v = int(float(val))
            entry.config(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, f"{v}{unit}")
            entry.config(state="readonly")

        slider = ttk.Scale(frame, from_=min_val, to=max_val, variable=var, command=on_slider_move)
        slider.pack(side="left", fill="x", expand=True, padx=10)

        entry = ttk.Entry(frame, width=6, justify="right")
        entry.pack(side="right")
        entry.insert(0, f"{int(var.get())}{unit}")
        entry.config(state="readonly")

        self.bind_hover(slider, desc)
        return slider, entry

    def bind_hover(self, widget, text):
        widget.bind("<Enter>", lambda e: self.set_description(text))
        widget.bind("<Leave>", lambda e: self.set_description("Move the mouse over a control to see more information for that item."))

    def set_description(self, text):
        self.desc_label.config(text=text)

    def toggle_ffb_state(self):
        state_flag = ['!disabled'] if self.use_ffb_var.get() else ['disabled']
        for w in [self.overall_slider, self.spring_slider, self.damper_slider, self.enable_centering_cb]:
            w.state(state_flag)
        self.toggle_centering_state()

    def toggle_centering_state(self):
        state_flag = ['!disabled'] if (self.enable_centering_var.get() and self.use_ffb_var.get()) else ['disabled']
        self.centering_slider.state(state_flag)

    def toggle_wheel_state(self):
        state_flag = ['!disabled'] if self.use_wheel_var.get() else ['disabled']
        self.degrees_slider.state(state_flag)

    def apply_defaults(self):
        self.apply_defaults_values()
        self.overall_slider.set(100)
        self.spring_slider.set(100)
        self.damper_slider.set(100)
        self.centering_slider.set(10)
        self.degrees_slider.set(900)
        self.toggle_ffb_state()
        self.toggle_wheel_state()
        self.push_to_wheel()

    def apply_defaults_values(self):
        self.use_ffb_var.set(True)
        self.overall_var.set(100)
        self.spring_var.set(100)
        self.damper_var.set(100)
        self.enable_centering_var.set(True)
        self.centering_var.set(10)
        self.use_wheel_var.set(True)
        self.degrees_var.set(900)

    def push_to_wheel(self):
        # 1. Build the Configuration Packet
        props = LogiControllerPropertiesData()

        props.forceEnable = self.use_ffb_var.get()
        props.overallGain = int(self.overall_var.get())
        props.springGain = int(self.spring_var.get())
        props.damperGain = int(self.damper_var.get())

        # Centering Spring Settings
        props.defaultSpringEnabled = self.enable_centering_var.get()
        if props.defaultSpringEnabled:
            props.defaultSpringGain = int(self.centering_var.get())
        else:
            props.defaultSpringGain = 0

        # Wheel Settings (Keeps the same structure as the driver expects)
        props.combinePedals = False
        props.wheelRange = int(self.degrees_var.get()) if self.use_wheel_var.get() else 900
        props.gameSettingsEnabled = True
        props.allowGameSettings = True

        # 2. Send the Configuration to the Driver permanently
        success = self.wheel.set_preferred_properties(props)

        if success:
            self.status_label.config(text="Status: Global Configuration Saved to Driver!", foreground="green")
            print("Successfully overwrote global driver configuration.")
        else:
            self.status_label.config(text="Status: Failed to set configuration.", foreground="red")
            print("Failed to set global configuration.")

        # 3. Apply the physical steering lock
        if self.use_wheel_var.get():
            self.wheel.set_degrees(int(self.degrees_var.get()))

    def apply_settings(self):
        self.push_to_wheel()

    def show_help(self):
        tk.messagebox.showinfo("Help", "To feel the forces, this app MUST be the active window.")

    def sdk_loop(self):
        self.wheel.update()

        if self.wheel.is_connected():
            if self.root.focus_displayof():
                self.status_label.config(text="Status: Connected & App Focused (Forces Active)", foreground="green")
                self.push_to_wheel()
            else:
                self.status_label.config(text="Status: Connected (Focus lost! Click this window to feel FFB)", foreground="orange")
        else:
            self.status_label.config(text="Status: Wheel NOT detected! Is Logitech Gaming Software running?", foreground="red")

        self.root.after(50, self.sdk_loop)

if __name__ == "__main__":
    my_wheel = LogitechWheel(index=0)
    root = tk.Tk()
    app = ClassicWheelConfigApp(root, my_wheel)
    root.mainloop()
