# -*- coding: utf-8 -*-


import os
from datetime import datetime

from qgis import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsPoint,
    QgsProcessingFeatureSourceDefinition,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QCoreApplication, Qt, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import (
    QgsTask,
    QgsApplication,
    QgsProcessingFeedback,
    QgsMessageLog,
    Qgis,
    QgsProject,
)
from qgis.PyQt.QtWidgets import QProgressDialog
from qgis.PyQt.QtCore import Qt, QTimer

from GeoLinesQC.utils import create_spatial_index
from GeoLinesQC.tasks import SegmentAndCheckTask, ExtractionTask, ClipLayerTask
from GeoLinesQC.errors import ClipError

DEFAULT_BUFFER = 500.0
DEFAULT_SEGMENT_LENGTH = 200.0

ADD_CLIPPED_LAYER_TO_MAP = True
DIALOG_WIDTH = 400

# Enable high DPI scaling
if hasattr(QApplication, "setAttribute"):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# Set the environment variable for auto screen scaling
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


class GeolinesQCPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&GeoLines QC")
        self.predefined_geometries = {}
        # Get the path to your plugin directory
        self.styles_dir = os.path.join(self.plugin_dir, "styles")

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
        self.segment_length_input = QLineEdit()
        self.segment_length_input.setPlaceholderText(
            f"Optional: segment length [m] (default: {DEFAULT_SEGMENT_LENGTH})"
        )
        self.geometry_combo = QComboBox()

        layout.addWidget(QLabel("Layer to Check:"))
        layout.addWidget(self.layer1_combo)
        layout.addWidget(QLabel("Reference Layer:"))
        layout.addWidget(self.layer2_combo)
        layout.addWidget(QLabel("Buffer Distance:"))
        layout.addWidget(self.threshold_input)
        layout.addWidget(QLabel("Segment Length:"))
        layout.addWidget(self.segment_length_input)
        layout.addWidget(QLabel("Region layer:"))
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

    def extract_within_distance_with_processing(
        self, layer_to_check, ref_layer, distance, layer_name
    ):
        # Create the processing parameters
        # We want to filter out features of the reference layer which are too far from the layer to check (inverted logic)
        extract_within_params = {
            "INPUT": ref_layer,  # Layer to extract features from
            "PREDICATE": [6],  # Spatial predicate (6 = Within Distance)
            "INTERSECT": layer_to_check,  # Reference layer for distance comparison
            "DISTANCE": distance,  # The distance threshold (in layer's CRS units)
            "OUTPUT": "memory:" + layer_name,  # Output layer (temporary)
        }

        # Run the clip processing algorithm
        result = processing.run("native:extractbylocation", extract_within_params)

        # Get the output layer
        clipped_layer = result["OUTPUT"]

        # If the result is a string (file path) load it as a layer
        if isinstance(clipped_layer, str):
            clipped_layer = QgsVectorLayer(clipped_layer, layer_name, "ogr")

        # Check if the layer is valid and has features
        if not clipped_layer.isValid():
            raise ClipError("Failed to create valid clipped layer")

        if clipped_layer.featureCount() == 0:
            raise ClipError(
                "Clipping resulted in empty layer - no overlapping features found"
            )

        return clipped_layer

    def clip_layer_with_processing(self, layer, region_layer, layer_name):
        """
        Clips a layer using selected features from region_layer or the whole layer if nothing is selected.

        Args:
            layer: Input layer to be clipped
            region_layer: Layer containing the clip features
            layer_name: Name for the output layer

        Returns:
            QgsVectorLayer: The clipped layer

        Raises:
            ClipError: If the resulting layer is empty or invalid
        """
        # Create the processing parameters
        params = {"INPUT": layer, "OUTPUT": "memory:" + layer_name}

        # Check if there are selected features
        if region_layer.selectedFeatureCount() > 0:
            # Use only selected features for clipping
            self.log_debug(
                f"Using {region_layer.selectedFeatureCount()} selected features for clipping"
            )
            params["OVERLAY"] = QgsProcessingFeatureSourceDefinition(
                region_layer.id(), selectedFeaturesOnly=True
            )
        else:
            # Use all features if nothing is selected
            self.log_debug("No features selected, using entire overlay layer")
            params["OVERLAY"] = region_layer

        # Run the clip processing algorithm
        result = processing.run("native:clip", params)

        # Get the output layer
        clipped_layer = result["OUTPUT"]

        # If the result is a string (file path) load it as a layer
        if isinstance(clipped_layer, str):
            clipped_layer = QgsVectorLayer(clipped_layer, layer_name, "ogr")

        # Check if the layer is valid and has features
        if not clipped_layer.isValid():
            raise ClipError("Failed to create valid clipped layer")

        if clipped_layer.featureCount() == 0:
            raise ClipError(
                "Clipping resulted in empty layer - no overlapping features found"
            )

        return clipped_layer

    def analyze_layers(self):
        """Main analysis function that chains processing steps together using background tasks"""
        # Clear logs
        QgsMessageLog.logMessage(
            "---- Starting a new operation ----", "GeoLinesQC", level=Qgis.Info
        )

        # Get selected layers
        layer1_name = self.layer1_combo.currentText()
        layer2_name = self.layer2_combo.currentText()
        mask_layer_name = self.geometry_combo.currentText()

        # Get parameters
        buffer_distance = (
            float(self.threshold_input.text())
            if self.threshold_input.text()
            else DEFAULT_BUFFER
        )
        segment_length = (
            float(self.segment_length_input.text())
            if self.segment_length_input.text()
            else DEFAULT_SEGMENT_LENGTH
        )

        # Show initial message
        self.iface.messageBar().pushMessage("Info", "Loading data...", level=Qgis.Info)
        QgsMessageLog.logMessage("Loading data...", "GeoLinesQC", level=Qgis.Info)
        self.log_debug("Loading data...", show_in_bar=False)

        # Get layer objects
        input_layer_full = QgsProject.instance().mapLayersByName(layer1_name)[0]
        reference_layer_full = QgsProject.instance().mapLayersByName(layer2_name)[0]

        # Create spatial indices
        create_spatial_index(input_layer_full)
        create_spatial_index(reference_layer_full)

        # Check if mask layer is selected
        if mask_layer_name == "None":
            self.iface.messageBar().pushMessage(
                "Info", "No region selected. Using the full dataset", level=Qgis.Info
            )
            # Skip clipping and go directly to extraction
            self.start_extraction_step(
                input_layer_full, reference_layer_full, buffer_distance, segment_length
            )
        else:
            # Get mask layer
            region_layer = QgsProject.instance().mapLayersByName(mask_layer_name)[0]
            self.iface.messageBar().pushMessage(
                "Info", "Clipping data...", level=Qgis.Info
            )
            self.log_debug("Clipping data...", show_in_bar=False)

            # Start the clipping process
            self.start_clipping_step(
                input_layer_full,
                reference_layer_full,
                region_layer,
                layer1_name,
                layer2_name,
                buffer_distance,
                segment_length,
            )

    def start_clipping_step(
        self,
        input_layer_full,
        reference_layer_full,
        region_layer,
        layer1_name,
        layer2_name,
        buffer_distance,
        segment_length,
    ):
        """Start the clipping process in the background"""
        # Create task for clipping input layer
        clip_task1 = ClipLayerTask(
            "Clip input layer", input_layer_full, region_layer, f"Clipped {layer1_name}"
        )

        # Function to handle completion of first clip task
        def on_clip1_complete(success):
            if success:
                input_layer = clip_task1.output_layer
                QgsMessageLog.logMessage(
                    f"Input layer clipped successfully, features: {input_layer.featureCount()}",
                    "GeoLinesQC",
                )

                # Add to map if configured
                if ADD_CLIPPED_LAYER_TO_MAP and input_layer:
                    QgsProject.instance().addMapLayer(input_layer)
                    create_spatial_index(input_layer)

                # Start clipping reference layer
                self.log_debug("Clipping reference data...", show_in_bar=False)
                clip_task2 = ClipLayerTask(
                    "Clip reference layer",
                    reference_layer_full,
                    region_layer,
                    f"{layer2_name} clipped",
                )

                # Function to handle completion of second clip task
                def on_clip2_complete(success):
                    if success:
                        reference_layer = clip_task2.output_layer
                        QgsMessageLog.logMessage(
                            f"Reference layer clipped successfully, features: {reference_layer.featureCount()}",
                            "GeoLinesQC",
                        )

                        # Add to map if configured
                        if ADD_CLIPPED_LAYER_TO_MAP and reference_layer:
                            QgsProject.instance().addMapLayer(reference_layer)
                            create_spatial_index(reference_layer)

                        # Start extraction step
                        self.start_extraction_step(
                            input_layer,
                            reference_layer,
                            buffer_distance,
                            segment_length,
                        )
                    else:
                        self.iface.messageBar().pushMessage(
                            "Error",
                            f"Failed to clip reference layer: {clip_task2.exception}",
                            level=Qgis.Critical,
                        )

                # Connect signals and start second clip task
                clip_task2.taskCompleted.connect(on_clip2_complete)
                clip_task2.taskTerminated.connect(
                    lambda: self.handle_task_error(
                        "Clip reference layer", clip_task2.exception
                    )
                )
                QgsApplication.taskManager().addTask(clip_task2)
            else:
                self.iface.messageBar().pushMessage(
                    "Error",
                    f"Failed to clip input layer: {clip_task1.exception}",
                    level=Qgis.Critical,
                )

        # Connect signals and start first clip task
        clip_task1.taskCompleted.connect(on_clip1_complete)
        clip_task1.taskTerminated.connect(
            lambda: self.handle_task_error("Clip input layer", clip_task1.exception)
        )
        QgsApplication.taskManager().addTask(clip_task1)

    def start_extraction_step(
        self, input_layer, reference_layer, buffer_distance, segment_length
    ):
        """Start the extraction process in the background"""
        self.log_debug(
            f"Selecting reference data within {buffer_distance}...", show_in_bar=False
        )

        # Create progress dialog
        progress = QProgressDialog(
            "Extracting features within distance...",
            "Cancel",
            0,
            100,
            self.iface.mainWindow(),
        )
        progress.setWindowTitle("Processing")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # Create extraction task
        extract_task = ExtractionTask(
            "Extract features within distance",
            reference_layer,
            input_layer,
            buffer_distance * 1.05,
            f"{reference_layer.name()} extracted",
        )

        # Function to handle completion of extraction task
        def on_extraction_complete(success):
            progress.close()

            if success:
                reference_layer_extracted = extract_task.output_layer
                QgsMessageLog.logMessage(
                    f"Reference layer extracted successfully, features: {reference_layer_extracted.featureCount()}",
                    "GeoLinesQC",
                )

                # Add to map if configured
                if ADD_CLIPPED_LAYER_TO_MAP and reference_layer_extracted:
                    QgsProject.instance().addMapLayer(reference_layer_extracted)
                    create_spatial_index(reference_layer_extracted)

                # Start final step
                self.start_final_step(
                    input_layer,
                    reference_layer_extracted,
                    segment_length,
                    buffer_distance,
                )
            else:
                self.iface.messageBar().pushMessage(
                    "Error",
                    f"Failed to extract reference features: {extract_task.exception}",
                    level=Qgis.Critical,
                )

        # Connect signals
        # extract_task.taskCompleted.connect(on_extraction_complete)
        # TODO:
        extract_task.taskCompleted.connect(
            lambda: on_extraction_complete(True)
        )  # Always assume success
        extract_task.taskTerminated.connect(
            lambda: self.handle_task_error("Extract features", extract_task.exception)
        )
        progress.canceled.connect(extract_task.cancel)

        # Setup progress updates
        timer = QTimer(self.iface.mainWindow())

        def update_progress():
            if extract_task.feedback:
                progress.setValue(int(extract_task.feedback.progress()))
                if extract_task.feedback.isCanceled() or not extract_task.isActive():
                    timer.stop()

        timer.timeout.connect(update_progress)
        timer.start(100)

        # Start task
        QgsApplication.taskManager().addTask(extract_task)
        progress.show()

    def start_final_step(
        self, input_layer, reference_layer, segment_length, buffer_distance
    ):
        """Start the final analysis step in the background"""
        self.iface.messageBar().pushMessage(
            "Info", "Performing final analysis...", level=Qgis.Info
        )

        # Create final analysis task
        final_task = SegmentAndCheckTask(
            "Segment and check intersections",
            input_layer,
            reference_layer,
            segment_length,
            buffer_distance,
        )

        # Progress dialog
        progress = QProgressDialog(
            "Analyzing intersections...", "Cancel", 0, 100, self.iface.mainWindow()
        )
        progress.setWindowTitle("Processing")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # Function to handle completion
        def on_final_complete(success):
            progress.close()

            if success:
                result_layer = final_task.output_layer
                QgsMessageLog.logMessage("Final analysis complete", "GeoLinesQC")

                # Add result to map
                if result_layer:
                    QgsProject.instance().addMapLayer(result_layer)
                    # Load style and add to map
                    self.add_styled_layer(result_layer, "intersects")
                    # close dialog
                    self.dialog.close()

                # Show completion message
                self.iface.messageBar().pushMessage(
                    "Success", "Final analysis complete", level=Qgis.Success
                )
            else:
                self.iface.messageBar().pushMessage(
                    "Error",
                    f"Final analysis failed: {final_task.exception}",
                    level=Qgis.Critical,
                )

        # Connect signals
        # final_task.taskCompleted.connect(on_final_complete)
        # TODO
        final_task.taskCompleted.connect(
            lambda: on_final_complete(True)
        )  # Always assume success
        final_task.taskTerminated.connect(
            lambda: self.handle_task_error("Final analysis", final_task.exception)
        )

        progress.canceled.connect(final_task.cancel)

        # Setup progress updates
        timer = QTimer(self.iface.mainWindow())

        def update_progress():
            if not final_task or final_task.isCanceled():
                if final_task.feedback:
                    # TODO reactivate
                    # progress.setValue(int(final_task.feedback.progress()))
                    if final_task.feedback.isCanceled() or not final_task.isActive():
                        timer.stop()

        # timer.timeout.connect(update_progress)
        timer.start(100)

        # Start task
        QgsApplication.taskManager().addTask(final_task)
        progress.show()

    def handle_task_error(self, task_name, exception):
        """Handle errors from tasks"""
        error_msg = str(exception) if exception else "Unknown error"
        QgsMessageLog.logMessage(
            f"Error in {task_name}: {error_msg}", "GeoLinesQC", level=Qgis.Critical
        )
        self.iface.messageBar().pushMessage(
            "Error", f"{task_name} failed: {error_msg}", level=Qgis.Critical
        )

    # TODO: remove
    '''def segment_and_check_intersections(
        self,
        input_layer,
        reference_layer,
        segment_length: float,
        buffer_distance: float,
    ):
        """
        Segments features in the input layer, checks for intersections with the reference layer,
        and creates an output memory layer with the results.

        Parameters:
        - input_layer: QgsVectorLayer
            The input layer containing the features to segment.
        - reference_layer: QgsVectorLayer
            The layer against which intersections are checked.
        - segment_length: float
            The length of each segment to create from the input layer's features.
        - buffer_distance: float
            The buffer distance used to check for intersections.
        """
        # Create a new memory layer to store the segmented lines with intersection results
        self.log_debug("Creating ouput memory layer...", show_in_bar=False)
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
        QgsMessageLog.logMessage(
            "Starting analysis...",
            "GeoLinesQC",
            level=Qgis.Info,
        )
        self.log_debug("Starting analysis...", show_in_bar=False)

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

        QgsMessageLog.logMessage(
            f"Buffer distance: {buffer_distance}, segment length={segment_length}",
            "GeoLinesQC",
            level=Qgis.Info,
        )
        nb_segments = 0

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
            segments = self.segment_line(line_geometry, segment_length)
            summary = f"Feature {i} has {len(segments)} segments"
            self.log_debug(summary)

            # Add each segment to the output layer with intersection results
            for segment in segments:
                nb_segments += 1
                new_feature = QgsFeature(output_layer.fields())
                new_feature.setGeometry(segment)

                # Check for intersections with the reference layer
                intersects = self.buffer_and_check_intersections(
                    segment, reference_layer, buffer_distance
                )
                new_feature.setAttribute("intersects", intersects)

                output_layer.dataProvider().addFeature(new_feature)

  
        # Close the progress dialog
        progress.setValue(input_layer.featureCount())
        self.iface.messageBar().pushMessage(
            "Success",
            f"Segmentation and intersection check complete (n={nb_segments}. Output layer added to the map.",
            level=Qgis.Success,
        )
        # Load style and add to map
        self.add_styled_layer(output_layer, "intersects")

        self.dialog.close()'''

    def add_styled_layer(self, layer, style_name):
        """
        Add a layer to the map with a predefined style

        Args:
            layer: QgsVectorLayer to add
            style_name: Name of the style file (without .qml extension)
        """
        # Construct path to style file
        style_path = os.path.join(self.styles_dir, f"{style_name}.qml")

        if not os.path.exists(style_path):
            self.iface.messageBar().pushMessage(
                "Style Error", f"Style file not found: {style_path}", level=Qgis.Warning
            )
            QgsProject.instance().addMapLayer(layer)
            return

        # Load the style
        success = layer.loadNamedStyle(style_path)
        if not success[1]:
            self.iface.messageBar().pushMessage(
                "Style Error", f"Failed to load style: {success[0]}", level=Qgis.Warning
            )

        # Add layer to the map
        QgsProject.instance().addMapLayer(layer)

    def log_debug(self, message, show_in_bar=False):
        """Unified logging function that writes to both log file and QGIS log"""
        # Log to QGIS Message Log
        QgsMessageLog.logMessage(message, "GeoLinesQC", level=Qgis.Info)

        # Optionally show in message bar
        if show_in_bar:
            self.iface.messageBar().pushMessage("Debug", message, level=Qgis.Info)

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

    # TODO: moved to task
    '''def segment_line(self, line, segment_length):
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
            return [line]'''

    # TODO: moved to task
    '''def segment_single_line(self, line, segment_length):
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
            self.log_debug(error_msg, show_in_bar=True)
            return [line]'''

    # TODO: moved to task
    '''def buffer_and_check_intersections(self, segment, reference_layer, buffer_distance):
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
            return False'''
