from qgis.core import (QgsTask, QgsApplication, QgsProcessingFeedback,
                       QgsMessageLog, Qgis)
from qgis.PyQt.QtWidgets import QProgressDialog
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsTask, QgsApplication, QgsProcessingFeedback, QgsMessageLog, Qgis, QgsProject
from qgis.PyQt.QtWidgets import QProgressDialog
from qgis.PyQt.QtCore import Qt, QTimer

from GeoLinesQC.errors import ClipError

class ClipLayerTask(QgsTask):
    """Task for clipping a layer with a mask layer"""

    def __init__(self, description, input_layer, mask_layer, output_name):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.mask_layer = mask_layer
        self.output_name = output_name
        self.output_layer = None
        self.exception = None
        self.feedback = None

    def run(self):
        """Run the clipping in the background"""
        import processing
        from processing.core.Processing import Processing

        # Initialize processing in this thread
        Processing.initialize()

        # Create feedback
        self.feedback = QgsProcessingFeedback()

        try:
            # Create processing parameters
            clip_params = {
                "INPUT": self.input_layer,
                "OVERLAY": self.mask_layer,
                "OUTPUT": f"memory:{self.output_name}"
            }

            # Run the clip algorithm
            result = processing.run("native:clip", clip_params, feedback=self.feedback)
            self.output_layer = result["OUTPUT"]

            # Check if any features were clipped
            if self.output_layer.featureCount() == 0:
                self.exception = ClipError(f"No features found in the clipped layer: {self.output_name}")
                return False

            return True
        except Exception as e:
            self.exception = e
            return False

    def cancel(self):
        """Cancel the task"""
        if self.feedback:
            self.feedback.setCanceled(True)
        return super().cancel()


class ExtractionTask(QgsTask):
    """Task for extracting features within a distance"""

    def __init__(self, description, input_layer, reference_layer, distance, output_name):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.distance = distance
        self.output_name = output_name
        self.output_layer = None
        self.exception = None
        self.feedback = None

    def run(self):
        """Run the extraction in the background"""
        import processing
        from processing.core.Processing import Processing

        # Initialize processing in this thread
        Processing.initialize()

        # Create feedback
        self.feedback = QgsProcessingFeedback()

        try:
            # Create the processing parameters
            extract_within_params = {
                "INPUT": self.input_layer,
                "PREDICATE": [6],  # Spatial predicate (6 = Within Distance)
                "INTERSECT": self.reference_layer,
                "DISTANCE": self.distance,
                "OUTPUT": f"memory:{self.output_name}"
            }

            # Run the extraction algorithm
            result = processing.run("native:extractbylocation", extract_within_params, feedback=self.feedback)
            self.output_layer = result["OUTPUT"]

            # Check if any features were extracted
            if self.output_layer.featureCount() == 0:
                self.exception = ClipError(f"No features found within distance in layer: {self.output_name}")
                return False

            return True
        except Exception as e:
            self.exception = e
            return False

    def cancel(self):
        """Cancel the task"""
        if self.feedback:
            self.feedback.setCanceled(True)
        return super().cancel()

    def finished(self, result):
        """Handle the task completion"""
        if self.exception:
            QgsMessageLog.logMessage(
                f"Task failed: {str(self.exception)}", "GeoLinesQC",  level=Qgis.Critical

            )
            self.finished.emit(False)
        else:
            QgsMessageLog.logMessage(
            "ExtractionTask completed successfully.", "GeoLinesQC", level=Qgis.Success
            )
            # Optionally add the output layer to the map
            QgsProject.instance().addMapLayer(self.output_layer)



'''class SegmentAndCheckTask(QgsTask):
    """Task for segmenting and checking intersections"""

    def __init__(self, description, input_layer, reference_layer, segment_length, buffer_distance):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.segment_length = segment_length
        self.buffer_distance = buffer_distance
        self.output_layer = None
        self.exception = None
        self.feedback = None

    def run(self):
        """Run the segmentation and intersection check in the background"""
        # Create feedback
        self.feedback = QgsProcessingFeedback()

        try:
            # This is a placeholder for your actual segment_and_check_intersections method
            # You'll need to adapt your existing method to work with the QgsTask framework

            # Example implementation (to be replaced with your actual code):
            # self.output_layer = self.segment_and_check_intersections_impl(
            #     self.input_layer,
            #     self.reference_layer,
            #     self.segment_length,
            #     self.buffer_distance,
            #     self.feedback
            # )

            # Instead of directly calling your method, you'd implement the logic here
            # making sure to periodically check self.feedback.isCanceled() and update
            # self.feedback.setProgress() to report progress

            # For now, we'll just call the method directly, but in a real implementation,
            # you should adapt the method to work with the task framework
            from qgis.core import QgsProject
            # Call your original method but make sure it doesn't modify the UI directly
            # This is just a placeholder - you'll need to adapt your actual method
            self.output_layer = self.segment_and_check_intersections_impl(
                self.input_layer,
                self.reference_layer,
                self.segment_length,
                self.buffer_distance
            )

            return True
        except Exception as e:
            self.exception = e
            return False

    def cancel(self):
        """Cancel the task"""
        if self.feedback:
            self.feedback.setCanceled(True)
        return super().cancel()

    def segment_and_check_intersections_impl(self, input_layer, reference_layer, segment_length, buffer_distance):
        """
        Implementation of the segmentation and intersection check logic
        This is a placeholder - you need to adapt your actual method to work here
        """
        # This is where you'd implement your segment_and_check_intersections logic
        # but adapted to work in a background task

        # For example, if your original method creates a new layer and modifies the UI,
        # you'd need to modify it to just return the layer without modifying the UI

        # This is just a placeholder - replace with your actual implementation
        return None'''

class SegmentAndCheckTask(QgsTask):
    """Task for segmenting and checking intersections"""

    def __init__(self, description, input_layer, reference_layer, segment_length, buffer_distance):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.segment_length = segment_length
        self.buffer_distance = buffer_distance
        self.output_layer = None
        self.exception = None
        self.feedback = QgsProcessingFeedback()

    def run(self):
        """Run the segmentation and intersection analysis in the background"""
        try:
            # Run segmentation and intersection in the background
            self.output_layer = self.segment_and_check_intersections_bg(
                self.input_layer,
                self.reference_layer,
                self.segment_length,
                self.buffer_distance
            )
            return True  # Task completed successfully
        except Exception as e:
            self.exception = e
            QgsMessageLog.logMessage(f"Error in analysis task: {str(e)}", "GeoLinesQC", level=Qgis.Critical)
            return False  # Task failed

    def segment_and_check_intersections_bg(self, input_layer, reference_layer, segment_length, buffer_distance):
        """
        Background-friendly implementation of segment_and_check_intersections.
        Supports progress reporting and cancellation.
        """
        # Create a new memory layer to store the results
        output_layer = QgsVectorLayer(
            f"LineString?crs={input_layer.crs().authid()}",
            f"Segmented {input_layer.name()}",
            "memory"
        )
        output_layer.dataProvider().addAttributes([
            QgsField("id", QVariant.Int),
            QgsField("intersects", QVariant.Bool)  # Field to store intersection results
        ])
        output_layer.updateFields()

        total_features = input_layer.featureCount()
        nb_segments = 0  # Counter for segments added

        # Iterate through features in the input layer
        for i, feature in enumerate(input_layer.getFeatures()):
            # Check if the task has been cancelled
            if self.feedback.isCanceled():
                return None  # Stop processing if cancelled

            # Update progress
            progress = int((i / total_features) * 100)
            self.feedback.setProgress(progress)

            line_geometry = feature.geometry()
            segments = self.segment_line(line_geometry, segment_length)  # Custom segmentation logic

            # Process each segment
            for segment in segments:
                nb_segments += 1
                new_feature = QgsFeature(output_layer.fields())
                new_feature.setGeometry(segment)

                # Check for intersections with the reference layer
                intersects = self.buffer_and_check_intersections(segment, reference_layer, buffer_distance)
                new_feature.setAttribute("intersects", intersects)

                # Add the feature to the memory layer
                output_layer.dataProvider().addFeature(new_feature)

        QgsMessageLog.logMessage(
            f"Analysis complete. Total segments: {nb_segments}.",
            "GeoLinesQC",
            level=Qgis.Info
        )
        return output_layer  # Return the processed memory layer

    def cancel(self):
        """Cancel the task"""
        self.feedback.setCanceled(True)
        return super().cancel()

    def finished(self, result):
        """Handle the task completion"""
        if self.exception:
            self.iface.messageBar().pushMessage(
                "Error", f"Task failed: {str(self.exception)}", level=Qgis.Critical
            )
        else:
            self.iface.messageBar().pushMessage(
                "Success", "Task completed successfully.", level=Qgis.Success
            )
            # Optionally add the output layer to the map
            QgsProject.instance().addMapLayer(self.output_layer)
