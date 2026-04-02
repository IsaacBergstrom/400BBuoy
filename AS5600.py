"""
as5600.py
=========
MicroPython driver for the AS5600 12-bit magnetic angle sensor.

Usage
-----
    from machine import I2C, Pin
    from as5600 import AS5600

    i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400_000)
    sensor = AS5600(i2c)

    # Check magnet is in range before reading
    if sensor.magnet_detected:
        print(sensor.raw_angle)   # 0–4095
        print(sensor.angle_deg)   # 0.0–359.9°
        print(sensor.angle_rad)   # 0.0–2π

Register map (AS5600 datasheet rev 1.9)
---------------------------------------
    0x00        ZMCO       R     Burn count
    0x01–0x02   ZPOS       R/W   Zero position (12-bit)
    0x03–0x04   MPOS       R/W   Maximum position (12-bit)
    0x05–0x06   MANG       R/W   Maximum angle (12-bit)
    0x07–0x08   CONF       R/W   Configuration register
    0x0B        STATUS     R     Magnet status flags
    0x0C–0x0D   RAWANGLE   R     Unscaled angle (12-bit)
    0x0E–0x0F   ANGLE      R     Scaled/filtered angle (12-bit)
    0x1A        AGC        R     Automatic gain control
    0x1B–0x1C   MAGNITUDE  R     CORDIC magnitude (12-bit)
    0xFF        BURN       W     Burn command (irreversible!)
"""

import math
from micropython import const

# ── I2C address ───────────────────────────────────────────────────────────────
_AS5600_ADDR = const(0x36)   # fixed — cannot be changed in hardware

# ── Register addresses ────────────────────────────────────────────────────────
_REG_ZMCO      = const(0x00)
_REG_ZPOS_H    = const(0x01)
_REG_MPOS_H    = const(0x03)
_REG_MANG_H    = const(0x05)
_REG_CONF_H    = const(0x07)
_REG_STATUS    = const(0x0B)
_REG_RAWANGLE_H = const(0x0C)
_REG_ANGLE_H   = const(0x0E)
_REG_AGC       = const(0x1A)
_REG_MAGNITUDE_H = const(0x1B)
_REG_BURN      = const(0xFF)

# ── STATUS register bit positions ─────────────────────────────────────────────
_STATUS_MD = const(5)   # Magnet Detected
_STATUS_ML = const(4)   # Magnet too weak  (Low)
_STATUS_MH = const(3)   # Magnet too strong (High)

# ── CONF register bit positions ───────────────────────────────────────────────
# Byte 0x07 (high byte of CONF)
_CONF_WD    = const(13)  # Watchdog
_CONF_FTH_H = const(12)  # Fast filter threshold [2:0] — bits 12:10
_CONF_SF    = const(8)   # Slow filter [1:0]       — bits 9:8
# Byte 0x08 (low byte of CONF)
_CONF_PWMF  = const(6)   # PWM frequency [1:0]
_CONF_OUTS  = const(4)   # Output stage [1:0]
_CONF_HYST  = const(2)   # Hysteresis [1:0]
_CONF_PM    = const(0)   # Power mode [1:0]

# ── BURN commands ─────────────────────────────────────────────────────────────
_BURN_ANGLE   = const(0x80)   # burn ZPOS/MPOS
_BURN_SETTING = const(0x40)   # burn CONF/MANG

# ── Conversion constants ──────────────────────────────────────────────────────
_RAW_TO_DEG = 360.0 / 4096.0
_RAW_TO_RAD = (2.0 * math.pi) / 4096.0


# =============================================================================
# Low-level helpers
# =============================================================================

def _read1(i2c, addr, reg):
    """Read one byte from a register."""
    buf = bytearray(1)
    i2c.readfrom_mem_into(addr, reg, buf)
    return buf[0]


def _read2(i2c, addr, reg):
    """
    Read two consecutive bytes and combine big-endian into a 16-bit integer.
    The AS5600 always sends MSB first (big-endian), so reg is the high byte
    and reg+1 is the low byte.
    """
    buf = bytearray(2)
    i2c.readfrom_mem_into(addr, reg, buf)
    return (buf[0] << 8) | buf[1]


def _write2(i2c, addr, reg, value):
    """Write a 16-bit value big-endian to reg (high) and reg+1 (low)."""
    buf = bytearray([(value >> 8) & 0xFF, value & 0xFF])
    i2c.writeto_mem(addr, reg, buf)


def _write1(i2c, addr, reg, value):
    """Write one byte to a register."""
    i2c.writeto_mem(addr, reg, bytearray([value & 0xFF]))


# =============================================================================
# Main driver
# =============================================================================

class AS5600:
    """
    Driver for the AS5600 12-bit magnetic angle sensor.

    Parameters
    ----------
    i2c  : machine.I2C
        Configured I2C bus object.
    addr : int
        I2C address (default 0x36 — the only valid address for AS5600).
    """

    def __init__(self, i2c, addr=_AS5600_ADDR):
        self._i2c  = i2c
        self._addr = addr
        self._verify_connection()

    # ── Connection check ──────────────────────────────────────────────────────

    def _verify_connection(self):
        """Raise an error if the AS5600 is not responding on the I2C bus."""
        devices = self._i2c.scan()
        if self._addr not in devices:
            found = [hex(d) for d in devices]
            raise OSError(
                f"AS5600 not found at I2C address {hex(self._addr)}. "
                f"Devices found: {found}"
            )

    # ── Magnet status ─────────────────────────────────────────────────────────

    @property
    def status(self):
        """Raw STATUS register byte."""
        return _read1(self._i2c, self._addr, _REG_STATUS)

    @property
    def magnet_detected(self):
        """True if a magnet with acceptable field strength is detected (MD bit)."""
        return bool((self.status >> _STATUS_MD) & 1)

    @property
    def magnet_too_weak(self):
        """True if the magnetic field is too weak — move magnet closer (ML bit)."""
        return bool((self.status >> _STATUS_ML) & 1)

    @property
    def magnet_too_strong(self):
        """True if the magnetic field is too strong — move magnet further away (MH bit)."""
        return bool((self.status >> _STATUS_MH) & 1)

    def check_magnet(self):
        """
        Print a human-readable magnet status summary.
        Useful for debugging alignment and air-gap issues.
        """
        s = self.status
        md = (s >> _STATUS_MD) & 1
        ml = (s >> _STATUS_ML) & 1
        mh = (s >> _STATUS_MH) & 1
        print(f"AS5600 Magnet Status:")
        print(f"  Detected (MD) : {'YES' if md else 'NO'}")
        print(f"  Too weak  (ML): {'YES — move magnet closer' if ml else 'no'}")
        print(f"  Too strong(MH): {'YES — move magnet further away' if mh else 'no'}")
        if md and not ml and not mh:
            print("  ✓ Magnet is in range — angle readings are valid.")
        else:
            print("  ✗ Angle readings are NOT reliable until magnet is in range.")
        return md, ml, mh

    # ── Angle readings ────────────────────────────────────────────────────────

    @property
    def raw_angle(self):
        """
        Unscaled raw angle from the ADC (0–4095).
        Not affected by ZPOS/MPOS/MANG settings.
        Use this to verify the sensor is working and to set zero position.
        """
        return _read2(self._i2c, self._addr, _REG_RAWANGLE_H) & 0x0FFF

    @property
    def angle(self):
        """
        Scaled and filtered angle (0–4095), adjusted by ZPOS/MPOS/MANG
        and filtered according to CONF settings.
        This is the value to use in production.
        """
        return _read2(self._i2c, self._addr, _REG_ANGLE_H) & 0x0FFF

    @property
    def angle_deg(self):
        """Scaled angle in degrees (0.0–359.91°)."""
        return self.angle * _RAW_TO_DEG

    @property
    def angle_rad(self):
        """Scaled angle in radians (0.0–2π)."""
        return self.angle * _RAW_TO_RAD

    @property
    def raw_angle_deg(self):
        """Raw (unscaled) angle in degrees (0.0–359.91°)."""
        return self.raw_angle * _RAW_TO_DEG

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @property
    def agc(self):
        """
        Automatic Gain Control value (0–255).
        Lower = stronger field, higher = weaker field.
        Ideal range is roughly 70–180 for 3.3 V supply.
        """
        return _read1(self._i2c, self._addr, _REG_AGC)

    @property
    def magnitude(self):
        """CORDIC magnitude of the magnetic field vector (0–4095)."""
        return _read2(self._i2c, self._addr, _REG_MAGNITUDE_H) & 0x0FFF

    @property
    def burn_count(self):
        """Number of times the OTP has been burned (0–3 for angle, max 1 for settings)."""
        return _read1(self._i2c, self._addr, _REG_ZMCO) & 0x03

    # ── Zero / range configuration ────────────────────────────────────────────

    @property
    def zero_position(self):
        """ZPOS — start angle for the output range (0–4095)."""
        return _read2(self._i2c, self._addr, _REG_ZPOS_H) & 0x0FFF

    @zero_position.setter
    def zero_position(self, value):
        """Set ZPOS. The sensor remaps 0° to this raw angle."""
        _write2(self._i2c, self._addr, _REG_ZPOS_H, int(value) & 0x0FFF)

    @property
    def max_position(self):
        """MPOS — end angle for the output range (0–4095)."""
        return _read2(self._i2c, self._addr, _REG_MPOS_H) & 0x0FFF

    @max_position.setter
    def max_position(self, value):
        _write2(self._i2c, self._addr, _REG_MPOS_H, int(value) & 0x0FFF)

    @property
    def max_angle(self):
        """MANG — maximum angle range in raw counts (0–4095, minimum ~18°)."""
        return _read2(self._i2c, self._addr, _REG_MANG_H) & 0x0FFF

    @max_angle.setter
    def max_angle(self, value):
        _write2(self._i2c, self._addr, _REG_MANG_H, int(value) & 0x0FFF)

    def set_zero_here(self):
        """
        Convenience method: set ZPOS to the current raw angle so the
        current shaft position reads as 0°.
        Does NOT burn to OTP — resets on power cycle unless burned.
        """
        current = self.raw_angle
        self.zero_position = current
        print(f"Zero position set to raw angle {current} "
              f"({current * _RAW_TO_DEG:.2f}°)")
        return current

    # ── Configuration register ────────────────────────────────────────────────

    @property
    def conf(self):
        """Raw 14-bit CONF register value."""
        return _read2(self._i2c, self._addr, _REG_CONF_H) & 0x3FFF

    @conf.setter
    def conf(self, value):
        _write2(self._i2c, self._addr, _REG_CONF_H, int(value) & 0x3FFF)

    def _conf_set_bits(self, shift, mask, value):
        """Read-modify-write a bitfield in CONF."""
        current = self.conf
        current &= ~(mask << shift)
        current |= (int(value) & mask) << shift
        self.conf = current

    def set_power_mode(self, mode):
        """
        PM bits [1:0]:
            0 = NOM (default, always on)
            1 = LPM1 (~3.4 mA, polling every 5 ms)
            2 = LPM2 (~1.8 mA, polling every 20 ms)
            3 = LPM3 (~1.5 mA, polling every 100 ms)
        """
        self._conf_set_bits(0, 0x3, mode)

    def set_hysteresis(self, hyst):
        """
        HYST bits [1:0]:
            0 = OFF (default)
            1 = 1 LSB
            2 = 2 LSBs
            3 = 3 LSBs
        """
        self._conf_set_bits(2, 0x3, hyst)

    def set_slow_filter(self, sf):
        """
        SF bits [1:0] (applied when fast filter is inactive):
            0 = 16x (default, most smoothing)
            1 = 8x
            2 = 4x
            3 = 2x
        """
        self._conf_set_bits(8, 0x3, sf)

    def set_fast_filter(self, fth):
        """
        FTH bits [2:0] — fast filter threshold:
            0 = slow filter only (default)
            1–7 = increasing threshold for fast filter activation
        """
        self._conf_set_bits(10, 0x7, fth)

    def set_watchdog(self, enable):
        """Enable (True) or disable (False) the watchdog timer."""
        self._conf_set_bits(13, 0x1, 1 if enable else 0)

    # ── OTP burn (IRREVERSIBLE — use with caution) ────────────────────────────

    def burn_angle(self):
        """
        Permanently burn ZPOS and MPOS to OTP memory.

        WARNING: IRREVERSIBLE. Can only be done up to 3 times total.
        Magnet must be detected before burning.
        """
        if not self.magnet_detected:
            raise RuntimeError(
                "Cannot burn angle: magnet not detected. "
                "Ensure MD=1 before burning."
            )
        if self.burn_count >= 3:
            raise RuntimeError(
                "Cannot burn angle: OTP already burned 3 times (maximum)."
            )
        _write1(self._i2c, self._addr, _REG_BURN, _BURN_ANGLE)
        print("WARNING: ZPOS/MPOS burned to OTP. This is permanent.")

    def burn_setting(self):
        """
        Permanently burn MANG and CONF to OTP memory.

        WARNING: IRREVERSIBLE. Can only be done once.
        Magnet must be detected before burning.
        """
        if not self.magnet_detected:
            raise RuntimeError(
                "Cannot burn settings: magnet not detected. "
                "Ensure MD=1 before burning."
            )
        _write1(self._i2c, self._addr, _REG_BURN, _BURN_SETTING)
        print("WARNING: MANG/CONF burned to OTP. This is permanent.")

    # ── String representation ─────────────────────────────────────────────────

    def __repr__(self):
        try:
            md, ml, mh = (
                self.magnet_detected,
                self.magnet_too_weak,
                self.magnet_too_strong,
            )
            status_str = "OK" if (md and not ml and not mh) else "CHECK MAGNET"
            return (
                f"AS5600(addr={hex(self._addr)}, "
                f"angle={self.angle_deg:.2f}°, "
                f"agc={self.agc}, "
                f"magnet={status_str})"
            )
        except Exception as e:
            return f"AS5600(addr={hex(self._addr)}, error={e})"