# wave_direction.py
# Computes primary swell direction relative to magnetic North.
# Strategy: correlate horizontal accelerations (ax, ay) with vertical (az)
# to find the axis of maximum wave energy, then rotate to world frame using
# the magnetometer heading.

import math


def compute_heading(mx, my, mz, roll_rad, pitch_rad):
    """
    Tilt-compensated magnetic heading.
    Inputs : raw magnetometer readings (µT) + roll/pitch from accelerometer (rad)
    Output : heading in degrees from magnetic North (0–360)

    QMC5883P axis note: check your chip orientation — you may need to negate
    one axis depending on how the board is mounted in the buoy.
    """
    # Tilt-compensate the magnetometer readings
    cos_r, sin_r = math.cos(roll_rad),  math.sin(roll_rad)
    cos_p, sin_p = math.cos(pitch_rad), math.sin(pitch_rad)

    mx2 = mx * cos_p + mz * sin_p
    my2 = mx * sin_r * sin_p + my * cos_r - mz * sin_r * cos_p

    heading_rad = math.atan2(-my2, mx2)  # atan2(East, North)
    heading_deg = math.degrees(heading_rad) % 360.0
    return round(heading_deg, 1)


def compute_roll_pitch(ax, ay, az):
    """
    Estimate roll and pitch from accelerometer (static / slow-motion assumption).
    Good enough for a buoy where orientation changes are slow relative to fs=4Hz.
    """
    roll  = math.atan2(ay, az)
    pitch = math.atan2(-ax, math.sqrt(ay**2 + az**2))
    return roll, pitch


def estimate_swell_direction(ax_buf, ay_buf, az_buf, heading_deg):
    """
    Estimate primary swell direction by finding the horizontal axis with
    maximum correlation to vertical motion (cross-spectral method, simplified).

    For a full capstone implementation, replace with proper directional
    wave spectrum using the Longuet-Higgins (1963) formula:
        S(f, θ) ∝ Re[Qxz(f)*cos(θ) + Qyz(f)*sin(θ)]

    This simplified version gives ±180° ambiguity — add a sign check from
    the instantaneous acceleration direction to resolve it.

    Inputs : N-sample buffers for ax, ay, az (already high-pass filtered)
    Output : swell direction in degrees True (0 = North, 90 = East)
    """
    n = len(ax_buf)

    # Variance of horizontal axes weighted by correlation with vertical
    cov_xz = sum(ax_buf[i] * az_buf[i] for i in range(n)) / n
    cov_yz = sum(ay_buf[i] * az_buf[i] for i in range(n)) / n

    # Angle of maximum covariance in the buoy's local frame
    local_angle_rad = math.atan2(cov_yz, cov_xz)
    local_angle_deg = math.degrees(local_angle_rad)

    # Rotate to geographic frame using magnetic heading
    # (add local magnetic declination offset for your region if needed)
    swell_dir = (heading_deg + local_angle_deg) % 360.0
    return round(swell_dir, 1)
