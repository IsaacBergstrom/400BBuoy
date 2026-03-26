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
    9. Plot heave energy spectrum with annotated swell peaks

CSV row format (written by collector.py):
    timestamp_s, ax, ay, az, gx, gy, gz, mx, my, mz

Metadata rows (no timestamp column):
    TEMPS, t1, t2, t3
    WIND,  direction, speed

References:
    Longuet-Higgins et al. (1963) — directional wave spectrum estimation
    Datawell Waverider manual — heave double integration method
"""

import csv
import os
import math
import numpy as np
from scipy.signal import welch, csd, butter, filtfilt
from scipy.ndimage import label
import matplotlib.pyplot as plt

# =============================================================================
# CONSTANTS  — no magic numbers below this block
# =============================================================================
NOMINAL_RATE_HZ     = 10            # Expected IMU sample rate (Hz)
#   Actual fs is derived from CSV timestamps at load time; this is the fallback
#   used only if timestamps are missing or fewer than 2 samples are present.
GRAVITY             = 9.81          # m/s²
MAG_DECLINATION_DEG = 15.47         # +15° 28' E  (positive = east)

# Heave integration high-pass cutoff — removes drift below this frequency
HEAVE_HIGHPASS_HZ   = 0.03         # Hz  (≈ 33 s period — longer than any swell)

# Welch PSD parameters
WELCH_OVERLAP       = 0.5          # 50 % overlap

# Swell peak detection — minimum spectral energy ratio to count as a peak
PEAK_THRESHOLD_RATIO = 0.15        # fraction of max PSD to consider a peak

# Frequency band of interest for ocean swells
SWELL_FREQ_MIN      = 0.04         # Hz  (~25 s period)
SWELL_FREQ_MAX      = 0.5          # Hz  (~2 s period)


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
    Load buoy CSV log written by collector.py.

    Expected numeric row format:
        timestamp_s, ax, ay, az, gx, gy, gz, mx, my, mz   (10 columns)

    Also accepts legacy rows without a timestamp (9, 6, or 3 IMU columns).
    Metadata rows (TEMPS, WIND) and comment lines starting with '#' are
    handled separately.

    Sample rate is derived from the median inter-sample interval of the
    timestamps.  If timestamps are absent the NOMINAL_RATE_HZ constant is
    used as a fallback.

    Returns
    -------
    dict with keys:
        samples    : list of 9-tuples  (ax, ay, az, gx, gy, gz, mx, my, mz)
        timestamps : np.ndarray of float seconds (None if not present)
        fs         : float — derived (or nominal) sample rate in Hz
        dt         : float — 1 / fs
        temps      : list or None
        wind       : dict {avg_direction, avg_speed}
    """
    path = _resolve_file(filename)
    samples    = []
    timestamps = []
    temps      = None
    wind       = {"avg_direction": None, "avg_speed": None}
    has_timestamps = False

    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f, skipinitialspace=True)
            for row in reader:
                if not row or not any(field.strip() for field in row):
                    continue

                # Skip comment lines written by collector.py
                if str(row[0]).strip().startswith("#"):
                    continue

                tag = str(row[0]).strip().upper()

                if tag == "TEMPS":
                    temps = [float(v) if v.strip() else None for v in row[1:]]
                    continue
                if tag == "WIND":
                    if len(row) > 1 and row[1].strip():
                        try:
                            wind["avg_direction"] = float(row[1])
                        except ValueError:
                            pass
                    if len(row) > 2 and row[2].strip():
                        try:
                            wind["avg_speed"] = float(row[2])
                        except ValueError:
                            pass
                    continue

                try:
                    numeric = [float(v) for v in row if v.strip()]
                except ValueError:
                    continue

                # 10-column row: timestamp + 9 IMU values
                if len(numeric) >= 10:
                    timestamps.append(numeric[0])
                    samples.append(tuple(numeric[1:10]))
                    has_timestamps = True
                # Legacy formats (no timestamp)
                elif len(numeric) >= 9:
                    samples.append(tuple(numeric[:9]))
                elif len(numeric) >= 6:
                    samples.append(tuple(numeric[:6]) + (0.0, 0.0, 0.0))
                elif len(numeric) >= 3:
                    samples.append(tuple(numeric[:3]) + (0.0,) * 6)

        # --- Derive sample rate from timestamps ---
        if has_timestamps and len(timestamps) >= 2:
            ts_arr  = np.array(timestamps)
            diffs   = np.diff(ts_arr)
            median_dt = float(np.median(diffs))
            fs  = 1.0 / median_dt if median_dt > 0 else NOMINAL_RATE_HZ
            dt  = median_dt
            jitter_pct = float(np.std(diffs) / median_dt * 100)
            print(f"Loaded {len(samples)} samples from {path}")
            print(f"  Duration     : {ts_arr[-1] - ts_arr[0]:.2f} s")
            print(f"  Sample rate  : {fs:.2f} Hz  (nominal {NOMINAL_RATE_HZ} Hz)")
            print(f"  Timing jitter: {jitter_pct:.1f} %")
        else:
            ts_arr = None
            fs     = NOMINAL_RATE_HZ
            dt     = 1.0 / fs
            print(f"Loaded {len(samples)} samples from {path}  "
                  f"(no timestamps — using nominal {fs} Hz)")

        if temps:
            print(f"  Temperatures : {temps}")
        if wind["avg_direction"] is not None:
            print(f"  Wind dir     : {wind['avg_direction']:.1f}°")

    except FileNotFoundError:
        print(f"Error: {path} not found.")
        ts_arr = None
        fs     = NOMINAL_RATE_HZ
        dt     = 1.0 / fs

    return {
        "samples":    samples,
        "timestamps": ts_arr,
        "fs":         fs,
        "dt":         dt,
        "temps":      temps,
        "wind":       wind,
    }


# =============================================================================
# 2. COORDINATE TRANSFORMATION  — body frame → NED
# =============================================================================
def rotation_matrix_ned(pitch_rad: float, roll_rad: float,
                         yaw_rad: float) -> np.ndarray:
    """
    Build a 3×3 rotation matrix R that transforms a vector from the
    body frame into the NED (North-East-Down) frame.

    Uses the ZYX (yaw-pitch-roll) convention:
        R = Rz(yaw) @ Ry(pitch) @ Rx(roll)

    Parameters
    ----------
    pitch_rad, roll_rad, yaw_rad : float  — Euler angles in radians

    Returns
    -------
    R : (3, 3) ndarray
    """
    cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
    cr, sr = math.cos(roll_rad),  math.sin(roll_rad)
    cy, sy = math.cos(yaw_rad),   math.sin(yaw_rad)

    # Rz (yaw)
    Rz = np.array([[ cy, -sy, 0],
                   [ sy,  cy, 0],
                   [  0,   0, 1]])
    # Ry (pitch)
    Ry = np.array([[ cp, 0, sp],
                   [  0, 1,  0],
                   [-sp, 0, cp]])
    # Rx (roll)
    Rx = np.array([[1,  0,   0],
                   [0, cr, -sr],
                   [0, sr,  cr]])

    return Rz @ Ry @ Rx


def rotate_to_ned(samples: list, pitch_rad: np.ndarray,
                  roll_rad: np.ndarray, yaw_ned_rad: np.ndarray) -> np.ndarray:
    """
    Rotate each body-frame acceleration sample into NED.

    Parameters
    ----------
    samples     : list of 9-tuples from load_log
    pitch_rad   : (N,) array — pitch from fusion filter (rad)
    roll_rad    : (N,) array — roll from fusion filter (rad)
    yaw_ned_rad : (N,) array — heading corrected for magnetic declination (rad)

    Returns
    -------
    acc_ned : (N, 3) array  [North, East, Down]  m/s²
    """
    N = len(samples)
    acc_ned = np.zeros((N, 3))

    for i, s in enumerate(samples):
        acc_body = np.array([s[0], s[1], s[2]])
        R = rotation_matrix_ned(pitch_rad[i], roll_rad[i], yaw_ned_rad[i])
        acc_ned[i] = R @ acc_body

    return acc_ned


# =============================================================================
# 3. HEAVE CALCULATION  — frequency-domain double integration
# =============================================================================
def accel_to_heave(acc_down: np.ndarray, fs: float = NOMINAL_RATE_HZ,
                   f_cutoff: float = HEAVE_HIGHPASS_HZ) -> np.ndarray:
    """
    Convert downward acceleration to heave displacement using the
    1/ω² method in the frequency domain.

    Steps:
        1. Remove gravity offset (mean subtraction)
        2. FFT the acceleration signal
        3. Divide each frequency component by -ω²  (double integration)
        4. Zero out components below f_cutoff to prevent drift
        5. IFFT back to time domain → heave (metres)

    Parameters
    ----------
    acc_down : (N,) array  — NED down-axis acceleration (m/s²)
    fs       : float       — sample rate (Hz)
    f_cutoff : float       — high-pass cutoff (Hz)

    Returns
    -------
    heave : (N,) array  — vertical displacement (m), positive = up
    """
    N = len(acc_down)

    # Remove mean to eliminate DC offset / gravity residual
    a = acc_down - np.mean(acc_down)

    # Frequency array for N-point FFT
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)   # Hz
    A     = np.fft.rfft(a)                    # complex spectrum

    # Build integration kernel:  H(f) = -1 / (2πf)²
    # (negative because down is positive in NED; heave up is positive out)
    omega = 2.0 * np.pi * freqs
    with np.errstate(divide="ignore", invalid="ignore"):
        kernel = np.where(freqs >= f_cutoff, -1.0 / omega**2, 0.0)

    # Frequency-domain integration → displacement spectrum
    Z = A * kernel

    # Back to time domain
    heave = np.fft.irfft(Z, n=N)
    return heave


# =============================================================================
# 4. SLOPE CALCULATION
# =============================================================================
def compute_slopes(pitch_rad: np.ndarray, roll_rad: np.ndarray,
                   yaw_ned_rad: np.ndarray) -> tuple:
    """
    Compute the North slope (η_x) and East slope (η_y) of the sea surface
    by rotating pitch and roll by the true heading (yaw corrected for
    magnetic declination).

    The small-angle approximation is valid for buoy motions:
        η_x  =  pitch * cos(yaw) + roll * sin(yaw)
        η_y  = -pitch * sin(yaw) + roll * cos(yaw)

    Parameters
    ----------
    pitch_rad   : (N,) array — rad
    roll_rad    : (N,) array — rad
    yaw_ned_rad : (N,) array — true heading (rad, 0 = North)

    Returns
    -------
    slope_north : (N,) array
    slope_east  : (N,) array
    """
    cy = np.cos(yaw_ned_rad)
    sy = np.sin(yaw_ned_rad)

    slope_north =  pitch_rad * cy + roll_rad * sy
    slope_east  = -pitch_rad * sy + roll_rad * cy

    return slope_north, slope_east


# =============================================================================
# 5. SPECTRAL ANALYSIS  — Hs, Tp
# =============================================================================
def compute_spectrum(heave: np.ndarray, fs: float = NOMINAL_RATE_HZ) -> tuple:
    """
    Estimate the heave Power Spectral Density using Welch's method.

    Significant wave height:
        m₀ = ∫ S(f) df   (zeroth spectral moment = variance)
        Hs = 4 √m₀

    Peak period:
        Tp = 1 / f_peak

    Parameters
    ----------
    heave : (N,) array — heave displacement (m)
    fs    : float      — sample rate (Hz)

    Returns
    -------
    freqs : (M,) array — frequency bins (Hz)
    psd   : (M,) array — power spectral density (m²/Hz)
    Hs    : float      — significant wave height (m)
    Tp    : float      — peak period (s)
    """
    N = len(heave)
    # Use longest power-of-2 segment that fits at least 2 windows
    nperseg = min(N, max(32, int(2 ** np.floor(np.log2(N / 2)))))

    freqs, psd = welch(heave, fs=fs, nperseg=nperseg,
                       noverlap=int(nperseg * WELCH_OVERLAP),
                       window="hann", scaling="density")

    # Restrict to swell band for Hs / Tp calculation
    band = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    if not np.any(band):
        print("Warning: no frequency bins in swell band — check data length.")
        return freqs, psd, np.nan, np.nan

    df   = freqs[1] - freqs[0]          # bin width (Hz)
    m0   = np.trapezoid(psd[band], freqs[band])
    Hs   = 4.0 * np.sqrt(max(m0, 0.0))

    peak_idx = np.argmax(psd[band])
    Tp       = 1.0 / freqs[band][peak_idx] if freqs[band][peak_idx] > 0 else np.nan

    return freqs, psd, Hs, Tp


# =============================================================================
# 6. DIRECTIONAL ANALYSIS  — a1, b1 Fourier coefficients
# =============================================================================
def compute_direction(heave: np.ndarray,
                      slope_north: np.ndarray,
                      slope_east: np.ndarray,
                      fs: float = NOMINAL_RATE_HZ) -> tuple:
    """
    Estimate mean wave direction per frequency using the first-order
    Fourier coefficients of the directional spectrum.

    From Longuet-Higgins et al. (1963):

        a₁(f) = Re[ C_xz(f) ] / √( S_zz(f) · S_xx(f) )
        b₁(f) = Re[ C_yz(f) ] / √( S_zz(f) · S_yy(f) )

    Where:
        S_zz  = heave PSD
        C_xz  = cross-spectrum(heave, north slope)
        C_yz  = cross-spectrum(heave, east slope)

    Mean direction (meteorological convention — direction waves come FROM):
        θ(f) = arctan2(b₁, a₁)   converted to degrees from North

    Parameters
    ----------
    heave, slope_north, slope_east : (N,) arrays
    fs : float

    Returns
    -------
    freqs     : (M,) array — frequency bins (Hz)
    direction : (M,) array — mean direction (°, from North, coming from)
    a1, b1    : (M,) arrays — normalised Fourier coefficients
    """
    N = len(heave)
    nperseg = min(N, max(32, int(2 ** np.floor(np.log2(N / 2)))))
    noverlap = int(nperseg * WELCH_OVERLAP)

    # Auto-spectra
    freqs, S_zz = welch(heave,       fs=fs, nperseg=nperseg,
                        noverlap=noverlap, window="hann", scaling="density")
    _,     S_xx = welch(slope_north, fs=fs, nperseg=nperseg,
                        noverlap=noverlap, window="hann", scaling="density")
    _,     S_yy = welch(slope_east,  fs=fs, nperseg=nperseg,
                        noverlap=noverlap, window="hann", scaling="density")

    # Cross-spectra (heave vs slopes)
    _, C_xz = csd(heave, slope_north, fs=fs, nperseg=nperseg,
                  noverlap=noverlap, window="hann", scaling="density")
    _, C_yz = csd(heave, slope_east,  fs=fs, nperseg=nperseg,
                  noverlap=noverlap, window="hann", scaling="density")

    # Normalised first Fourier coefficients
    eps = 1e-12   # avoid division by zero
    a1 = np.real(C_xz) / np.sqrt((S_zz + eps) * (S_xx + eps))
    b1 = np.real(C_yz) / np.sqrt((S_zz + eps) * (S_yy + eps))

    # Mean direction in degrees (0° = North, clockwise positive)
    direction_rad = np.arctan2(b1, a1)
    direction_deg = np.degrees(direction_rad) % 360.0

    return freqs, direction_deg, a1, b1


# =============================================================================
# 7. SWELL PEAK DETECTION
# =============================================================================
def find_swell_peaks(freqs: np.ndarray, psd: np.ndarray,
                     direction: np.ndarray, n_peaks: int = 2) -> list:
    """
    Identify dominant swell peaks in the spectrum and report their
    height, period, and direction.

    A peak is a local maximum in the swell band above PEAK_THRESHOLD_RATIO
    × the global maximum PSD.

    Parameters
    ----------
    freqs     : (M,) array — Hz
    psd       : (M,) array — m²/Hz
    direction : (M,) array — degrees
    n_peaks   : int        — maximum number of peaks to return

    Returns
    -------
    peaks : list of dicts  {freq, period, psd_value, direction}
    """
    band = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    f_b  = freqs[band]
    p_b  = psd[band]
    d_b  = direction[band]

    if len(p_b) == 0:
        return []

    threshold = PEAK_THRESHOLD_RATIO * np.max(p_b)

    # Find local maxima (simple: greater than both neighbours)
    peaks = []
    for i in range(1, len(p_b) - 1):
        if p_b[i] > p_b[i - 1] and p_b[i] > p_b[i + 1] and p_b[i] >= threshold:
            peaks.append({
                "freq":      f_b[i],
                "period":    1.0 / f_b[i],
                "psd_value": p_b[i],
                "direction": d_b[i],
            })

    # Sort by energy, keep top n
    peaks.sort(key=lambda x: x["psd_value"], reverse=True)
    return peaks[:n_peaks]


# =============================================================================
# 8. FUSION HELPER  — pitch / roll / heading from micropython-fusion
# =============================================================================
def run_fusion(samples: list, dt: float = 1.0 / NOMINAL_RATE_HZ) -> tuple:
    """
    Run micropython-fusion Mahony filter over all samples.

    Returns
    -------
    pitch_rad, roll_rad, yaw_ned_rad : (N,) arrays in radians
        yaw_ned_rad is corrected for magnetic declination.
    """
    try:
        from fusion import Fusion
    except ImportError:
        print("Warning: fusion.py not found. Using accel-only tilt estimate.")
        return _fallback_tilt(samples, dt)

    fuse = Fusion(lambda *_: dt)
    pitches, rolls, yaws = [], [], []

    for s in samples:
        accel = (s[0], s[1], s[2])
        gyro  = (s[3], s[4], s[5])
        mag   = (s[6], s[7], s[8])
        has_mag = any(v != 0.0 for v in mag)

        if has_mag:
            fuse.update(accel, gyro, mag, dt)
        else:
            fuse.update_nomag(accel, gyro, dt)

        pitches.append(math.radians(fuse.pitch))
        rolls.append(math.radians(fuse.roll))
        # Correct magnetic heading for declination → true heading
        true_heading = (fuse.heading + MAG_DECLINATION_DEG) % 360.0
        yaws.append(math.radians(true_heading))

    return np.array(pitches), np.array(rolls), np.array(yaws)


def _fallback_tilt(samples: list, dt: float = 1.0 / NOMINAL_RATE_HZ) -> tuple:
    """
    Estimate pitch and roll from accelerometer only (no gyro/mag).
    Heading assumed zero if fusion unavailable.
    """
    pitches, rolls, yaws = [], [], []
    for s in samples:
        ax, ay, az = s[0], s[1], s[2]
        pitch = math.atan2(-ax, math.sqrt(ay**2 + az**2))
        roll  = math.atan2(ay, az)
        pitches.append(pitch)
        rolls.append(roll)
        yaws.append(0.0)
    return np.array(pitches), np.array(rolls), np.array(yaws)


# =============================================================================
# 9. PLOTTING
# =============================================================================
def plot_heave_spectrum(freqs: np.ndarray, psd: np.ndarray,
                        peaks: list, Hs: float, Tp: float,
                        direction: np.ndarray = None):
    """
    Plot the heave energy spectrum (top) and mean wave direction per
    frequency (bottom) with annotated swell peaks on both panels.

    Parameters
    ----------
    freqs     : frequency bins (Hz)
    psd       : heave PSD (m²/Hz)
    peaks     : list of dicts from find_swell_peaks
    Hs, Tp    : significant wave height (m) and peak period (s)
    direction : mean wave direction per frequency bin (degrees, optional)
    """
    band = (freqs >= SWELL_FREQ_MIN) & (freqs <= SWELL_FREQ_MAX)
    n_panels = 2 if direction is not None else 1
    fig, axes = plt.subplots(n_panels, 1,
                             figsize=(12, 5 * n_panels),
                             sharex=True)
    if n_panels == 1:
        axes = [axes]   # keep indexing consistent

    # ── Top panel: PSD ────────────────────────────────────────────────────────
    ax_psd = axes[0]
    ax_psd.semilogy(freqs[band], psd[band], color="steelblue", linewidth=1.5,
                    label="Heave PSD")
    ax_psd.fill_between(freqs[band], psd[band], alpha=0.15, color="steelblue")

    colors = ["tab:red", "tab:orange", "tab:purple"]
    for i, peak in enumerate(peaks):
        c = colors[i % len(colors)]
        ax_psd.axvline(peak["freq"], color=c, linestyle="--", linewidth=1.2)
        ax_psd.annotate(
            f"Swell {i+1}\n"
            f"T = {peak['period']:.1f} s\n"
            f"Dir = {peak['direction']:.0f}°",
            xy=(peak["freq"], peak["psd_value"]),
            xytext=(peak["freq"] * 1.15, peak["psd_value"]),
            fontsize=8, color=c,
            arrowprops=dict(arrowstyle="->", color=c, lw=0.8),
        )

    ax_psd.set_title(
        f"Heave Energy Spectrum    Hs = {Hs:.2f} m    Tp = {Tp:.1f} s",
        fontsize=12,
    )
    ax_psd.set_ylabel("PSD (m² / Hz)")
    ax_psd.set_xlim(SWELL_FREQ_MIN, SWELL_FREQ_MAX)
    ax_psd.grid(True, which="both", linestyle="--", alpha=0.4)
    ax_psd.legend()

    # ── Bottom panel: direction ───────────────────────────────────────────────
    if direction is not None:
        ax_dir = axes[1]

        # Mask low-energy bins — direction estimate is unreliable where PSD is
        # near the noise floor (below 1 % of peak)
        noise_mask = psd >= (0.01 * np.max(psd[band]))
        valid = band & noise_mask

        ax_dir.scatter(freqs[valid], direction[valid],
                       s=12, color="steelblue", alpha=0.7, label="Mean direction")

        # Overlay a shaded ±std band using a simple running window if enough pts
        if np.sum(valid) > 5:
            ax_dir.plot(freqs[valid], direction[valid],
                        color="steelblue", linewidth=1.0, alpha=0.4)

        # Mark peak directions with coloured horizontal lines
        for i, peak in enumerate(peaks):
            c = colors[i % len(colors)]
            ax_dir.axvline(peak["freq"], color=c, linestyle="--",
                           linewidth=1.2, alpha=0.8)
            ax_dir.axhline(peak["direction"], color=c, linestyle=":",
                           linewidth=1.0, alpha=0.6,
                           label=f"Swell {i+1}: {peak['direction']:.0f}°")

        ax_dir.set_title("Mean Wave Direction per Frequency  "
                         "(0° = North, clockwise, waves arriving FROM)",
                         fontsize=11)
        ax_dir.set_ylabel("Direction (°)")
        ax_dir.set_xlabel("Frequency (Hz)")
        ax_dir.set_ylim(0, 360)
        ax_dir.set_yticks([0, 45, 90, 135, 180, 225, 270, 315, 360])
        ax_dir.set_yticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"])
        ax_dir.grid(True, which="both", linestyle="--", alpha=0.4)
        ax_dir.legend(fontsize=8)

    plt.tight_layout()


def plot_raw(data_dict: dict):
    """Plot raw accelerometer, gyroscope, and magnetometer traces."""
    samples    = data_dict.get("samples", [])
    timestamps = data_dict.get("timestamps")
    if not samples:
        return
    cols = list(zip(*samples))

    if timestamps is not None:
        x      = timestamps - timestamps[0]
        xlabel = "Time (s)  [from timestamps]"
    else:
        x      = np.arange(len(samples))
        xlabel = "Sample Index"

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    fig.suptitle("Raw IMU Data", fontsize=13)
    labels = ["X", "Y", "Z"]
    colors = ["tab:red", "tab:green", "tab:blue"]
    titles = ["Accelerometer (m/s²)", "Gyroscope (deg/s)", "Magnetometer (raw)"]
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
                  timestamps: np.ndarray = None, dt: float = 1.0 / NOMINAL_RATE_HZ):
    """Plot fused pitch, roll, and heading over time."""
    if timestamps is not None:
        t      = timestamps - timestamps[0]   # relative seconds from first sample
        xlabel = "Time (s)  [from timestamps]"
    else:
        t      = np.arange(len(pitch_rad)) * dt
        xlabel = f"Time (s)  [nominal {1/dt:.0f} Hz]"

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    fig.suptitle("Fused Attitude", fontsize=13)

    axes[0].plot(t, np.degrees(pitch_rad), color="tab:red")
    axes[0].set_title("Pitch (°)")
    axes[0].axhline(0, color="black", lw=0.6, ls="--")
    axes[0].grid(True, linestyle="--", alpha=0.4)

    axes[1].plot(t, np.degrees(roll_rad), color="tab:green")
    axes[1].set_title("Roll (°)")
    axes[1].axhline(0, color="black", lw=0.6, ls="--")
    axes[1].grid(True, linestyle="--", alpha=0.4)

    axes[2].plot(t, np.degrees(yaw_ned_rad) % 360, color="tab:blue")
    axes[2].set_title("True Heading (°)")
    axes[2].set_ylim(0, 360)
    axes[2].set_xlabel(xlabel)
    axes[2].grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":

    # ── 1. Load ───────────────────────────────────────────────────────────────
    data       = load_log("accel.csv")
    samples    = data["samples"]
    timestamps = data["timestamps"]   # np.ndarray or None
    fs         = data["fs"]
    dt         = data["dt"]

    if len(samples) < 10:
        raise SystemExit("Not enough samples to analyse.")

    # ── 2. Fusion → Euler angles ──────────────────────────────────────────────
    pitch_rad, roll_rad, yaw_ned_rad = run_fusion(samples, dt=dt)

    # ── 3. NED acceleration ───────────────────────────────────────────────────
    acc_ned = rotate_to_ned(samples, pitch_rad, roll_rad, yaw_ned_rad)
    acc_up  = -acc_ned[:, 2]   # NED down → negate for upward-positive heave

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
    print("  WAVE ANALYSIS SUMMARY")
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
    print("=" * 50 + "\n")

    # ── 10. Plots ─────────────────────────────────────────────────────────────
    plot_raw(data)
    plot_attitude(pitch_rad, roll_rad, yaw_ned_rad,
                  timestamps=timestamps, dt=dt)
    plot_heave_spectrum(freqs_dir, psd, peaks, Hs, Tp, direction=direction)

    plt.show()