# -*- coding: utf-8 -*-


import os
from datetime import datetime

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer
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

from GeoLinesQC.tasks import GeoLinesProcessingTask
from GeoLinesQC.utils import create_spatial_index

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

    """def extract_within_distance_with_processing(
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

        return clipped_layer"""

    '''def clip_layer_with_processing(self, layer, region_layer, layer_name):
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

        return clipped_layer'''

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
            """self.start_extraction_step(
                input_layer_full, reference_layer_full, buffer_distance, segment_length
            )"""
            self.start_single_task(
                input_layer_full, reference_layer_full, segment_length, buffer_distance
            )
        else:
            # Get mask layer
            region_layer = QgsProject.instance().mapLayersByName(mask_layer_name)[0]

            self.log_debug(
                f"Clipping data with {region_layer.name()}...", show_in_bar=False
            )

            # TODO reactivate
            # Start the clipping process
            """self.start_clipping_step(
                input_layer_full,
                reference_layer_full,
                region_layer,
                layer1_name,
                layer2_name,
                buffer_distance,
                segment_length,
            )"""

    # New single task

    def start_single_task(
        self, input_layer, reference_layer, segment_length, buffer_distance
    ):
        """Start the final analysis step in the background"""

        # Create the task
        task = GeoLinesProcessingTask(
            description="Process line features",
            input_layer=input_layer,
            reference_layer=reference_layer,
            buffer_distance=buffer_distance,
            split_length=segment_length,
            output_name=f"Result {input_layer.name()} - {reference_layer.name()}",
            output_field_name="has_nearby_features",
            run_distance_check=True,
            run_line_split=True,
        )

        # Connect signals
        task.taskCompleted.connect(lambda: on_task_completed(task))
        task.taskTerminated.connect(
            lambda: handle_task_error("GeoLines processing", task.exception)
        )

        # Create progress dialog
        progress = QProgressDialog(
            f"Processing geolines with buffer {buffer_distance}m...",
            "Cancel",
            0,
            100,
            self.iface.mainWindow(),
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.canceled.connect(task.cancel)

        # Setup progress updates
        timer = QTimer(self.iface.mainWindow())

        def update_progress():
            try:
                if task and task.feedback:
                    progress.setValue(int(task.feedback.progress()))
                    if task.feedback.isCanceled() or not task.isActive():
                        timer.stop()
            except RuntimeError:
                # The task has been deleted
                timer.stop()

        def handle_task_error(task_name, exception):
            timer.stop()  # Stop the progress timer

            if exception:
                self.iface.messageBar().pushCritical(
                    "Task Error",
                    f"The {task_name} task encountered an error: {exception}",
                )
            else:
                self.iface.messageBar().pushWarning(
                    "Task Cancelled", f"The {task_name} task was cancelled"
                )

        def on_task_completed(task):
            timer.stop()  # Stop the progress timer
            progress.close()

            if task.output_layer:
                # Add the layer to the map
                QgsProject.instance().addMapLayer(task.output_layer)
                # Load style and add to map
                self.add_styled_layer(task.output_layer, "has_nearby_features")
                QgsMessageLog.logMessage(
                    "Result layer + style added to the map",
                    "GeoLinesQC",
                    level=Qgis.Info,
                )
                # close dialog
                self.dialog.close()

                # Show a success message
                self.iface.messageBar().pushSuccess(
                    "GeoLines QC Processing",
                    f"Processing completed successfully. {task.result_message}",
                )

        timer.timeout.connect(update_progress)
        timer.start(100)

        # Start task

        QgsApplication.taskManager().addTask(task)
        progress.show()

    # ---

    '''def start_clipping_step(
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
        progress.setWindowTitle("Extracting")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # Create extraction task
        extract_task = ExtractionTask(
            f"Extract features within {buffer_distance} meters",
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
            try:
                if extract_task and extract_task.feedback:
                    progress.setValue(int(extract_task.feedback.progress()))
                    if (
                        extract_task.feedback.isCanceled()
                        or not extract_task.isActive()
                    ):
                        timer.stop()
            except RuntimeError:
                # The task has been deleted
                timer.stop()

        timer.timeout.connect(update_progress)
        timer.start(100)

        # Start task
        QgsApplication.taskManager().addTask(extract_task)
        progress.show()'''

    '''def start_final_step(
        self, input_layer, reference_layer, segment_length, buffer_distance
    ):
        """Start the final analysis step in the background"""

        # Create the task
        task = GeoLinesProcessingTask(
            description="Process line features",
            input_layer=input_layer,
            reference_layer=reference_layer,
            buffer_distance=buffer_distance,
            split_length=segment_length,
            output_name=None,  # "C:/path/to/output/processed_lines.gpkg",
            output_field_name="has_nearby_features",
            run_distance_check=True,
            run_line_split=True,
        )

        # Connect signals
        task.taskCompleted.connect(lambda: on_task_completed(task))
        task.taskTerminated.connect(
            lambda: self.handle_task_error("GeoLines processing", task.exception)
        )

        # Create progress dialog
        progress = QProgressDialog(
            "Processing lines...", "Cancel", 0, 100, self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.canceled.connect(task.cancel)

        # Setup progress updates
        timer = QTimer(self.iface.mainWindow())

        def update_progress():
            try:
                if task and task.feedback:
                    progress.setValue(int(task.feedback.progress()))
                    if task.feedback.isCanceled() or not task.isActive():
                        timer.stop()
            except RuntimeError:
                # The task has been deleted
                timer.stop()

        def on_task_completed(task):
            timer.stop()  # Stop the progress timer
            progress.close()

            if task.output_layer:
                # Add the layer to the map
                QgsProject.instance().addMapLayer(task.output_layer)
                # Load style and add to map
                self.add_styled_layer(task.output_layer, "has_nearby_features")
                QgsMessageLog.logMessage(
                    "Result layer + style added to the map",
                    "GeoLinesQC",
                    level=Qgis.Info,
                )
                # close dialog
                self.dialog.close()

                # Show a success message
                self.iface.messageBar().pushSuccess(
                    "GeoLines QC Processing",
                    f"Processing completed successfully. {task.result_message}",
                )

        timer.timeout.connect(update_progress)
        timer.start(100)

        # Start task

        QgsApplication.taskManager().addTask(task)
        progress.show()'''

    """def handle_task_error(self, task_name, exception):
        timer.stop()  # Stop the progress timer

        if exception:
            self.iface.messageBar().pushCritical(
                "Task Error",
                f"The {task_name} task encountered an error: {exception}",
            )
        else:
            self.iface.messageBar().pushWarning(
                "Task Cancelled", f"The {task_name} task was cancelled"
            )"""

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
