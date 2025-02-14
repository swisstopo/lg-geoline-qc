import sys
import os
from qgis.core import Qgis

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
)
from qgis.core import QgsGeometry, QgsPointXY, QgsProject, QgsFeature, QgsVectorLayer, QgsField
from qgis.PyQt.QtCore import QVariant


from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsPoint,
    QgsProject,
    QgsFeature,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from qgis.core import QgsGeometry, QgsPoint, QgsProject, QgsFeature, QgsVectorLayer
from qgis.core import QgsSpatialIndex
from qgis.core import QgsProject, QgsFeature, QgsGeometry, QgsDistanceArea
from qgis.gui import QgsMessageBar
from qgis.utils import iface


class GeolinesQCPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&Distance Checker")

    def tr(self, message):
        return QCoreApplication.translate("DistanceChecker", message)

    def initGui(self):
        # Create action for the plugin
        self.action = QAction(
            QIcon(":/plugins/GeoLinesQC/icons8-line-chart-50.png"),
            "Distance Checker",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        # Remove plugin menu and icon
        self.iface.removePluginMenu("&Distance Checker", self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        # Create and show the dialog
        self.dialog = QDialog()
        self.dialog.setWindowTitle("Distance Checker")
        layout = QVBoxLayout()

        # Add input fields for layers and threshold distance
        self.layer1_combo = QComboBox()
        self.layer2_combo = QComboBox()
        self.threshold_input = QLineEdit()
        self.threshold_input.setPlaceholderText(
            "Optional: Enter threshold distance [m]"
        )

        layout.addWidget(QLabel("Layer to Check:"))
        layout.addWidget(self.layer1_combo)
        layout.addWidget(QLabel("Reference Layer:"))
        layout.addWidget(self.layer2_combo)
        layout.addWidget(QLabel("Threshold Distance:"))
        layout.addWidget(self.threshold_input)

        layers = QgsProject.instance().layerTreeRoot().children()
        self.layer1_combo.clear()
        self.layer1_combo.addItems([layer.name() for layer in layers])

        self.layer2_combo.clear()
        self.layer2_combo.addItems([layer.name() for layer in layers])

        # Add a button to run the analysis
        self.run_button = QPushButton("Run Analysis")
        self.run_button.clicked.connect(self.analyze_layers)
        layout.addWidget(self.run_button)

        self.dialog.setLayout(layout)
        self.dialog.exec_()

    def analyze_layers(self):
        # Get selected layers
        # TODO check validiy
        layer1_name = self.layer1_combo.currentText()
        layer2_name = self.layer2_combo.currentText()
        threshold = (
            float(self.threshold_input.text()) if self.threshold_input.text() else None
        )

        input_layer = QgsProject.instance().mapLayersByName(layer1_name)[0]
        reference_layer = QgsProject.instance().mapLayersByName(layer2_name)[0]


        # Create a new memory layer to store the segmented lines with intersection results
        output_layer = QgsVectorLayer(
            "LineString?crs=" + input_layer.crs().authid(),
            "segmented_lines_with_intersections",
            "memory",
        )
        output_layer.dataProvider().addAttributes(
            [
                QgsField("id", QVariant.Int),
                QgsField(
                    "intersects", QVariant.Bool
                ),  # Add a field to store intersection results
            ]
        )
        output_layer.updateFields()

        # Segment each feature in the input layer
        segment_length = 100.0  # Desired segment length
        buffer_distance = 500.0  # Buffer distance for intersection check
        for feature in input_layer.getFeatures():
            line_geometry = feature.geometry()
            segments = self.segment_line(line_geometry, segment_length)

            # Add each segment to the output layer with intersection results
            for segment in segments:
                new_feature = QgsFeature(output_layer.fields())
                new_feature.setGeometry(segment)

                # Check for intersections with the reference layer
                intersects = self.buffer_and_check_intersections(
                    segment, reference_layer, buffer_distance
                )
                new_feature.setAttribute("intersects", intersects)

                output_layer.dataProvider().addFeature(new_feature)

        # Add the output layer to the map
        QgsProject.instance().addMapLayer(output_layer)
        print("Segmentation and intersection check complete. Output layer added to the map.")
        self.iface.messageBar().pushMessage(
            "Info", "Segmentation and intersection check complete. Output layer added to the map.", level=Qgis.Info
        )

    def segment_line(self, line, segment_length):
        """
        Splits a line into segments of equal length using QGIS native functions.

        Args:
            line (QgsGeometry): The input line geometry.
            segment_length (float): The desired length of each segment.

        Returns:
            list: A list of QgsGeometry objects representing the segments.
        """
        try:
            # Extract vertices from the line
            vertices = line.asPolyline()  # Returns a list of QgsPointXY
            if len(vertices) < 2:
                print("Invalid line: Not enough vertices.")
                return [line]

            new_segments = []
            current_segment = [QgsPoint(vertices[0])]  # Convert QgsPointXY to QgsPoint
            accumulated_length = 0.0

            for i in range(1, len(vertices)):
                prev_point = QgsPoint(vertices[i - 1])  # Convert QgsPointXY to QgsPoint
                current_point = QgsPoint(vertices[i])  # Convert QgsPointXY to QgsPoint
                segment = QgsGeometry.fromPolyline([prev_point, current_point])
                segment_length_current = segment.length()

                while accumulated_length + segment_length_current >= segment_length:
                    # Calculate the remaining length to reach the segment_length
                    remaining_length = segment_length - accumulated_length
                    cut_point = segment.interpolate(remaining_length).asPoint()

                    # Add the cut point to the current segment
                    current_segment.append(
                        QgsPoint(cut_point)
                    )  # Convert QgsPointXY to QgsPoint
                    new_segments.append(QgsGeometry.fromPolyline(current_segment))

                    # Start a new segment from the cut point
                    current_segment = [
                        QgsPoint(cut_point)
                    ]  # Convert QgsPointXY to QgsPoint
                    accumulated_length = 0.0

                    # Update the segment with the remaining part after the cut
                    segment = QgsGeometry.fromPolyline([QgsPoint(cut_point), current_point])
                    segment_length_current = segment.length()

                # Add the current point to the segment
                current_segment.append(current_point)
                accumulated_length += segment_length_current

            # Add the last segment if it has more than one point
            if len(current_segment) > 1:
                new_segments.append(QgsGeometry.fromPolyline(current_segment))

            return new_segments

        except Exception as e:
            print(f"Error: {e}")
            self.iface.messageBar().pushMessage("Error", str(e), level=Qgis.Critical)
            return [line]

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
        self.iface.messageBar().pushMessage(
            "Info", "Starting analysis...", level=Qgis.Info
        )
        try:
            # Create a buffer around the segment
            segment_buffer = segment.buffer(
                buffer_distance, 5
            )  # 5 is the number of segments to approximate the buffer

            # Check for intersections with the reference layer
            for feature in reference_layer.getFeatures():
                reference_geometry = feature.geometry()
                if segment_buffer.intersects(reference_geometry):
                    return True  # Intersection found

            return False  # No intersection found

        except Exception as e:
            print(f"Error: {e}")
            self.iface.messageBar().pushMessage("Error", str(e), level=Qgis.Critical)
            return False

    # TODO: not used
    def check_distance(self, layer1, layer2, threshold=None):
        # Initialize distance calculator
        self.iface.messageBar().pushMessage(
            "Info", "Starting analysis...", level=Qgis.Info
        )
        try:
            d = QgsDistanceArea()
            d.setSourceCrs(layer1.crs(), QgsProject.instance().transformContext())

            """# Iterate through features in both layers
          for feat1 in layer1.getFeatures():
            geom1 = feat1.geometry()
            for feat2 in layer2.getFeatures():
                geom2 = feat2.geometry()
                distance = d.measureLine(geom1.centroid().asPoint(), geom2.centroid().asPoint())

                # Check if distance is within threshold
                if threshold and distance <= threshold:
                    print(f"Feature {feat1.id()} is within {threshold} units of Feature {feat2.id()}")"""
            self.iface.messageBar().pushMessage(
                "Analysis Complete", "Distance check finished", level=Qgis.Info
            )
        except Exception as e:
            self.iface.messageBar().pushMessage("Error", str(e), level=Qgis.Critical)
