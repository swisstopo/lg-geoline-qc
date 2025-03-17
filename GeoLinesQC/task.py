from qgis.core import (QgsTask, QgsApplication, QgsProcessingFeedback,
                       QgsMessageLog, Qgis)
from qgis.PyQt.QtWidgets import QProgressDialog
from qgis.PyQt.QtCore import Qt, pyqtSignal


class ExtractionTask(QgsTask):
    """Task for running extraction in the background"""
    # Signal to update progress dialog from the main thread
    progress_update = pyqtSignal(int)

    def __init__(self, description, ref_layer, layer_to_check, distance, layer_name):
        super().__init__(description, QgsTask.CanCancel)
        self.ref_layer = ref_layer
        self.layer_to_check = layer_to_check
        self.distance = distance
        self.layer_name = layer_name
        self.result = None
        self.output_layer = None
        self.exception = None
        self.feedback = None

    def run(self):
        """Run the extraction task in the background"""
        from processing.core.Processing import Processing
        import processing

        # Need to initialize processing in the new thread
        Processing.initialize()

        # Create feedback for the processing algorithm
        self.feedback = QgsProcessingFeedback()

        try:
            # Create the processing parameters
            extract_within_params = {
                "INPUT": self.ref_layer,
                "PREDICATE": [6],  # Spatial predicate (6 = Within Distance)
                "INTERSECT": self.layer_to_check,
                "DISTANCE": self.distance,
                "OUTPUT": "memory:" + self.layer_name,
            }

            # Run the extraction
            QgsMessageLog.logMessage(f"Starting extraction within {self.distance} units", "DistanceExtraction")
            self.result = processing.run("native:extractbylocation", extract_within_params, feedback=self.feedback)
            self.output_layer = self.result["OUTPUT"]

            # Success
            return True

        except Exception as e:
            self.exception = e
            QgsMessageLog.logMessage(f"Error in extraction task: {str(e)}", "DistanceExtraction", level=Qgis.Critical)
            return False

    def cancel(self):
        """Cancel the task"""
        QgsMessageLog.logMessage("Extraction task canceled by user", "DistanceExtraction")
        if self.feedback:
            self.feedback.setCanceled(True)
        return super().cancel()