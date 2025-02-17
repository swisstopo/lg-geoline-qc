# -*- coding: utf-8 -*-


import os

from qgis import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPoint,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

# from GeoLinesQC import resolve
# from GeoLinesQC.utils import geometry_to_vector_layer

DEFAULT_BUFFER = 500.0
DEFAULT_SEGMENT_LENGTH = 100.0

ADD_CLIPPED_LAYER_TO_MAP = False
DIALOG_WIDTH = 400


class GeolinesQCPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&GeoLines QC")
        self.predefined_geometries = {}

    def tr(self, message):
        return QCoreApplication.translate("GeoLinesQC", message)

    def initGui(self):
        # Create action for the plugin
        self.action = QAction(
            QIcon(":/plugins/GeoLinesQC/icons8-line-chart-50.png"),
            "GeoLines QC",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        # Remove plugin menu and icon
        self.iface.removePluginMenu("&GeoLines QC", self.action)
        self.iface.removeToolBarIcon(self.action)

    """def get_predefined_geometries(self):
        # Load the GPGK file
        gpkg_path = resolve("data/regions.gpkg")
        layername = "regions"

        if bool(self.predefined_geometries):
            return self.predefined_geometries

        try:
            # Check if the file exists
            if not os.path.exists(gpkg_path):
                raise FileNotFoundError(f"The file '{gpkg_path}' does not exist.")

            regions_layer = QgsVectorLayer(
                gpkg_path + "|layername=" + layername, "regions", "ogr"
            )

            # Check if the layer is valid
            if not regions_layer.isValid():
                raise ValueError(
                    f"Failed to load layer from '{gpkg_path}'. The file may be corrupt or unsupported."
                )

            # Check if the layer contains geometries
            if regions_layer.featureCount() == 0:
                raise ValueError(f"The layer '{layername}' contains no features.")

        except FileNotFoundError as e:
            self.iface.messageBar().pushMessage(
                "File Not Found", str(e), level=Qgis.Critical
            )

        except ValueError as e:
            self.iface.messageBar().pushMessage(
                "Layer Error", str(e), level=Qgis.Critical
            )
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Unexpected Error",
                f"An unexpected error occurred: {str(e)}",
                level=Qgis.Critical,
            )

        # Store geometries in a dictionary

        for feature in regions_layer.getFeatures():
            name = feature["name"]
            geometry = feature.geometry()
            self.predefined_geometries[name] = geometry

        return self.predefined_geometries"""

    """def get_selected_geometry(self):
        selected_name = self.geometry_combo.currentText()
        if selected_name != "None":
            return self.get_predefined_geometries()[selected_name]
        return None"""

    def run(self):
        # Create and show the dialog
        self.iface.messageBar().pushMessage(
            "Info",
            "Open dialog...",
            level=Qgis.Info,
        )
        self.dialog = QDialog()
        self.dialog.setWindowTitle("GeoLines QC")
        self.dialog.setFixedWidth(DIALOG_WIDTH)
        layout = QVBoxLayout()

        # Add input fields for layers and threshold distance
        self.layer1_combo = QComboBox()
        self.layer2_combo = QComboBox()
        self.threshold_input = QLineEdit()
        self.threshold_input.setPlaceholderText(
            f"Optional: buffer distance [m] (default: {DEFAULT_BUFFER})"
        )
        self.geometry_combo = QComboBox()

        layout.addWidget(QLabel("Layer to Check:"))
        layout.addWidget(self.layer1_combo)
        layout.addWidget(QLabel("Reference Layer:"))
        layout.addWidget(self.layer2_combo)
        layout.addWidget(QLabel("Buffer Distance:"))
        layout.addWidget(self.threshold_input)
        layout.addWidget(QLabel("Select Region:"))
        layout.addWidget(self.geometry_combo)

        layers = QgsProject.instance().layerTreeRoot().children()
        self.layer1_combo.clear()
        self.layer1_combo.addItems([layer.name() for layer in layers])

        self.layer2_combo.clear()
        self.layer2_combo.addItems([layer.name() for layer in layers])

        # Add a dropdown for predefined geometries
        self.geometry_combo.clear()
        self.geometry_combo.addItem("None")
        self.geometry_combo.addItems([layer.name() for layer in layers])

        # Add a button to run the analysis
        self.run_button = QPushButton("Run Analysis")
        self.run_button.clicked.connect(self.analyze_layers)
        layout.addWidget(self.run_button)

        self.dialog.setLayout(layout)
        self.dialog.exec_()

    def clip_layer_with_processing(self, layer, region_layer, layer_name):
        """
        Clips a layer using the QGIS processing tool.

        Args:
            layer (QgsVectorLayer): The layer to clip.
            region_layer (QgsVectorLayer): The region layer to clip with.
            layer_name (str): Name of the clipped layer.

        Returns:
            QgsVectorLayer: The clipped layer, or None if an error occurs.
        """
        try:
            # Run the clip algorithm
            result = processing.run(
                "qgis:clip",
                {
                    "INPUT": layer,
                    "OVERLAY": region_layer,
                    "OUTPUT": "memory:",
                },
            )

            # Get the clipped layer
            clipped_layer = result["OUTPUT"]
            clipped_layer.setName(layer_name)

            return clipped_layer

        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Error",
                f"Failed to clip layer: {str(e)}",
                level=Qgis.Critical,
            )
            return None

    def analyze_layers(self):
        # Get selected layers
        # TODO check validiy
        mask_layer_name_full = None
        layer1_name = self.layer1_combo.currentText()
        layer2_name = self.layer2_combo.currentText()
        mask_layer_name = self.geometry_combo.currentText()
        buffer_distance = (
            float(self.threshold_input.text())
            if self.threshold_input.text()
            else DEFAULT_BUFFER
        )

        self.iface.messageBar().pushMessage(
            "Info",
            "Loading data...",
            level=Qgis.Info,
        )

        input_layer_full = QgsProject.instance().mapLayersByName(layer1_name)[0]
        reference_layer_full = QgsProject.instance().mapLayersByName(layer2_name)[0]
        if mask_layer_name:
            mask_layer_name_full = QgsProject.instance().mapLayersByName(
                mask_layer_name
            )[0]

        # Get the selected region layer
        """region_geometry = (
            self.get_selected_geometry()
        )  # Assuming this returns a QgsVectorLayer"""

        if not mask_layer_name:
            self.iface.messageBar().pushMessage(
                "Info",
                "No region selected. Using the full dataset",
                level=Qgis.Info,
            )
            input_layer = input_layer_full
            reference_layer = reference_layer_full
        else:
            self.iface.messageBar().pushMessage(
                "Info",
                "Clipping data...",
                level=Qgis.Info,
            )
            # Convert the region geometry to a vector layer
            # region_layer = geometry_to_vector_layer(region_geometry, "Selected Region")
            region_layer = mask_layer_name_full
            # Clip layer1 to the selected region
            input_layer = self.clip_layer_with_processing(
                input_layer_full, region_layer, f"Clipped {layer1_name}"
            )
            if ADD_CLIPPED_LAYER_TO_MAP and input_layer:
                QgsProject.instance().addMapLayer(input_layer)

            # Clip layer2 to the selected region
            reference_layer = self.clip_layer_with_processing(
                reference_layer_full, region_layer, f"Clipped {layer2_name}"
            )
            if ADD_CLIPPED_LAYER_TO_MAP and reference_layer:
                QgsProject.instance().addMapLayer(reference_layer)

        # Create a new memory layer to store the segmented lines with intersection results
        output_layer = QgsVectorLayer(
            "LineString?crs=" + input_layer.crs().authid(),
            f"{layer1_name} — {layer2_name} {buffer_distance}",
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
        self.iface.messageBar().pushMessage(
            "Info",
            "Starting analysis...",
            level=Qgis.Info,
        )

        # Initialize progress dialog
        progress = QProgressDialog(
            "Processing features...",
            "Cancel",
            0,
            input_layer.featureCount(),
            self.iface.mainWindow(),
        )
        progress.setWindowTitle("Analyzing Layers")
        progress.setWindowModality(
            Qt.WindowModal
        )  # Make the dialog block the main window
        progress.setMinimumDuration(0)  # Show the dialog immediately

        # Segment each feature in the input layer
        # segment_length = 100.0  # Desired segment length
        # buffer_distance = 500.0  # Buffer distance for intersection check
        for i, feature in enumerate(input_layer.getFeatures()):
            # Update progress bar
            if i % 10 == 0:
                progress.setValue(i)
            if progress.wasCanceled():
                self.iface.messageBar().pushMessage(
                    "Warning",
                    "Operation canceled by user.",
                    level=Qgis.Warning,
                )
                break
            line_geometry = feature.geometry()
            segments = self.segment_line(line_geometry, DEFAULT_SEGMENT_LENGTH)

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

        self.iface.messageBar().pushMessage(
            "Info",
            "Segmentation and intersection check complete. Output layer added to the map.",
            level=Qgis.Info,
        )
        # Close the progress dialog
        progress.setValue(input_layer.featureCount())
        self.iface.messageBar().pushMessage(
            "Success",
            "Segmentation and intersection check complete. Output layer added to the map.",
            level=Qgis.Success,
        )
        self.dialog.close()

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
                    segment = QgsGeometry.fromPolyline(
                        [QgsPoint(cut_point), current_point]
                    )
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
            print(f"Error: {e}")
            self.iface.messageBar().pushMessage("Error", str(e), level=Qgis.Critical)
            return False
