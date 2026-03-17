# drift_prevention.py
# Standalone demonstration of the three-stage HP filter strategy.
# This is already integrated into wave_dsp.py above — this file
# explains WHY each stage exists.

import math

def make_highpass(fc=0.04, fs=4.0):
    """
    1st-order IIR high-pass filter.

    fc = 0.04 Hz  → passes everything above ~25 seconds period
    This is safely below F_LOW=0.05 Hz so we don't attenuate real waves,
    but aggressively blocks the sub-0.04 Hz drift that causes runaway integration.

    The recurrence relation:
        y[n] = α · (y[n-1] + x[n] - x[n-1])
        α = τ / (τ + Δt)
        τ = 1 / (2π·fc) = 3.98 s

    At fc=0.04 Hz and fs=4 Hz:
        α = 3.98 / (3.98 + 0.25) = 0.9409
    """
    tau   = 1.0 / (2.0 * math.pi * fc)
    dt    = 1.0 / fs
    alpha = tau / (tau + dt)

    state = {"x_prev": 0.0, "y_prev": 0.0}

    def apply(x):
        y = alpha * (state["y_prev"] + x - state["x_prev"])
        state["x_prev"] = x
        state["y_prev"] = y
        return y

    return apply


# Pipeline:
#
#   raw_az  → HP1 → filtered_az
#                        ↓
#                  integrate → velocity → HP2 → clean_velocity
#                                                     ↓
#                                              integrate → displacement → HP3 → clean_displacement
#
# HP1: strips DC offset from the accelerometer (gravity residual after
#      subtracting g is never perfectly zero due to tilt).
#
# HP2: strips any velocity drift that accumulated during the first integration.
#      Without this, a tiny bias in filtered_az becomes a growing velocity trend.
#
# HP3: strips displacement drift. This is the most important stage.
#      The final output is a zero-mean displacement signal — exactly what
#      the FFT expects for an unbiased spectral estimate.
#
# Rule of thumb: any time you integrate in MicroPython, add a HP filter
# immediately after. Never integrate twice without filtering in between.
