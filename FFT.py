"""
fft_inspector.py
================
Visualizes the raw frequency content of 9-axis IMU data.
No high-pass filtering, no double-integration, no coordinate rotations.
"""

import csv
import os
import numpy as np
import matplotlib.pyplot as plt

# =============================================================================
# CONSTANTS
# =============================================================================
NOMINAL_RATE_HZ = 10 

def load_log(filename: str = "accel.csv") -> dict:
    """Simplified loader to get raw IMU columns."""
    path = filename
    samples = []
    timestamps = []
    
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f, skipinitialspace=True)
            for row in reader:
                if not row or row[0].startswith(("#", "TEMPS", "WIND", "timestamp_s")):
                    continue
                try:
                    numeric = [float(v) for v in row if v.strip()]
                    if len(numeric) >= 10:
                        timestamps.append(numeric[0])
                        samples.append(numeric[1:10])
                except ValueError:
                    continue
    except FileNotFoundError:
        print(f"Error: {path} not found.")
        return None

    ts_arr = np.array(timestamps)
    fs = 1.0 / np.median(np.diff(ts_arr)) if len(ts_arr) > 1 else NOMINAL_RATE_HZ
    
    return {
        "data": np.array(samples),
        "fs": fs,
        "ts": ts_arr
    }

def plot_raw_fft(data_dict):
    """
    Computes and plots the Magnitude Spectrum (FFT) for Accel, Gyro, and Mag.
    """
    samples = data_dict["data"]
    fs = data_dict["fs"]
    N = len(samples)
    
    # Calculate Frequency Bins
    # fftfreq returns frequencies from 0 to fs/2
    freqs = np.fft.rfftfreq(N, d=1/fs)
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    fig.suptitle(f"Raw FFT Magnitude Spectrum (fs = {fs:.2f} Hz)\nNo Filtering / No Rotation", fontsize=14)
    
    titles = ["Accelerometer (Linear Motion + Gravity)", "Gyroscope (Rotational Rate)", "Magnetometer (Magnetic Field)"]
    labels = ["X", "Y", "Z"]
    colors = ["tab:red", "tab:green", "tab:blue"]
    
    for i, title in enumerate(titles):
        ax = axes[i]
        start_col = i * 3
        
        for j in range(3):
            # Compute FFT
            raw_signal = samples[:, start_col + j]
            # Subtract mean to remove the DC (0Hz) spike so we can see the peaks
            signal_no_dc = raw_signal - np.mean(raw_signal)
            
            fft_values = np.fft.rfft(signal_no_dc)
            magnitude = np.abs(fft_values) * (2.0 / N) # Normalized magnitude
            
            ax.plot(freqs, magnitude, label=labels[j], color=colors[j], alpha=0.8)
        
        ax.set_title(title)
        ax.set_ylabel("Magnitude")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(loc="upper right")
        
        # Log scale often helps see small vibration peaks
        ax.set_yscale('log')

    axes[-1].set_xlabel("Frequency (Hz)")
    plt.tight_layout()
    plt.show()

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    target = input("Enter filename (default: accel.csv): ").strip() or "accel.csv"
    if not target.endswith(".csv"): target += ".csv"
    
    payload = load_log(target)
    
    if payload and len(payload["data"]) > 0:
        print(f"Analyzing {len(payload['data'])} samples...")
        plot_raw_fft(payload)
    else:
        print("No data found or file error.")