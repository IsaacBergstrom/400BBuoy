"""Host-side post-processing utilities.

This module reads a CSV file containing IMU samples (acceleration, gyroscope,
temperature) produced by the ESP32 and uses matplotlib to visualize the raw data.
It is intended to be run on the PC; the MicroPython device has no support for
matplotlib.

Usage example::

    from PostProcess import load_and_plot
    load_and_plot()

The function also returns the raw samples for further analysis.
"""

import csv
import matplotlib.pyplot as plt  # type: ignore
import numpy as np


def load_samples(filename=None):
    """Read samples from a CSV file and return a list of (ax,ay,az,gx,gy,gz,temp) tuples.

    If ``filename`` is omitted the default is ``accel.csv`` in the current directory.
    """
    if filename is None:
        filename = "accel.csv"
    data = []
    try:
        with open(filename, newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) == 7:
                    # Full IMU: ax,ay,az,gx,gy,gz,temp
                    pass
                elif len(row) == 3:
                    # Old accel only: pad with zeros for gyro/temp
                    row = row + ['0', '0', '0', '0']
                else:
                    print(f"Skipping row with {len(row)} columns: {row}")
                    continue
                try:
                    data.append(tuple(float(v) for v in row))
                except ValueError as e:
                    print(f"ValueError parsing row: {row} - {e}")
                    pass
        print(f"Successfully loaded {len(data)} samples from {filename}")
    except FileNotFoundError:
        print(f"File {filename} not found. Transfer accel.csv from the ESP32 to this directory first.")
    return data


def smooth_data(data, window_size=5):
    """Apply a moving average filter to smooth noisy acceleration data.

    Args:
        data: List or array of values
        window_size: Number of points for the moving average window

    Returns:
        Smoothed data as a numpy array
    """
    return np.convolve(data, np.ones(window_size) / window_size, mode='same')


def integrate_acceleration(acceleration, time_step):
    """Integrate acceleration to get velocity, then integrate again for displacement.

    Args:
        acceleration: Array of acceleration values
        time_step: Sampling interval in seconds (1/sampling_rate)

    Returns:
        Tuple of (velocity, displacement) arrays
    """
    # First integration: acceleration -> velocity
    velocity = np.cumsum(acceleration) * time_step
    # Second integration: velocity -> displacement
    displacement = np.cumsum(velocity) * time_step
    return velocity, displacement


def analyze_wave_motion(samples, sampling_rate=20):
    """Analyze vertical motion to extract wave characteristics.

    Extracts z-axis (vertical) acceleration, removes gravity, smooths, 
    and integrates to displacement. Returns data for plotting.

    Args:
        samples: List of IMU tuples (ax,ay,az,gx,gy,gz,temp)
        sampling_rate: Samples per second (default 20 Hz)

    Returns:
        Dict with time array and various processed signals
    """
    time_step = 1.0 / sampling_rate
    n_samples = len(samples)
    time = np.arange(n_samples) * time_step

    # Extract z-axis (vertical) acceleration
    accel_z = np.array([s[2] for s in samples])

    # Remove gravity (buoy sits at ~9.8 m/s² offset)
    accel_z_detrended = accel_z - 9.81

    # Smooth the acceleration
    accel_z_smooth = smooth_data(accel_z_detrended, window_size=5)

    # Integrate to get velocity and displacement
    velocity_z, displacement_z = integrate_acceleration(accel_z_smooth, time_step)

    return {
        'time': time,
        'accel_raw': accel_z,
        'accel_detrended': accel_z_detrended,
        'accel_smooth': accel_z_smooth,
        'velocity': velocity_z,
        'displacement': displacement_z
    }


def plot_wave_analysis(data_dict):
    """Plot raw, smoothed, and integrated wave motion data.

    Args:
        data_dict: Dictionary returned from analyze_wave_motion()
    """
    time = data_dict['time']

    # Acceleration plots
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))

    # Raw vs. Smoothed Acceleration
    axes[0].plot(time, data_dict['accel_raw'], label='Raw z-accel', alpha=0.6, color='red')
    axes[0].plot(time, data_dict['accel_smooth'], label='Smoothed', color='darkred', linewidth=2)
    axes[0].axhline(0, color='k', linestyle='--', alpha=0.3)
    axes[0].set_ylabel('Acceleration (m/s²)')
    axes[0].set_title('Vertical Acceleration (gravity removed)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Velocity
    axes[1].plot(time, data_dict['velocity'], label='Velocity', color='blue')
    axes[1].axhline(0, color='k', linestyle='--', alpha=0.3)
    axes[1].set_ylabel('Velocity (m/s)')
    axes[1].set_title('Vertical Velocity (integrated from acceleration)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    # Displacement (wave height)
    axes[2].plot(time, data_dict['displacement'], label='Displacement', color='green', linewidth=2)
    axes[2].axhline(0, color='k', linestyle='--', alpha=0.3)
    axes[2].set_ylabel('Displacement (m)')
    axes[2].set_xlabel('Time (s)')
    axes[2].set_title('Vertical Displacement (wave height profile)')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def plot_samples_original(samples, title="IMU data"):
    """Plot the IMU samples: acceleration, gyroscope, and temperature."""
    if not samples:
        print("no samples to plot")
        return
    t = list(range(len(samples)))
    axs = [s[0] for s in samples]
    ays = [s[1] for s in samples]
    azs = [s[2] for s in samples]
    gxs = [s[3] for s in samples]
    gys = [s[4] for s in samples]
    gzs = [s[5] for s in samples]
    temps = [s[6] for s in samples]

    # Acceleration plot
    plt.figure()
    plt.plot(t, axs, label="ax")
    plt.plot(t, ays, label="ay")
    plt.plot(t, azs, label="az")
    plt.xlabel("sample #")
    plt.ylabel("acceleration (m/s²)")
    plt.title(f"Acceleration - {title}")
    plt.legend()
    plt.grid(True)

    # Gyroscope plot
    plt.figure()
    plt.plot(t, gxs, label="gx")
    plt.plot(t, gys, label="gy")
    plt.plot(t, gzs, label="gz")
    plt.xlabel("sample #")
    plt.ylabel("gyro (°/s)")
    plt.title(f"Gyroscope - {title}")
    plt.legend()
    plt.grid(True)

    # Temperature plot
    plt.figure()
    plt.plot(t, temps, label="temp", color="red")
    plt.xlabel("sample #")
    plt.ylabel("temperature (°C)")
    plt.title(f"Temperature - {title}")
    plt.legend()
    plt.grid(True)

    plt.show()


def load_and_plot(filename=None):
    """Convenience function: load data from filename and plot it.

    The default filename is ``accel.csv`` in the current directory.
    Returns the samples list for further use.
    """
    if filename is None:
        filename = "accel.csv"
    samples = load_samples(filename)
    plot_samples_original(samples, title=f"Data from {filename}")
    return samples


if __name__ == "__main__":
    samples = load_samples()
    if samples:
        # Option 1: Plot raw IMU data (accel, gyro, temp)
        print("\nDisplaying raw IMU plots...")
        plot_samples_original(samples, title="Raw IMU Data")

        # Option 2: Analyze and plot wave motion
        print("\nAnalyzing wave motion...")
        wave_data = analyze_wave_motion(samples, sampling_rate=20)
        print(f"Displacement range: {wave_data['displacement'].min():.3f} to {wave_data['displacement'].max():.3f} m")
        print(f"Velocity range: {wave_data['velocity'].min():.3f} to {wave_data['velocity'].max():.3f} m/s")
        plot_wave_analysis(wave_data)
    else:
        print("No data loaded.")
