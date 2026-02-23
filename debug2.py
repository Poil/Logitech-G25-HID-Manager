import ctypes
import time
import os

# --- 1. Put the path to the DLL you want to test here ---
DLL_PATH = r"c:\program files\logitech gaming software\sdk\steeringwheel\x64\LogitechSteeringWheel.dll"

try:
    logi_dll = ctypes.WinDLL(DLL_PATH)
    print(f"Successfully loaded DLL: {os.path.basename(DLL_PATH)}")
except OSError as e:
    print(f"CRITICAL ERROR: Could not load DLL. {e}")
    exit()

# --- 2. Setup the C-types signatures ---
logi_dll.LogiSteeringInitialize.argtypes = [ctypes.c_bool]
logi_dll.LogiSteeringInitialize.restype = ctypes.c_bool

logi_dll.LogiUpdate.argtypes = []
logi_dll.LogiUpdate.restype = ctypes.c_bool

logi_dll.LogiIsConnected.argtypes = [ctypes.c_int]
logi_dll.LogiIsConnected.restype = ctypes.c_bool

# The magic function to check for exact hardware models
logi_dll.LogiIsModelConnected.argtypes = [ctypes.c_int, ctypes.c_int]
logi_dll.LogiIsModelConnected.restype = ctypes.c_bool

logi_dll.LogiSteeringShutdown.argtypes = []
logi_dll.LogiSteeringShutdown.restype = None

# --- Hardware Constants (From the Logitech C++ Header) ---
LOGI_MODEL_G27 = 0
LOGI_MODEL_G25 = 2
LOGI_MODEL_G29 = 26
LOGI_MODEL_G920 = 27

print("\n--- Starting Hardware Diagnostic ---")

# Pass False for older DirectInput wheels like the G25
initialized = logi_dll.LogiSteeringInitialize(False)

if not initialized:
    print("❌ FAILED: SDK refused to initialize. The required background driver (LGS or G HUB) is probably not running.")
else:
    print("✅ SDK Initialized. Pinging the driver for USB devices...")

    # We must call LogiUpdate a few times to give the driver a fraction of a second to poll the USB ports
    for _ in range(10):
        logi_dll.LogiUpdate()
        time.sleep(0.05)

    # Check Index 0 (The first gaming device plugged in)
    index = 0

    # Check 1: Does it see ANYTHING at all?
    is_connected = logi_dll.LogiIsConnected(index)
    if is_connected:
        print(f"✅ DEVICE FOUND: The DLL sees a gaming device at Index {index}.")
    else:
        print(f"❌ NO DEVICE: The DLL does not see any controllers at Index {index}.")
        print("   (If you have an Xbox controller plugged in, try changing 'index = 0' to 'index = 1' or '2' in the script).")

    # Check 2: Is it specifically the G25?
    is_g25 = logi_dll.LogiIsModelConnected(index, LOGI_MODEL_G25)
    if is_g25:
        print("🏎️  SUCCESS: The DLL has positively identified your Logitech G25!")
    else:
        # Let's do a quick check to see if it thinks it's something else
        if logi_dll.LogiIsModelConnected(index, LOGI_MODEL_G27):
            print("❌ MISMATCH: The DLL thinks your wheel is a G27.")
        elif logi_dll.LogiIsModelConnected(index, LOGI_MODEL_G29) or logi_dll.LogiIsModelConnected(index, LOGI_MODEL_G920):
            print("❌ MISMATCH: The DLL thinks your wheel is a modern G29/G920.")
        else:
            print("❌ MISMATCH: The device is connected, but the DLL does NOT recognize it as a G25.")

    # Always shut down cleanly
    logi_dll.LogiSteeringShutdown()
    print("\nDiagnostic complete. SDK Shutdown.")
