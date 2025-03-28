import os
import threading

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QDateTime

# Global lock for thread-safe file writing
_log_lock = threading.Lock()


def log_message(message, level=Qgis.Info, log_file_path=None):
    """
    Thread-safe logging to both file and QgsMessageLog.

    Args:
        message (str): The message to log
        level (Qgis.MessageLevel): Info, Warning, or Critical/Error
        log_file_path (str): Path to log file
    """

    if log_file_path is None:
        profile_path = QgsApplication.qgisSettingsDirPath()

        # Construct the path to your plugin's logs directory
        log_file_path = os.path.join(
            profile_path, "python", "plugins", "GeoLinesQC", "logs", "debug.log"
        )
    timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
    log_entry = f"[{timestamp}] {message}"

    # Thread-safe file writing
    with _log_lock:
        try:
            with open(log_file_path, "a") as log_file:
                log_file.write(log_entry + "\n")
        except (IOError, OSError) as e:
            # Use QgsMessageLog directly (no file ops) if writing fails
            QgsMessageLog.logMessage(
                f"Failed to write to log file: {str(e)}",
                "GeoLinesProcessing",
                Qgis.Warning,
            )

    # Log to QgsMessageLog based on level
    if level in (Qgis.Info, Qgis.Warning, Qgis.Critical):
        QgsMessageLog.logMessage(message, "GeoLinesProcessing", level)
