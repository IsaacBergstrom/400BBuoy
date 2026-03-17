# wave_dsp.py
# DSP pipeline: high-pass filter → double integration → FFT → Hs, Tp, Energy
# Designed for ESP32 MicroPython, fs=4Hz, N=512 samples

import math

# ─── Configuration ─────────────────────────────────────────────────────────────
FS   = 4.0    # Hz — sample rate
N    = 512    # FFT point count (power of 2)
G    = 9.81   # m/s²

# Wave frequency band of interest (Hz)
F_LOW  = 0.05  # 20 s swell
F_HIGH = 0.50  # 2 s chop


# ─── 1. High-Pass Butterworth Filter (1st order, fc=0.04 Hz) ──────────────────
# Prevents DC offset and low-frequency drift from blowing up double integration.
# Transfer function: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
# alpha = RC / (RC + dt), where RC = 1 / (2*pi*fc)

def make_highpass(fc=0.04, fs=FS):
    """Return a stateful high-pass filter closure."""
    rc = 1.0 / (2.0 * math.pi * fc)
    dt = 1.0 / fs
    alpha = rc / (rc + dt)
    prev_x = [0.0]
    prev_y = [0.0]

    def filter_sample(x):
        y = alpha * (prev_y[0] + x - prev_x[0])
        prev_x[0] = x
        prev_y[0] = y
        return y

    return filter_sample


# ─── 2. Trapezoidal Integrator ─────────────────────────────────────────────────

def integrate(signal, dt=1.0/FS):
    """Single integration using the trapezoidal rule."""
    result = [0.0] * len(signal)
    for i in range(1, len(signal)):
        result[i] = result[i-1] + 0.5 * (signal[i] + signal[i-1]) * dt
    return result


# ─── 3. Hanning Window ────────────────────────────────────────────────────────
# Reduces spectral leakage before FFT.

def hanning_window(n):
    return [0.5 * (1.0 - math.cos(2.0 * math.pi * i / (n - 1))) for i in range(n)]


# ─── 4. Radix-2 Cooley-Tukey FFT (in-place, real-valued input) ────────────────
# Returns the power spectrum (magnitude squared) for bins 0..N//2.

def fft(x_real):
    """
    In-place FFT. Input: list of floats (real signal, length must be power of 2).
    Returns: list of power spectral densities for bins 0..N//2.
    """
    n = len(x_real)
    x_imag = [0.0] * n

    # Bit-reversal permutation
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            x_real[i], x_real[j] = x_real[j], x_real[i]
            x_imag[i], x_imag[j] = x_imag[j], x_imag[i]

    # Cooley-Tukey butterfly
    length = 2
    while length <= n:
        half = length >> 1
        angle = -2.0 * math.pi / length
        w_re = math.cos(angle)
        w_im = math.sin(angle)
        for i in range(0, n, length):
            u_re, u_im = 1.0, 0.0
            for k in range(half):
                a, b = i + k, i + k + half
                t_re = u_re * x_real[b] - u_im * x_imag[b]
                t_im = u_re * x_imag[b] + u_im * x_real[b]
                x_real[b] = x_real[a] - t_re
                x_imag[b] = x_imag[a] - t_im
                x_real[a] += t_re
                x_imag[a] += t_im
                u_re, u_im = u_re * w_re - u_im * w_im, u_re * w_im + u_im * w_re
        length <<= 1

    # One-sided power spectrum (bins 1..N//2-1, doubled for energy conservation)
    half = n // 2
    psd = [0.0] * half
    psd[0] = (x_real[0]**2 + x_imag[0]**2) / n**2
    for k in range(1, half):
        psd[k] = 2.0 * (x_real[k]**2 + x_imag[k]**2) / n**2
    return psd


# ─── 5. Wave Parameter Extraction ─────────────────────────────────────────────

def compute_wave_params(accel_z_raw):
    """
    Input : list of N raw vertical acceleration samples (m/s²) at fs=4 Hz
            with gravity already subtracted (i.e. true dynamic acceleration).
    Output: dict with Hs (m), Tp (s), energy (m²), peak_freq (Hz)
    """
    if len(accel_z_raw) != N:
        raise ValueError(f"Expected {N} samples, got {len(accel_z_raw)}")

    # 1. High-pass filter (remove DC + drift)
    hp = make_highpass(fc=0.04, fs=FS)
    filtered = [hp(a) for a in accel_z_raw]

    # 2. Double-integrate acceleration → displacement
    #    Each integration stage also high-pass filters to prevent drift accumulation
    velocity     = integrate(filtered)
    hp2 = make_highpass(fc=0.04, fs=FS)
    velocity     = [hp2(v) for v in velocity]

    displacement = integrate(velocity)
    hp3 = make_highpass(fc=0.04, fs=FS)
    displacement = [hp3(d) for d in displacement]

    # 3. Apply Hanning window
    win = hanning_window(N)
    windowed = [displacement[i] * win[i] for i in range(N)]

    # 4. FFT → power spectrum
    psd = fft(windowed)

    # 5. Extract parameters from wave band [F_LOW, F_HIGH]
    df = FS / N  # frequency resolution per bin

    m0 = 0.0   # 0th spectral moment (variance = energy)
    m1 = 0.0   # 1st spectral moment
    peak_power = 0.0
    peak_bin   = 1

    for k in range(1, N // 2):
        f = k * df
        if F_LOW <= f <= F_HIGH:
            m0 += psd[k] * df
            m1 += f * psd[k] * df
            if psd[k] > peak_power:
                peak_power = psd[k]
                peak_bin   = k

    peak_freq = peak_bin * df
    Tp = 1.0 / peak_freq if peak_freq > 0 else 0.0

    # Hs = 4 * sqrt(m0)  — the standard oceanographic definition
    Hs = 4.0 * math.sqrt(max(m0, 0.0))

    return {
        "Hs":        round(Hs, 3),       # Significant wave height (m)
        "Tp":        round(Tp, 2),       # Peak wave period (s)
        "energy":    round(m0, 5),       # Wave energy (m²)
        "peak_freq": round(peak_freq, 4) # Peak frequency (Hz)
    }
