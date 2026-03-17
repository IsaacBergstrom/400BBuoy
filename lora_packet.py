# lora_packet.py
# Encode/decode wave parameters into a compact binary LoRa payload.
# Total payload: 11 bytes  →  ~30 ms airtime at SF7/125kHz/4-5 CR

import struct

# Packet format (little-endian):
# Offset  Type     Field          Scale         Range
# 0       uint16   Hs             ×1000 (mm)    0–65.535 m
# 2       uint16   Tp             ×100 (cs)     0–655.35 s
# 4       uint32   energy         ×1e6          0–4294.967 m²
# 8       uint16   swell_dir      ×10 (0.1°)    0–3600 (→ 0–360°)
# 10      uint8    sequence       raw           0–255 (rollover counter)
# Total: 11 bytes

PACKET_FMT = "<HHIHb"   # 2+2+4+2+1 = 11 bytes

def encode_packet(Hs, Tp, energy, swell_dir, seq):
    """
    Pack wave parameters into an 11-byte binary payload.
    All values are scaled to integers to avoid float precision loss over the wire.
    """
    hs_int  = int(round(Hs       * 1000))
    tp_int  = int(round(Tp       * 100))
    en_int  = int(round(energy   * 1e6))
    sd_int  = int(round(swell_dir * 10)) % 3601
    seq_int = seq & 0xFF

    return struct.pack(PACKET_FMT, hs_int, tp_int, en_int, sd_int, seq_int)


def decode_packet(raw_bytes):
    """
    Unpack an 11-byte payload back into physical units.
    """
    if len(raw_bytes) != 11:
        raise ValueError(f"Expected 11 bytes, got {len(raw_bytes)}")

    hs_int, tp_int, en_int, sd_int, seq_int = struct.unpack(PACKET_FMT, raw_bytes)

    return {
        "Hs":        hs_int  / 1000.0,   # m
        "Tp":        tp_int  / 100.0,    # s
        "energy":    en_int  / 1e6,      # m²
        "swell_dir": sd_int  / 10.0,     # degrees
        "seq":       seq_int & 0xFF
    }


# ─── Usage in transmitter ──────────────────────────────────────────────────────
# params = compute_wave_params(accel_buffer)
# direction = estimate_swell_direction(ax_buf, ay_buf, az_buf, heading)
# payload = encode_packet(params["Hs"], params["Tp"], params["energy"], direction, seq)
# lora.println(payload)   # send raw bytes
