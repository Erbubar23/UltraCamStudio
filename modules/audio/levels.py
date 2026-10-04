"""
UltraCam Studio - Formato de niveles de audio.
"""

import math


def vol_to_db_text(v: float) -> str:
    if v <= 0.001:
        return "−∞ dB"
    db = 20 * math.log10(v)
    return f"{db:+.1f} dB".replace("-", "−")
