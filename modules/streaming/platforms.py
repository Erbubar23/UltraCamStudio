"""
UltraCam Studio - Plataformas de transmisión y lo que exige cada una.

Fuentes (2026): guías de ingesta de cada plataforma y de Restream/OBS. Todas aceptan H.264
con AAC, fotograma clave cada 2 s y bitrate constante (Kick rechaza el variable). Facebook
exige RTMPS por el puerto 443. TikTok e Instagram son verticales (9:16) y su clave cambia en
cada directo; TikTok solo da clave a cuentas habilitadas.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    orientation: str               # "h" (16:9) o "v" (9:16)
    server: str                    # servidor sugerido ("" = lo da la plataforma en su panel)
    max_kbps: int                  # bitrate de video que acepta (o recomienda) como máximo
    key_per_session: bool = False  # la clave cambia en cada directo: se pide antes de salir
    help: str = ""
    color: str = "#3A3A40"         # color de la marca, para su símbolo
    glyph: str = "●"               # símbolo (sin logos de terceros incluidos en la app)
    glyph_color: str = "#FFFFFF"


PLATFORMS: Dict[str, Platform] = {p.key: p for p in (
    Platform("youtube", "YouTube", "h", "rtmps://a.rtmps.youtube.com/live2", 9000,
             help="YouTube Studio › Emitir en directo › Clave de transmisión.", color="#FF0033", glyph="▶"),
    Platform("twitch", "Twitch", "h", "rtmps://ingest.global-contribute.live-video.net/app", 6000,
             help="Panel de creador › Configuración › Transmisión › Clave principal.", color="#9146FF", glyph="T"),
    Platform("facebook", "Facebook", "h", "rtmps://live-api-s.facebook.com:443/rtmp", 6000,
             help="Live Producer › Software de transmisión › Clave (siempre RTMPS).", color="#1877F2", glyph="f"),
    Platform("kick", "Kick", "h", "", 8000,
             help="Panel del canal › Stream URL and Key: copia la URL (rtmps://…) y la clave.",
             color="#53FC18", glyph="K", glyph_color="#0B0B0B"),
    Platform("tiktok", "TikTok", "v", "", 6000, key_per_session=True,
             help="LIVE Studio o Centro LIVE › Servidor y clave. Cambian en cada directo; "
                  "solo cuentas habilitadas para transmitir desde PC.", color="#111111", glyph="♪"),
    Platform("instagram", "Instagram", "v", "", 6000, key_per_session=True,
             help="Live Producer (cuenta profesional) › URL y clave. Cambian en cada directo.",
             color="#E1306C", glyph="IG"),
    Platform("custom", "RTMP propio", "h", "", 20000,
             help="Cualquier servidor RTMP/RTMPS, o un servicio que reparte por ti (Restream).",
             color="#3A3A40", glyph="R"),
)}


def get(key: str) -> Platform:
    return PLATFORMS.get(key, PLATFORMS["custom"])


def ingest_url(server: str, stream_key: str) -> Optional[str]:
    """URL para MediaMTX: «servidor#clave» (así la clave no queda escrita en su registro)."""
    server = (server or "").strip().rstrip("/")
    stream_key = (stream_key or "").strip()
    if not server.lower().startswith(("rtmp://", "rtmps://")) or not stream_key:
        return None
    return f"{server}#{stream_key}"


def redact(url: str) -> str:
    """Para el registro: la clave nunca se muestra."""
    return (url or "").split("#", 1)[0] + ("#•••" if "#" in (url or "") else "")
