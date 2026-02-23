import pefile
import os

def list_dll_functions(dll_path):
    print(f"\n{'='*60}")
    print(f"Scanning: {os.path.basename(dll_path)}")
    print(f"{'='*60}")

    if not os.path.exists(dll_path):
        print("File not found! Check the path.")
        return

    try:
        # Load the DLL file
        pe = pefile.PE(dll_path)

        # Check if it has an export directory
        if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
            functions = []
            for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if exp.name:
                    functions.append(exp.name.decode('utf-8'))

            # Sort alphabetically and print
            for func in sorted(functions):
                print(f" - {func}")
            print(f"\nTotal functions found: {len(functions)}")
        else:
            print("No exported functions found in this DLL.")

    except Exception as e:
        print(f"Error reading DLL: {e}")

# --- Paths to your two DLLs ---
legacy_dll = r"c:\program files\logitech gaming software\sdk\steeringwheel\x64\LogitechSteeringWheel.dll"
modern_dll = r"c:\program files\logi\wheel_sdk\9.1.0\logi_steering_wheel_x64.dll"

# Run the scanner
list_dll_functions(legacy_dll)
list_dll_functions(modern_dll)
