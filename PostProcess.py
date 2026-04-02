"""
wave_analysis.py
================
Directional wave spectrum analysis from 9-axis buoy IMU data.

Pipeline:
    1. Load CSV — timestamps in column 0 (seconds); 9 IMU columns follow
    2. Derive actual sample rate from timestamps; fall back to NOMINAL_RATE_HZ
    3. Rotate body-frame acceleration → NED frame
    4. Double-integrate vertical acceleration → heave displacement (freq domain)
    5. Compute north/east slope from pitch/roll rotated by heading
    6. Welch PSD → Hs, Tp
    7. Cross-spectral density (heave vs slopes) → a1, b1 Fourier coefficients
    8. Mean wave direction at peak frequency (and per dominant swell peak)
    9. True wind direction from AS5600 vane + Mahony heading + tilt correction
    10. Plot heave energy spectrum with annotated swell peaks

CSV row format (written by main.py):
    timestamp_s, ax, ay, az, gx, gy, gz, mx, my, mz, wind_vane_deg
    (wind_vane_deg is blank for most rows; populated in the final window only)

Metadata rows (no timestamp column):
    TEMPS, t_pin7, t_pin8, t_pin9
    WIND,  total_clicks, cps, avg_period_s, avg_direction_deg

References:
    Longuet-Higgins et al. (1963) — directional wave spectrum estimation
    Datawell Waverider manual — heave double integration method
"""

import csv
import os
import math
import numpy as np
from scipy.signal import welch, csd
import matplotlib.pyplot as plt

# =============================================================================
# CONSTANTS  — no magic numbers below this block
# =============================================================================
NOMINAL_RATE_HZ      = 10           # Expected IMU sample rate (Hz)
GRAVITY              = 9.81         # m/s²
MAG_DECLINATION_DEG  = 15.47        # +15° 28' E  (positive = east)

# Calibration Offsets
WIND_OFFSET_DEG = 14.5

# Mahony fusion filter warm-up trim
FUSION_KP       = 0.1
FUSION_KI       = 0.001
FUSION_WARMUP_S = 3.0               # seconds to trim from the start

# Heave integration high-pass cutoff
HEAVE_HIGHPASS_HZ    = 0.06         # Hz

# Welch PSD parameters
WELCH_OVERLAP        = 0.5          # 50 % overlap

# Swell peak detection
PEAK_THRESHOLD_RATIO = 0.15         # fraction of max PSD to consider a peak

# Frequency band of interest
SWELL_FREQ_MIN       = 0.05         # Hz  (~20 s period)
SWELL_FREQ_MAX       = 0.5          # Hz  (~2 s period)

# Window size for zoomed time-domain plots (raw, attitude, heave, NED)
PLOT_WINDOW_S        = 60.0         # seconds — centred on middle of record


# Based on calibration of magnetometer, using max and min 
# minx=-32640, maxx=32640
# miny=-32517, maxy=32254
# minz=-32514, maxz=32510
MAG_FIX_OFFSETS = (0.0, -131.0, -126.5)
MAG_SCALES = (0.996, 1.004, 1.000)


# =============================================================================
# 1. DATA LOADING
# =============================================================================
def _resolve_file(filename: str) -> str:
    """Resolve a filename relative to this script's directory."""
    if os.path.isabs(filename):
        return filename
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def load_log(filename: str = "accel.csv") -> dict:
    """
    Load buoy CSV log written by main.py.

    Expected numeric row format:
        timestamp_s, ax, ay, az, gx, gy, gz, mx, my, mz [, wind_vane_deg]

    wind_vane_deg (column 11) is blank for most rows and populated only
    during the final wind-sampling window.

    Returns
    -------
    dict with keys:
        samples        : list of 9-tuples  (ax, ay, az, gx, gy, gz, mx, my, mz)
        timestamps     : np.ndarray of float seconds (None if not present)
        wind_vane_deg  : np.ndarray of float, NaN where column was blank
        fs             : float — derived (or nominal) sample rate in Hz
        dt             : float — 1 / fs
        temps          : list [t_pin7, t_pin8, t_pin9] or None
        wind           : dict {total_clicks, cps, avg_period_s, avg_direction_deg}
        filename       : str — basename of the loaded file (for plot titles)
    """
    path = _resolve_file(filename)
    samples       = []
    timestamps    = []
    wind_vane_raw = []
    temps         = None
    wind          = {
        "total_clicks"     : None,
        "cps"              : None,
        "avg_period_s"     : None,
        "avg_direction_deg": None,
    }
    has_timestamps = False

    def _maybe_float(val):
        v = val.strip() if val else ""
        return float(v) if v else None

    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f, skipinitialspace=True)
            for row in reader:
                if not row or not any(field.strip() for field in row):
                    continue
                if str(row[0]).strip().startswith("#"):
                    continue
                if str(row[0]).strip().lower() == "timestamp_s":
                    continue

                tag = str(row[0]).strip().upper()

                if tag == "TEMPS":
                    temps = [_maybe_float(v) for v in row[1:4]]
                    continue

                if tag == "WIND":
                    fields = row[1:]
                    keys   = ["total_clicks", "cps", "avg_period_s", "avg_direction_deg"]
                    for i, key in enumerate(keys):
                        if i < len(fields):
                            wind[key] = _maybe_float(fields[i])
                    if wind["total_clicks"] is not None:
                        wind["total_clicks"] = int(wind["total_clicks"])
                    continue

                try:
                    numeric = [float(v) if v.strip() else float("nan") for v in row]
                except ValueError:
                    continue

                if len(numeric) >= 10 and not math.isnan(numeric[0]):

                    mx_csv, my_csv, mz_csv = numeric[7], numeric[8], numeric[9]
                    # Apply magnetometer corrections
                    mx_cal = (mx_csv - MAG_FIX_OFFSETS[0]) * MAG_SCALES[0]
                    my_cal = (my_csv - MAG_FIX_OFFSETS[1]) * MAG_SCALES[1]
                    mz_cal = (mz_csv - MAG_FIX_OFFSETS[2]) * MAG_SCALES[2]

                    timestamps.append(numeric[0])
                    samples.append((
                        numeric[1], numeric[2], numeric[3], # Accel
                        numeric[4], numeric[5], numeric[6], # Gyro
                        mx_cal,     my_cal,     mz_cal      # FIXED Mag
                    ))
                    vane = numeric[10] if len(numeric) >= 11 else float("nan")
                    wind_vane_raw.append(vane)
                    has_timestamps = True
                elif len(numeric) >= 9:
                    samples.append(tuple(numeric[:9]))
                    wind_vane_raw.append(float("nan"))
                elif len(numeric) >= 6:
                    samples.append(tuple(numeric[:6]) + (0.0, 0.0, 0.0))
                    wind_vane_raw.append(float("nan"))
                elif len(numeric) >= 3:
                    samples.append(tuple(numeric[:3]) + (0.0,) * 6)
                    wind_vane_raw.append(float("nan"))

        if has_timestamps and len(timestamps) >= 2:
            ts_arr    = np.array(timestamps)
            diffs     = np.diff(ts_arr)
            median_dt = float(np.median(diffs))
            fs        = 1.0 / median_dt if median_dt > 0 else NOMINAL_RATE_HZ
            dt        = median_dt
            jitter    = float(np.std(diffs) / median_dt * 100)
            print(f"Loaded {len(samples)} samples from {path}")
            print(f"  Duration     : {ts_arr[-1] - ts_arr[0]:.2f} s")
            print(f"  Sample rate  : {fs:.2f} Hz  (nominal {NOMINAL_RATE_HZ} Hz)")
            print(f"  Timing jitter: {jitter:.1f} %")
        else:
            ts_arr = None
            fs     = NOMINAL_RATE_HZ
            dt     = 1.0 / fs
            print(f"Loaded {len(samples)} samples from {path}  "
                  f"(no timestamps — using nominal {fs} Hz)")

        wind_vane_arr = np.array(wind_vane_raw, dtype=float)
        n_vane = int(np.sum(~np.isnan(wind_vane_arr)))
        print(f"  Wind vane    : {n_vane} samples with readings")

        if temps:
            labels = [f"pin{p}" for p in [7, 8, 9]]
            temp_strs = [
                f"{labels[i]}={t:.2f}°C" if t is not None else f"{labels[i]}=--"
                for i, t in enumerate(temps)
            ]
            print(f"  Temperatures : {', '.join(temp_strs)}")

        if wind["cps"] is not None:
            print(f"  Wind speed   : {wind['cps']:.4f} CPS  "
                  f"({wind['total_clicks']} clicks)")
        if wind["avg_period_s"] is not None:
            print(f"  Wind period  : {wind['avg_period_s']:.6f} s")
        if wind["avg_direction_deg"] is not None:
            print(f"  Wind dir     : {wind['avg_direction_deg']:.1f}°")

    except FileNotFoundError:
        print(f"Error: {path} not found.")
        ts_arr        = None
        wind_vane_arr = np.full(len(samples), float("nan"))
        fs            = NOMINAL_RATE_HZ
        dt            = 1.0 / fs

    return {
        "samples":       samples,
        "timestamps":    ts_arr,
        "wind_vane_deg": wind_vane_arr,
        "fs":            fs,
        "dt":            dt,
        "temps":         temps,
        "wind":          wind,
        "filename":      os.path.basename(filename),
    }


# =============================================================================
# 2. COORDINATE TRANSFORMATION  — body frame → NED
# =============================================================================
def rotation_matrix_ned(pitch_rad: float, roll_rad: float,
                         yaw_rad: float) -> np.ndarray:
    cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
    cr, sr = math.cos(roll_rad),  math.sin(roll_rad)
    cy, sy = math.cos(yaw_rad),   math.sin(yaw_rad)
    Rz = np.array([[ cy, -sy, 0], [ sy,  cy, 0], [  0,   0, 1]])
    Ry = np.array([[ cp, 0, sp],  [  0,  1,  0], [-sp,   0, cp]])
    Rx = np.array([[1,   0,  0],  [  0, cr, -sr], [  0,  sr, cr]])
    return Rz @ Ry @ Rx


def rotate_to_ned(samples: list, pitch_rad: np.ndarray,
                  roll_rad: np.ndarray, yaw_ned_rad: np.ndarray) -> np.ndarray:
    N = len(samples)
    acc_ned = np.zeros((N, 3))
    for i, s in enumerate(samples):
        R = rotation_matrix_ned(pitch_rad[i], roll_rad[i], yaw_ned_rad[i])
        acc_ned[i] = R @ np.array([s[0], s[1], s[2]])
    return acc_ned


# =============================================================================
# 3. HEAVE CALCULATION  — frequency-domain double integration
# =============================================================================
def accel_to_heave(acc_down: np.ndarray, fs: float = NOMINAL_RATE_HZ,
                   f_cutoff: float = HEAVE_HIGHPASS_HZ) -> np.ndarray:
    N = len(acc_down)
    a = acc_down - np.mean(acc_down)
    a = a - np.polyval(np.polyfit(np.arange(N), a, 1), np.arange(N))
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)
    A     = np.fft.rfft(a)
    omega = 2.0 * np.pi * freqs
    with np.errstate(divide="ignore", invalid="ignore"):
        kernel = np.where(freqs >= f_cutoff, -1.0 / omega**2, 0.0)
    return np.fft.irfft(A * kernel, n=N)


# =============================================================================
# 4. SLOPE CALCULATION
# =============================================================================
def compute_slopes(pitch_rad: np.ndarray, roll_rad: np.ndarray,
                   yaw_ned_rad: np.ndarray) -> tuple:
    cy = np.cos(yaw_ned_rad)
    sy = np.sin(yaw_ned_rad)
    return pitch_rad * cy + roll_rad * sy, -pitch_rad * sy + roll_rad * cy


# =============================================================================
# 5. SPECTRAL ANALYSIS  — Hs, Tp
# =============================================================================
def compute_spectrum(heave: np.ndarray, fs: float = NOMINAL_RATE_HZ) -> tuple:
    N = len(heave)
    nperseg = min(N, max(32, int(2 ** np.floor(np.log2(N / 2)))))
    freqs, psd = welch(heave, fs=fs, nperseg=nperseg,
                       noverlap=int(nperseg * WELCH_OVERLAP),
                       window="hann", scaling="density")
    band = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    if not np.any(band):
        print("Warning: no frequency bins in swell band — check data length.")
        return freqs, psd, np.nan, np.nan
    m0       = np.trapezoid(psd[band], freqs[band])
    Hs       = 4.0 * np.sqrt(max(m0, 0.0))
    peak_idx = np.argmax(psd[band])
    Tp       = 1.0 / freqs[band][peak_idx] if freqs[band][peak_idx] > 0 else np.nan
    return freqs, psd, Hs, Tp


# =============================================================================
# 6. DIRECTIONAL ANALYSIS  — a1, b1 Fourier coefficients
# =============================================================================
def compute_direction(heave: np.ndarray, slope_north: np.ndarray,
                      slope_east: np.ndarray, fs: float = NOMINAL_RATE_HZ) -> tuple:
    N        = len(heave)
    nperseg  = min(N, max(32, int(2 ** np.floor(np.log2(N / 2)))))
    noverlap = int(nperseg * WELCH_OVERLAP)
    kw       = dict(fs=fs, nperseg=nperseg, noverlap=noverlap,
                    window="hann", scaling="density")
    freqs, S_zz = welch(heave,       **kw)
    _,     S_xx = welch(slope_north, **kw)
    _,     S_yy = welch(slope_east,  **kw)
    _, C_xz     = csd(heave, slope_north, **kw)
    _, C_yz     = csd(heave, slope_east,  **kw)
    eps = 1e-12
    a1  = np.real(C_xz) / np.sqrt((S_zz + eps) * (S_xx + eps))
    b1  = np.real(C_yz) / np.sqrt((S_zz + eps) * (S_yy + eps))
    return freqs, np.degrees(np.arctan2(b1, a1)) % 360.0, a1, b1


# =============================================================================
# 7. SWELL PEAK DETECTION
# =============================================================================
def find_swell_peaks(freqs: np.ndarray, psd: np.ndarray,
                     direction: np.ndarray, n_peaks: int = 2) -> list:
    band = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    f_b, p_b, d_b = freqs[band], psd[band], direction[band]
    if len(p_b) == 0:
        return []
    threshold = PEAK_THRESHOLD_RATIO * np.max(p_b)
    peaks = []
    for i in range(1, len(p_b) - 1):
        if p_b[i] > p_b[i-1] and p_b[i] > p_b[i+1] and p_b[i] >= threshold:
            peaks.append({"freq": f_b[i], "period": 1.0 / f_b[i],
                          "psd_value": p_b[i], "direction": d_b[i]})
    peaks.sort(key=lambda x: x["psd_value"], reverse=True)
    return peaks[:n_peaks]


# =============================================================================
# 8. TRUE WIND DIRECTION — vane + heading + tilt correction
# =============================================================================
def compute_true_wind_direction(wind_vane_deg, pitch_rad,
                                roll_rad, yaw_ned_rad) -> dict:
    valid_idx = np.where(~np.isnan(wind_vane_deg))[0]
    if len(valid_idx) == 0:
        return {"true_dir_deg": None, "true_dir_std_deg": None,
                "n_samples": 0, "per_sample_deg": np.array([]),
                "per_sample_ts_idx": np.array([])}

    corrected = []
    for i in valid_idx:
        vane_rad = math.radians((wind_vane_deg[i] - WIND_OFFSET_DEG) % 360.0)
        vx, vy   = math.cos(vane_rad), math.sin(vane_rad)
        cp, sp   = math.cos(pitch_rad[i]), math.sin(pitch_rad[i])
        cr, sr   = math.cos(roll_rad[i]),  math.sin(roll_rad[i])
        ned_north    = cp * vx + sp * sr * vy
        ned_east     = cr * vy
        az_body_rad  = math.atan2(ned_east, ned_north)
        true_rad     = (az_body_rad + yaw_ned_rad[i]) % (2 * math.pi)
        corrected.append(math.degrees(true_rad))

    corrected = np.array(corrected)
    sin_mean  = np.mean(np.sin(np.radians(corrected)))
    cos_mean  = np.mean(np.cos(np.radians(corrected)))
    mean_dir  = math.degrees(math.atan2(sin_mean, cos_mean)) % 360.0
    R         = math.sqrt(sin_mean**2 + cos_mean**2)
    circ_std  = math.degrees(math.sqrt(-2.0 * math.log(max(R, 1e-9)))) if R < 1 else 0.0

    return {"true_dir_deg": mean_dir, "true_dir_std_deg": circ_std,
            "n_samples": len(corrected), "per_sample_deg": corrected,
            "per_sample_ts_idx": valid_idx}


# =============================================================================
# 9. FUSION HELPER  — pitch / roll / heading
# =============================================================================
def run_fusion(samples: list, dt: float = 1.0 / NOMINAL_RATE_HZ) -> tuple:
    try:
        from fusion import Fusion
    except ImportError:
        print("Warning: fusion.py not found. Using accel-only tilt estimate.")
        return _fallback_tilt(samples, dt)

    fuse    = Fusion(lambda *_: dt)
    fuse.kp = FUSION_KP
    fuse.ki = FUSION_KI
    pitches, rolls, yaws = [], [], []

    for s in samples:
        accel   = (s[0], s[1], s[2])
        gyro    = (s[3], s[4], s[5])
        mag     = (s[6], s[7], s[8])
        has_mag = any(v != 0.0 for v in mag)
        if has_mag:
            fuse.update(accel, gyro, mag, dt)
        else:
            fuse.update_nomag(accel, gyro, dt)
        pitches.append(math.radians(fuse.pitch))
        rolls.append(math.radians(fuse.roll))
        yaws.append(math.radians((fuse.heading + MAG_DECLINATION_DEG) % 360.0))

    return np.array(pitches), np.array(rolls), np.array(yaws)


def _fallback_tilt(samples: list, dt: float = 1.0 / NOMINAL_RATE_HZ) -> tuple:
    pitches, rolls, yaws = [], [], []
    for s in samples:
        ax, ay, az = s[0], s[1], s[2]
        pitches.append(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
        rolls.append(math.atan2(ay, az))
        yaws.append(0.0)
    return np.array(pitches), np.array(rolls), np.array(yaws)


# =============================================================================
# PLOTTING HELPERS
# =============================================================================
def _mid_window(n_total: int, fs: float, window_s: float = PLOT_WINDOW_S):
    """Return (start, end) indices for a centred window of `window_s` seconds."""
    half  = int(window_s * fs / 2)
    mid   = n_total // 2
    return max(0, mid - half), min(n_total, mid + half)


def _subtitle(fname: str) -> str:
    """One-line subtitle string showing the source file."""
    return f"source: {fname}"


# =============================================================================
# 10. PLOTTING
# =============================================================================
def plot_raw(data_dict: dict):
    """Raw accel / gyro / mag — middle 60 s window."""
    samples    = data_dict.get("samples", [])
    timestamps = data_dict.get("timestamps")
    fs         = data_dict.get("fs", NOMINAL_RATE_HZ)
    fname      = data_dict.get("filename", "")
    if not samples:
        return

    start, end   = _mid_window(len(samples), fs)
    view_samples = samples[start:end]
    cols         = list(zip(*view_samples))

    if timestamps is not None:
        x      = timestamps[start:end] - timestamps[0]
        xlabel = "Time (s) [relative to start of log]"
    else:
        x      = np.arange(start, end) / fs
        xlabel = "Time (s) [estimated]"

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.suptitle(f"Raw IMU data — middle {PLOT_WINDOW_S:.0f} s\n{_subtitle(fname)}",
                 fontsize=13)

    labels = ["X", "Y", "Z"]
    colors = ["tab:red", "tab:green", "tab:blue"]
    titles = ["Accelerometer (m/s²)", "Gyroscope (°/s)", "Magnetometer (raw)"]
    for row, (title, offset) in enumerate(zip(titles, [0, 3, 6])):
        for j in range(3):
            axes[row].plot(x, cols[offset + j], label=labels[j],
                           color=colors[j], alpha=0.8)
        axes[row].set_title(title)
        axes[row].legend(loc="right")
        axes[row].grid(True, linestyle="--", alpha=0.4)
    axes[-1].set_xlabel(xlabel)
    plt.tight_layout()


def plot_attitude(pitch_rad, roll_rad, yaw_ned_rad,
                  timestamps: np.ndarray = None,
                  dt: float = 1.0 / NOMINAL_RATE_HZ,
                  fname: str = ""):
    """Fused attitude — middle 60 s window."""
    fs           = 1.0 / dt
    start, end   = _mid_window(len(pitch_rad), fs)

    p_view = np.degrees(pitch_rad[start:end])
    r_view = np.degrees(roll_rad[start:end])
    y_view = np.degrees(yaw_ned_rad[start:end]) % 360

    if timestamps is not None:
        t      = timestamps[start:end] - timestamps[0]
        xlabel = "Time (s) [relative to start of log]"
    else:
        t      = np.arange(start, end) * dt
        xlabel = f"Time (s) [nominal {fs:.0f} Hz]"

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(f"Fused attitude — middle {PLOT_WINDOW_S:.0f} s\n{_subtitle(fname)}",
                 fontsize=13)

    axes[0].plot(t, p_view, color="tab:red");   axes[0].set_title("Pitch (°)")
    axes[1].plot(t, r_view, color="tab:green"); axes[1].set_title("Roll (°)")
    axes[2].plot(t, y_view, color="tab:blue");  axes[2].set_title("True heading (°)")
    axes[2].set_ylim(0, 360)

    for ax in axes:
        ax.axhline(0, color="black", lw=0.6, ls="--")
        ax.grid(True, linestyle="--", alpha=0.4)
    axes[-1].set_xlabel(xlabel)
    plt.tight_layout()


def plot_heave_time(heave, timestamps=None, fs=NOMINAL_RATE_HZ, fname: str = ""):
    """Heave displacement — middle 60 s window."""
    start, end = _mid_window(len(heave), fs)
    h_view     = heave[start:end]

    if timestamps is not None:
        t      = timestamps[start:end] - timestamps[0]
        xlabel = "Time (s) [relative]"
    else:
        t      = np.arange(start, end) / fs
        xlabel = "Time (s) [estimated]"

    plt.figure(figsize=(12, 5))
    plt.plot(t, h_view, color="tab:cyan", linewidth=2, label="Heave displacement")
    plt.fill_between(t, h_view, alpha=0.1, color="tab:cyan")
    plt.axhline(0, color="black", linestyle="-", alpha=0.3)
    plt.title(f"Vertical heave displacement — middle {PLOT_WINDOW_S:.0f} s\n{_subtitle(fname)}",
              fontsize=13)
    plt.xlabel(xlabel)
    plt.ylabel("Displacement (m)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc="upper right")
    plt.tight_layout()


def plot_ned(acc_ned, timestamps=None, fs=NOMINAL_RATE_HZ, fname: str = ""):
    """NED-frame accelerations — middle 60 s window."""
    start, end = _mid_window(len(acc_ned), fs)

    if timestamps is not None:
        t      = timestamps[start:end] - timestamps[0]
        xlabel = "Time (s) [relative]"
    else:
        t      = np.arange(start, end) / fs
        xlabel = "Time (s) [estimated]"

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.suptitle(f"NED-frame accelerations — middle {PLOT_WINDOW_S:.0f} s\n{_subtitle(fname)}",
                 fontsize=13)

    axes[0].plot(t, acc_ned[start:end, 0], color="tab:red",   alpha=0.8)
    axes[0].set_title("North (m/s²)")
    axes[1].plot(t, acc_ned[start:end, 1], color="tab:green", alpha=0.8)
    axes[1].set_title("East (m/s²)")
    axes[2].plot(t, acc_ned[start:end, 2], color="tab:blue",  alpha=0.8)
    axes[2].axhline(GRAVITY, color="black", linestyle="--", alpha=0.5, label="1g")
    axes[2].set_title("Down (m/s²)")
    axes[2].legend(loc="right")

    for ax in axes:
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.set_ylabel("m/s²")
    axes[-1].set_xlabel(xlabel)
    plt.tight_layout()


def plot_heave_spectrum(freqs: np.ndarray, psd: np.ndarray,
                        peaks: list, Hs: float, Tp: float,
                        direction: np.ndarray = None, fname: str = ""):
    """Heave energy spectrum + optional wave direction panel."""
    band      = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    n_panels  = 2 if direction is not None else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 5 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    colors = ["tab:red", "tab:orange", "tab:purple"]

    ax_psd = axes[0]
    ax_psd.semilogy(freqs[band], psd[band], color="steelblue", linewidth=1.5,
                    label="Heave PSD")
    ax_psd.fill_between(freqs[band], psd[band], alpha=0.15, color="steelblue")

    for i, peak in enumerate(peaks):
        c = colors[i % len(colors)]
        ax_psd.axvline(peak["freq"], color=c, linestyle="--", linewidth=1.2)
        ax_psd.annotate(
            f"Swell {i+1}\nT = {peak['period']:.1f} s\nDir = {peak['direction']:.0f}°",
            xy=(peak["freq"], peak["psd_value"]),
            xytext=(peak["freq"] * 1.15, peak["psd_value"]),
            fontsize=8, color=c,
            arrowprops=dict(arrowstyle="->", color=c, lw=0.8),
        )

    ax_psd.set_title(
        f"Heave energy spectrum — Hs = {Hs:.2f} m  Tp = {Tp:.1f} s\n{_subtitle(fname)}",
        fontsize=12)
    ax_psd.set_ylabel("PSD (m² / Hz)")
    ax_psd.set_xlim(SWELL_FREQ_MIN, SWELL_FREQ_MAX)
    ax_psd.grid(True, which="both", linestyle="--", alpha=0.4)
    ax_psd.legend()

    if direction is not None:
        ax_dir     = axes[1]
        noise_mask = psd >= (0.01 * np.max(psd[band]))
        valid      = band & noise_mask
        ax_dir.scatter(freqs[valid], direction[valid],
                       s=12, color="steelblue", alpha=0.7, label="Mean direction")
        if np.sum(valid) > 5:
            ax_dir.plot(freqs[valid], direction[valid],
                        color="steelblue", linewidth=1.0, alpha=0.4)
        for i, peak in enumerate(peaks):
            c = colors[i % len(colors)]
            ax_dir.axvline(peak["freq"], color=c, linestyle="--",
                           linewidth=1.2, alpha=0.8)
            ax_dir.axhline(peak["direction"], color=c, linestyle=":",
                           linewidth=1.0, alpha=0.6,
                           label=f"Swell {i+1}: {peak['direction']:.0f}°")
        ax_dir.set_title("Mean wave direction per frequency  "
                         "(0° = North, clockwise, waves arriving FROM)", fontsize=11)
        ax_dir.set_ylabel("Direction (°)")
        ax_dir.set_xlabel("Frequency (Hz)")
        ax_dir.set_ylim(0, 360)
        ax_dir.set_yticks([0, 45, 90, 135, 180, 225, 270, 315, 360])
        ax_dir.set_yticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"])
        ax_dir.grid(True, which="both", linestyle="--", alpha=0.4)
        ax_dir.legend(fontsize=8)

    plt.tight_layout()


def plot_wind_direction(wind_result: dict, timestamps: np.ndarray = None,
                        fs: float = NOMINAL_RATE_HZ, fname: str = ""):
    """Per-sample corrected wind direction with circular mean and ±1σ band."""
    if wind_result["n_samples"] == 0:
        print("No wind vane data to plot.")
        return

    idx      = wind_result["per_sample_ts_idx"]
    dirs     = wind_result["per_sample_deg"]
    mean_dir = wind_result["true_dir_deg"]
    std_dir  = wind_result["true_dir_std_deg"]

    if timestamps is not None:
        t      = timestamps[idx] - timestamps[0]
        xlabel = "Time (s) [relative to start of log]"
    else:
        t      = idx / fs
        xlabel = "Time (s) [estimated]"

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.scatter(t, dirs, s=14, color="steelblue", alpha=0.7,
               label="Corrected direction")
    ax.axhline(mean_dir, color="tab:red", linewidth=1.5,
               label=f"Mean = {mean_dir:.1f}°")
    ax.axhspan(mean_dir - std_dir, mean_dir + std_dir,
               alpha=0.15, color="tab:red", label=f"±1σ = {std_dir:.1f}°")
    ax.set_title(f"True wind direction (tilt-corrected, geographic)\n{_subtitle(fname)}",
                 fontsize=12)
    ax.set_ylabel("Direction (° from North)")
    ax.set_xlabel(xlabel)
    ax.set_ylim(0, 360)
    ax.set_yticks([0, 90, 180, 270, 360])
    ax.set_yticklabels(["N", "E", "S", "W", "N"])
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="upper right")
    plt.tight_layout()


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":

    # ── 0. File selection ─────────────────────────────────────────────────────
    print("Available files in script directory:")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_files  = sorted(f for f in os.listdir(script_dir) if f.endswith(".csv"))
    if csv_files:
        for name in csv_files:
            print(f"  {name}")
    else:
        print("  (no .csv files found)")

    raw = input("\nEnter filename to analyse (default: accel.csv): ").strip()
    if not raw:
        raw = "accel.csv"
    if not raw.endswith(".csv"):
        raw += ".csv"
    chosen_file = raw
    print(f"Loading: {chosen_file}\n")

    # ── 1. Load ───────────────────────────────────────────────────────────────
    data          = load_log(chosen_file)
    samples       = data["samples"]
    timestamps    = data["timestamps"]
    fs            = data["fs"]
    dt            = data["dt"]
    wind          = data["wind"]
    temps         = data["temps"]
    wind_vane_deg = data["wind_vane_deg"]
    fname         = data["filename"]

    if len(samples) < 10:
        raise SystemExit("Not enough samples to analyse.")

    # ── 2. Fusion → Euler angles ──────────────────────────────────────────────
    pitch_rad, roll_rad, yaw_ned_rad = run_fusion(samples, dt=dt)

    # ── 2b. Trim fusion warm-up ───────────────────────────────────────────────
    warmup_samples = int(FUSION_WARMUP_S * fs)
    if warmup_samples >= len(samples):
        raise SystemExit(
            f"FUSION_WARMUP_S ({FUSION_WARMUP_S} s) is longer than the whole "
            f"record ({len(samples) / fs:.1f} s). Reduce it.")

    samples     = samples[warmup_samples:]
    pitch_rad   = pitch_rad[warmup_samples:]
    roll_rad    = roll_rad[warmup_samples:]
    yaw_ned_rad = yaw_ned_rad[warmup_samples:]
    if timestamps is not None:
        timestamps = timestamps[warmup_samples:]
    if len(wind_vane_deg) > warmup_samples:
        wind_vane_deg = wind_vane_deg[warmup_samples:]
    print(f"  Trimmed first {FUSION_WARMUP_S:.1f} s ({warmup_samples} samples) "
          f"— {len(samples)} samples remain ({len(samples)/fs:.1f} s)")

    # ── 2c. True wind direction ───────────────────────────────────────────────
    wind_result = compute_true_wind_direction(
        wind_vane_deg, pitch_rad, roll_rad, yaw_ned_rad)

    # ── 3. NED acceleration ───────────────────────────────────────────────────
    acc_ned = rotate_to_ned(samples, pitch_rad, roll_rad, yaw_ned_rad)
    acc_up  = -acc_ned[:, 2]

    # ── 4. Heave ──────────────────────────────────────────────────────────────
    heave = accel_to_heave(acc_up, fs=fs)

    # ── 5. Slopes ─────────────────────────────────────────────────────────────
    slope_north, slope_east = compute_slopes(pitch_rad, roll_rad, yaw_ned_rad)

    # ── 6. Spectrum → Hs, Tp ─────────────────────────────────────────────────
    freqs, psd, Hs, Tp = compute_spectrum(heave, fs=fs)

    # ── 7. Directional analysis ───────────────────────────────────────────────
    freqs_dir, direction, a1, b1 = compute_direction(
        heave, slope_north, slope_east, fs=fs)

    # ── 8. Swell peaks ────────────────────────────────────────────────────────
    peaks = find_swell_peaks(freqs_dir, psd, direction, n_peaks=2)

    # ── 9. Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print(f"  WAVE ANALYSIS SUMMARY — {fname}")
    print("=" * 50)
    print(f"  Significant Wave Height  Hs  = {Hs:.2f} m")
    print(f"  Peak Period              Tp  = {Tp:.1f} s")
    print(f"  Sample rate used         fs  = {fs:.2f} Hz")
    print(f"  Magnetic Declination         = +{MAG_DECLINATION_DEG}° E")

    print()
    if peaks:
        for i, p in enumerate(peaks):
            print(f"  Swell {i+1}:")
            print(f"    Period    : {p['period']:.1f} s")
            print(f"    Direction : {p['direction']:.0f}° (waves arriving FROM)")
            print(f"    Energy    : {p['psd_value']:.4f} m²/Hz")
    else:
        print("  No distinct swell peaks detected.")
        print("  (Data record may be too short — need several swell periods)")

    print()
    print("  TEMPERATURES")
    if temps:
        labels = ["pin7", "pin8", "pin9"]
        for i, t_val in enumerate(temps):
            label = labels[i] if i < len(labels) else f"probe{i}"
            val   = f"{t_val:.2f} °C" if t_val is not None else "not connected"
            print(f"    {label} : {val}")
    else:
        print("    No temperature data in file.")

    print()
    print("  WIND")
    if wind["cps"] is not None:
        print(f"    Speed (CPS)    : {wind['cps']:.4f}")
        print(f"    Total clicks   : {wind['total_clicks']}")
        if wind["avg_period_s"] is not None:
            print(f"    Avg period     : {wind['avg_period_s']:.6f} s")
        if wind["avg_direction_deg"] is not None:
            print(f"    Direction      : {wind['avg_direction_deg']:.1f}°")
        else:
            print("    Direction      : not recorded")
    else:
        print("    No wind data in file.")

    print()
    print("  TRUE WIND DIRECTION (tilt-corrected)")
    if wind_result["true_dir_deg"] is not None:
        print(f"    Mean direction : {wind_result['true_dir_deg']:.1f}°")
        print(f"    Circular std   : ±{wind_result['true_dir_std_deg']:.1f}°")
        print(f"    Samples used   : {wind_result['n_samples']}")
    else:
        print("    No wind vane column found in this file.")

    print("=" * 50 + "\n")

    # ── 10. Plots ─────────────────────────────────────────────────────────────
    # Pass fname to every plot function so titles show the source file.
    # data dict still holds the original full-length arrays for plot_raw.
    plot_raw(data)
    plot_ned(acc_ned, timestamps=timestamps, fs=fs, fname=fname)
    plot_attitude(pitch_rad, roll_rad, yaw_ned_rad,
                  timestamps=timestamps, dt=dt, fname=fname)
    plot_heave_time(heave, timestamps=timestamps, fs=fs, fname=fname)
    plot_heave_spectrum(freqs_dir, psd, peaks, Hs, Tp,
                        direction=direction, fname=fname)
    plot_wind_direction(wind_result, timestamps=timestamps, fs=fs, fname=fname)

    plt.show()