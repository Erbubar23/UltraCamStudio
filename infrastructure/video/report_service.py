"""
Servicio de generación de reportes de diagnóstico técnico con IA.
Los reportes se quedan en la PC del usuario: nada se envía por internet.
Aislado del núcleo de captura de video (SRP).
"""

import os
import sys
import uuid
import json
import platform
import datetime
from typing import Dict, Any, Optional, List
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class ReportService:
    """Genera reportes de diagnóstico en formato JSON y los guarda localmente."""

    @staticmethod
    def generate_ai_report(user_notes: str, active_config: Optional[dict],
                           env_paths: Dict[str, Optional[str]],
                           device_info: Dict[str, Any],
                           log_trace: List[str]) -> Dict[str, Any]:
        report_id = f"ULTRA-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.datetime.now().isoformat()
        filtered_logs = [l for l in log_trace[-200:] if "[POLL]" not in l]

        return {
            "report_id": report_id,
            "timestamp": now_iso,
            "user_notes": user_notes.strip() if user_notes else "Sin notas adicionales del usuario.",
            "host_environment": {
                "os": platform.platform(),
                "python_version": sys.version.split()[0],
                "scrcpy_path": env_paths.get("scrcpy_path"),
                "adb_path": env_paths.get("adb_path"),
                "ffmpeg_path": env_paths.get("ffmpeg_path")
            },
            "connected_device": device_info,
            "active_stream_config": active_config or {},
            "session_log_trace": filtered_logs
        }

    @staticmethod
    def save_problem_report(report: Dict[str, Any]) -> Dict[str, Any]:
        """Guarda el reporte en Videos\\GalaxyCam\\reportes y prepara el texto para el portapapeles."""
        report_json_min = json.dumps(report, separators=(',', ':'), ensure_ascii=False)
        report_json_pretty = json.dumps(report, indent=2, ensure_ascii=False)

        report_dir = os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam", "reportes")
        os.makedirs(report_dir, exist_ok=True)
        file_name = f"Reporte_IA_{report['report_id']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(report_dir, file_name)

        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(report_json_pretty)
            GLOBAL_LOGGER.log(f"Reporte IA guardado en: {full_path}", "REPORT")
        except Exception as e:
            GLOBAL_LOGGER.log(f"Error guardando reporte local: {e}", "WARN")

        clipboard_ai_prompt = (
            f"=== DIAGNÓSTICO DE ERROR ULTRACAM PRO ===\n"
            f"Analiza este reporte técnico y propón soluciones:\n\n"
            f"```json\n{report_json_pretty}\n```"
        )

        return {
            "success": True,
            "report_id": report["report_id"],
            "file_path": full_path,
            "clipboard_text": clipboard_ai_prompt,
            "json_summary": report_json_min
        }
