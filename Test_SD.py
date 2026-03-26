import os
import machine
import sdcard

# --- 1. Setup SD Card (SPI 1) ---
spi = machine.SPI(1, baudrate=1000000, sck=machine.Pin(10), mosi=machine.Pin(11), miso=machine.Pin(12))
cs = machine.Pin(13, machine.Pin.OUT, value=1)

try:
    sd = sdcard.SDCard(spi, cs)
    os.mount(sd, "/sd")
    print("SD Card Mounted.")
except Exception as e:
    print("Mount failed. Is the 'Touch' connection secure?", e)

def get_next_filename(base_name="accel", extension=".csv"):
    """
    Checks /sd for existing files and returns the next available name.
    Example: accel.csv -> accel1.csv -> accel2.csv
    """
    path = "/sd/"
    files = os.listdir(path)
    
    # Start with the base name
    current_name = f"{base_name}{extension}"
    
    # If the base name doesn't exist, we're done
    if current_name not in files:
        return path + current_name
    
    # If it does exist, start counting from 1
    counter = 1
    while True:
        current_name = f"{base_name}{counter}{extension}"
        if current_name not in files:
            return path + current_name
        counter += 1

# --- 2. Create the File ---
new_file_path = get_next_filename()
print(f"Creating new file: {new_file_path}")

try:
    with open(new_file_path, "w") as f:
        f.write("Time_ms,X,Y,Z\n") # CSV Header
        f.write("0,0,0,0\n")      # Placeholder data row
    print("Success! File written.")
except Exception as e:
    print("Write failed:", e)

# --- 3. List all files to verify ---
print("Current files on SD card:", os.listdir("/sd"))