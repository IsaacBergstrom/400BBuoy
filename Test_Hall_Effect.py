import machine
import time

# --- Setup ---
# GP16 for Hall Effect (Internal pull-up is essential)
hall_pin = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)

# Global list to store timestamps of clicks (in microseconds)
click_timestamps = []

def hall_handler(pin):
    """Interrupt Service Routine: Runs every time magnet passes."""
    # Record the time in microseconds (more precise than milliseconds)
    click_timestamps.append(time.ticks_us())

# Attach Interrupt
hall_pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=hall_handler)

def run_5s_sample():
    global click_timestamps
    click_timestamps = [] # Reset for new window
    
    print("Starting 5-second reading...")
    start_time = time.time()
    
    # Wait for 5 seconds while the Interrupt collects data in the background
    time.sleep(5)
    
    # Calculate Results
    total_clicks = len(click_timestamps)
    cps = total_clicks / 5.0
    
    print("-" * 30)
    print("Reading Complete.")
    print("Total Clicks: ", total_clicks)
    print("Clicks Per Second (CPS): ", cps)
    
    if total_clicks > 1:
        # Calculate average time between clicks (Period)
        # Total time span / (number of intervals)
        first_click = click_timestamps[0]
        last_click = click_timestamps[-1]
        
        # Total duration in seconds from first to last click
        duration_s = time.ticks_diff(last_click, first_click) / 1_000_000
        
        if duration_s > 0:
            avg_period = duration_s / (total_clicks - 1)
            print("Avg Time Between Clicks: {:.4f}s".format(avg_period))
        else:
            print("Clicks happened too fast to measure interval.")
    else:
        print("Not enough clicks to calculate intervals.")
    print("-" * 30)

# Run a test
try:
    while True:
        run_5s_sample()
        time.sleep(1) # Small pause between windows
except KeyboardInterrupt:
    print("Program stopped.")