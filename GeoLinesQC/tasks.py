import os
from datetime import datetime

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsPoint,
    QgsProcessingFeedback,
    QgsProject,
    QgsSpatialIndex,
    QgsTask,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from GeoLinesQC.errors import ClipError


PROCESS_SEGMENTS = False  # Check if buffered segments intersect features


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
                "OUTPUT": f"memory:{self.output_name}",
            }

            # Run the clip algorithm
            result = processing.run("native:clip", clip_params, feedback=self.feedback)
            self.output_layer = result["OUTPUT"]

            # Check if any features were clipped
            if self.output_layer.featureCount() == 0:
                self.exception = ClipError(
                    f"No features found in the clipped layer: {self.output_name}"
                )
                return False

            return True
        except Exception as e:
            self.exception = e
            return False

    def cancel(self):
        """Cancel the task"""
        if self.feedback:
            self.feedback.isCanceled(True)
        return super().cancel()


class ExtractionTask(QgsTask):
    """Task for extracting features within a distance"""

    def __init__(
        self, description, input_layer, reference_layer, distance, output_name
    ):
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
                "OUTPUT": f"memory:{self.output_name}",
            }

            # Run the extraction algorithm
            result = processing.run(
                "native:extractbylocation",
                extract_within_params,
                feedback=self.feedback,
            )
            self.output_layer = result["OUTPUT"]

            # Check if any features were extracted
            if self.output_layer.featureCount() == 0:
                self.exception = ClipError(
                    f"No features found within distance in layer: {self.output_name}"
                )
                return False

            return True
        except Exception as e:
            self.exception = e
            return False

    # TODO: check
    def cancel(self):
        """Cancel the task"""
        if self.feedback:
            self.feedback.cancel()
        QgsMessageLog.logMessage(
            "ExtractionTask was cancelled: {self.description()}",
            "GeoLinesQC",
            Qgis.Info,
        )
        return super().cancel()

    def finished(self, result):
        """Handle the task completion"""
        if self.exception:
            QgsMessageLog.logMessage(
                f"Task failed: {str(self.exception)}", "GeoLinesQC", level=Qgis.Critical
            )

        else:
            QgsMessageLog.logMessage(
                "ExtractionTask completed successfully.",
                "GeoLinesQC",
                level=Qgis.Success,
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

    def __init__(
        self, description, input_layer, reference_layer, segment_length, buffer_distance
    ):
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
                self.buffer_distance,
            )
            return True  # Task completed successfully
        except Exception as e:
            self.exception = e
            QgsMessageLog.logMessage(
                f"Error in analysis task: {str(e)}", "GeoLinesQC", level=Qgis.Critical
            )
            return False  # Task failed

    def segment_line(self, line, segment_length):
        """
        Splits a line into segments of equal length using QGIS native functions.
        Handles both single LineString and MultiLineString geometries.

        Args:
            line (QgsGeometry): The input line geometry (can be LineString or MultiLineString).
            segment_length (float): The desired length of each segment.
        Returns:
            list: A list of QgsGeometry objects representing the segments.
        """
        try:
            new_segments = []

            # Check geometry type
            geom_type = line.wkbType()
            # self.log_debug(
            #    f"Processing geometry type: {QgsWkbTypes.displayString(geom_type)}"
            # )

            # Handle MultiLineString
            if QgsWkbTypes.isMultiType(geom_type):
                # self.log_debug("Processing MultiLineString geometry")
                for part in line.asGeometryCollection():
                    # self.log_debug(f"Processing part with length: {part.length()}")
                    segments = self.segment_single_line(part, segment_length)
                    new_segments.extend(segments)
            # Handle single LineString
            else:
                # self.log_debug("Processing single LineString geometry")
                new_segments = self.segment_single_line(line, segment_length)

            summary = f"\nTotal segments created: {len(new_segments)}"
            for idx, seg in enumerate(new_segments):
                summary += f"\nSegment {idx} length: {seg.length()}"
            # self.log_debug(summary)

            return new_segments

        except Exception as e:
            import traceback

            error_msg = f"Error: {str(e)}\nTraceback:\n{traceback.format_exc()}"
            self.log_debug(error_msg, show_in_bar=True)
            return [line]

    def segment_single_line(self, line, segment_length):
        """
        Splits a single LineString geometry into segments.

        Args:
            line (QgsGeometry): The input LineString geometry.
            segment_length (float): The desired length of each segment.
        Returns:
            list: A list of QgsGeometry objects representing the segments.
        """
        try:
            # Debug: Log input parameters
            # self.log_debug(f"Input line length: {line.length()}")
            # self.log_debug(f"Requested segment length: {segment_length}")

            # Extract vertices from the line
            vertices = line.asPolyline()
            # self.log_debug(f"Number of vertices in input line: {len(vertices)}")

            if len(vertices) < 2:
                # msg = "Invalid line: Not enough vertices."
                # self.log_debug(msg, show_in_bar=True)
                return [line]

            new_segments = []
            current_segment = [QgsPoint(vertices[0])]
            accumulated_length = 0.0

            for i in range(1, len(vertices)):
                prev_point = QgsPoint(vertices[i - 1])
                current_point = QgsPoint(vertices[i])
                segment = QgsGeometry.fromPolyline([prev_point, current_point])
                segment_length_current = segment.length()

                # self.log_debug(f"Processing vertex {i}:")
                # self.log_debug(f"Current segment length: {segment_length_current}")
                # self.log_debug(
                #     f"Accumulated length before processing: {accumulated_length}"
                # )

                while accumulated_length + segment_length_current >= segment_length:
                    remaining_length = segment_length - accumulated_length
                    # self.log_debug(
                    #    f"Splitting segment - Remaining length: {remaining_length}"
                    # )

                    if remaining_length <= 0:
                        # self.log_debug(
                        #    "Warning: Remaining length is zero or negative",
                        #    show_in_bar=True,
                        # )
                        break

                    if remaining_length >= segment_length_current:
                        # self.log_debug(
                        #    "Warning: Remaining length exceeds current segment length",
                        #    show_in_bar=True,
                        # )
                        break

                    cut_point = segment.interpolate(remaining_length).asPoint()
                    # self.log_debug(
                    #    f"Cut point created at: ({cut_point.x()}, {cut_point.y()})"
                    # )

                    current_segment.append(QgsPoint(cut_point))
                    new_segment = QgsGeometry.fromPolyline(current_segment)
                    # self.log_debug(f"New segment length: {new_segment.length()}")
                    new_segments.append(new_segment)

                    current_segment = [QgsPoint(cut_point)]
                    accumulated_length = 0.0

                    segment = QgsGeometry.fromPolyline(
                        [QgsPoint(cut_point), current_point]
                    )
                    segment_length_current = segment.length()
                    # self.log_debug(
                    #    f"Remaining segment length after cut: {segment_length_current}"
                    # )

                current_segment.append(current_point)
                accumulated_length += segment_length_current
                # self.log_debug(
                #    f"Accumulated length after processing: {accumulated_length}"
                # )

            # Add the last segment if it has more than one point
            if len(current_segment) > 1:
                final_segment = QgsGeometry.fromPolyline(current_segment)
                # self.log_debug(
                #    f"Adding final segment with length: {final_segment.length()}"
                # )
                new_segments.append(final_segment)

            return new_segments

        except Exception as e:
            import traceback

            error_msg = f"Error in segment_single_line: {str(e)}\nTraceback:\n{traceback.format_exc()}"
            # self.log_debug(error_msg, show_in_bar=True)
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", level=Qgis.Error)
            return [line]

    def segment_and_check_intersections_bg(
        self, input_layer, reference_layer, segment_length, buffer_distance
    ):
        """
        Background-friendly implementation of segment_and_check_intersections.
        Supports progress reporting and cancellation.
        """

        self.log_debug("Starting background segment and check")
        # Create a new memory layer to store the results
        output_layer = QgsVectorLayer(
            f"LineString?crs={input_layer.crs().authid()}",
            f"Segmented {input_layer.name()}",
            "memory",
        )
        output_layer.dataProvider().addAttributes(
            [
                QgsField("id", QVariant.Int),
                QgsField(
                    "intersects", QVariant.Bool
                ),  # Field to store intersection results
            ]
        )
        output_layer.updateFields()

        total_features = input_layer.featureCount()
        nb_segments = 0  # Counter for segments added

        self.log_debug(f"Total features: {total_features}")

        # Iterate through features in the input layer
        for i, feature in enumerate(input_layer.getFeatures()):
            # Check if the task has been cancelled
            if self.feedback.isCanceled():
                return None  # Stop processing if cancelled

            # Update progress
            progress = int((i / total_features) * 100)
            self.feedback.setProgress(progress)

            line_geometry = feature.geometry()
            segments = self.segment_line(
                line_geometry, segment_length
            )  # Custom segmentation logic
            msg = f"{i}/{total_features} Feature with {len(segments)} [{progress:.0%}]"
            self.log_debug(msg)
            QgsMessageLog.logMessage(msg, "GeoLinesQC", level=Qgis.Info)
            # Process each segment
            for segment in segments:
                nb_segments += 1
                new_feature = QgsFeature(output_layer.fields())
                new_feature.setGeometry(segment)

                if PROCESS_SEGMENTS:
                    # Check for intersections with the reference layer
                    intersects = self.buffer_and_check_intersections(
                        segment, reference_layer, buffer_distance
                    )
                    new_feature.setAttribute("intersects", intersects)

                # Add the feature to the memory layer
                output_layer.dataProvider().addFeature(new_feature)

        QgsMessageLog.logMessage(
            f"Analysis complete. Total segments: {nb_segments}.",
            "GeoLinesQC",
            level=Qgis.Info,
        )
        return output_layer  # Return the processed memory layer

    def buffer_and_check_intersections(self, segment, reference_layer, buffer_distance):
        """
        Buffers a segment and checks if it intersects with any features in a reference layer.

        Args:
            segment (QgsGeometry): The segment to buffer.
            reference_layer (QgsVectorLayer): The reference layer to check for intersections.
            buffer_distance (float): The buffer distance.

        Returns:
            bool: True if the buffer intersects any features in the reference layer, False otherwise.
        """

        try:
            # Create a buffer around the segment
            segment_buffer = segment.buffer(
                buffer_distance, 5
            )  # 5 is the number of segments to approximate the buffer

            # Create a spatial index for the reference layer
            spatial_index = QgsSpatialIndex(reference_layer.getFeatures())

            # Find features in the reference layer that intersect with the buffer's bounding box
            candidate_ids = spatial_index.intersects(segment_buffer.boundingBox())

            # Check for actual intersections with the candidate features
            for feature_id in candidate_ids:
                feature = reference_layer.getFeature(feature_id)
                reference_geometry = feature.geometry()
                if segment_buffer.intersects(reference_geometry):
                    return True  # Intersection found

            return False  # No intersection found

        except Exception as e:
            self.log_debug(f"Error in buffer and check: {e}")
            QgsMessageLog.logMessage(
                f"Error in buffer_and_check_intersections: {e}.",
                "GeoLinesQC",
                level=Qgis.Critical,
            )
            return False

    def log_debug(self, message):
        """Unified logging function that writes to both log file and QGIS log"""
        # Log to QGIS Message Log
        QgsMessageLog.logMessage(message, "GeoLinesQC", level=Qgis.Info)

        # Log to file

        # Get the path to the QGIS user profile directory
        profile_path = QgsApplication.qgisSettingsDirPath()

        # Construct the path to your plugin's logs directory
        log_dir = os.path.join(profile_path, "python", "plugins", "GeoLinesQC", "logs")

        # log_dir = os.path.join(os.path.dirname(__file__), "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = os.path.join(log_dir, "debug.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(log_file, "a") as f:
            f.write(f"{timestamp}: {message}\n")

    def cancel(self):
        """Cancel the task"""
        # TODO
        self.feedback.isCanceled()
        return super().cancel()

    def finished(self, result):
        """Handle the task completion"""
        if self.exception:
            QgsMessageLog.logMessage(
                f"Task failed: {str(self.exception)}", "GeoLinesQC", level=Qgis.Critical
            )

        else:
            QgsMessageLog.logMessage(
                "SegmentAndCheckTask completed successfully.",
                "GeoLinesQC",
                level=Qgis.Success,
            )
            # Optionally add the output layer to the map
            QgsProject.instance().addMapLayer(self.output_layer)
