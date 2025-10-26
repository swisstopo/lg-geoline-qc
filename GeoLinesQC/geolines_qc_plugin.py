# -*- coding: utf-8 -*-

import os
import warnings

from qgis import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    QgsProcessingFeatureSourceDefinition,
    QgsTask,
    QgsApplication,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QAction,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
    QProgressDialog,
    QCheckBox,
)
from qgis.PyQt.QtCore import QVariant


DEFAULT_BUFFER = 500.0
DIALOG_WIDTH = 400

# Enable high DPI scaling
if hasattr(QApplication, "setAttribute"):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# Set the environment variable for auto screen scaling
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


def create_intersects_field(name="intersects"):
    """
    Create the intersects Boolean field - compatible across QGIS versions

    Supports:
    - QGIS 3.34 (GitHub Actions CI)
    - QGIS 3.40 (Bratislava)
    - QGIS 3.42+ (Münster)
    """
    qgis_version = Qgis.versionInt()

    if qgis_version >= 34000:  # QGIS 3.40+
        try:
            from qgis.PyQt.QtCore import QMetaType

            field = QgsField(name=name, type=QMetaType.Type.Bool, typeName="Bool")
            return field
        except (ImportError, AttributeError, TypeError):
            pass  # Fall through to legacy API

    # Legacy API for QGIS 3.34 and fallback
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        field = QgsField(name, QVariant.Bool)
        return field


class QCAnalysisTask(QgsTask):
    """Background task for running the QC analysis"""

    # Signals for progress updates
    progressChanged = pyqtSignal(str, int)  # message, progress value
    analysisComplete = pyqtSignal(object)  # Will emit the result layer
    analysisError = pyqtSignal(str)

    def __init__(
        self,
        description,
        input_layer,
        reference_layer,
        buffer_distance,
        region_layer=None,
        output_name="QC Result",
        use_boundary_check=False,
    ):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.buffer_distance = buffer_distance
        self.region_layer = region_layer
        self.output_name = output_name
        self.use_boundary_check = use_boundary_check
        self.result_layer = None
        self.exception = None
        self.boundary_field = None

    def log(self, message, progress=None):
        """Log message to both QGIS log and emit signal for progress dialog"""
        QgsMessageLog.logMessage(message, "GeoLinesQC", Qgis.Info)
        if progress is not None:
            self.progressChanged.emit(message, progress)
            self.setProgress(progress)

    def find_boundary_field(self, layer):
        """
        Find the boundary field with fuzzy matching.
        Looks for field name starting with 'mp_bound' (case-insensitive).
        Returns field name or None if not found.
        """
        for field in layer.fields():
            field_name_lower = field.name().lower()
            if field_name_lower.startswith("mp_bound"):
                self.log(
                    f"Found boundary field: '{field.name()}' (type: {field.typeName()})"
                )
                return field.name()
        return None

    def is_boundary_feature(self, feature):
        """
        Check if a feature is marked as a boundary feature.
        Handles both boolean and text field types.
        Returns True if feature is a boundary, False otherwise.
        """
        if not self.boundary_field:
            return False

        value = feature[self.boundary_field]

        # Handle NULL/None
        if value is None:
            return False

        # Handle boolean type
        if isinstance(value, bool):
            return value

        # Handle text/string type
        if isinstance(value, str):
            value_lower = value.lower().strip()
            # Common "true" values
            return value_lower in ["yes", "true", "1", "y", "t"]

        # Handle numeric (treat 0 as False, non-zero as True)
        try:
            return bool(int(value))
        except Exception as e:
            self.exception = e
            error_msg = f"Error in boundary feature: {str(e)}"
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", Qgis.Warning)
            return False

    def run(self):
        """Execute the analysis in background"""
        try:
            self.log("Starting GeoLines QC analysis...", 0)

            # Step 1: Check for boundary field if requested
            if self.use_boundary_check:
                self.log("Checking for boundary attribute field...", 2)
                self.boundary_field = self.find_boundary_field(self.input_layer)
                if self.boundary_field:
                    self.log(
                        f"Boundary checking enabled using field: '{self.boundary_field}'",
                        5,
                    )
                else:
                    self.log(
                        "Warning: Boundary checking requested but no matching field found (looking for 'mp_bound*')",
                        5,
                    )
                    self.log("Continuing with normal buffer for all features", 5)

            # Step 2: Clip layers if region is provided
            working_input = self.input_layer
            working_reference = self.reference_layer

            if self.region_layer:
                self.log("Clipping input layer to region...", 10)
                if self.isCanceled():
                    return False

                # Clip input layer
                clip_params = {
                    "INPUT": self.input_layer,
                    "OVERLAY": self.get_region_source(),
                    "OUTPUT": "memory:",
                }
                clip_result = processing.run("native:clip", clip_params)
                working_input = clip_result["OUTPUT"]

                input_count = working_input.featureCount()
                self.log(f"Input layer clipped: {input_count} features", 15)

                if self.isCanceled():
                    return False

                # Clip reference layer
                self.log("Clipping reference layer to region...", 20)
                clip_params["INPUT"] = self.reference_layer
                clip_result = processing.run("native:clip", clip_params)
                working_reference = clip_result["OUTPUT"]

                ref_count = working_reference.featureCount()
                self.log(f"Reference layer clipped: {ref_count} features", 25)
            else:
                input_count = working_input.featureCount()
                ref_count = working_reference.featureCount()
                self.log(
                    f"Using full datasets: {input_count} input, {ref_count} reference features",
                    10,
                )
                self.setProgress(25)

            if self.isCanceled():
                return False

            # Step 3: Buffer the reference layer
            self.log(
                f"Creating {self.buffer_distance}m buffer around reference layer...", 30
            )
            buffer_params = {
                "INPUT": working_reference,
                "DISTANCE": self.buffer_distance,
                "SEGMENTS": 5,
                "END_CAP_STYLE": 0,  # Round
                "JOIN_STYLE": 0,  # Round
                "MITER_LIMIT": 2,
                "DISSOLVE": True,  # Dissolve all buffers into one
                "OUTPUT": "memory:",
            }
            buffer_result = processing.run("native:buffer", buffer_params)
            buffered_reference = buffer_result["OUTPUT"]

            # For exact matching (boundary features), use the original reference geometry
            # No need to buffer - we want exact match!
            if self.use_boundary_check and self.boundary_field:
                self.log(
                    "Preparing exact match geometry for boundary features (no buffer)...",
                    35,
                )
                # Dissolve reference layer for exact matching (same as buffered but no distance)
                dissolve_params = {
                    "INPUT": working_reference,
                    "FIELD": [],  # Dissolve all into one
                    "OUTPUT": "memory:",
                }
                dissolve_result = processing.run("native:dissolve", dissolve_params)
                exact_match_reference = dissolve_result["OUTPUT"]
            else:
                exact_match_reference = None

            self.log("Buffer created successfully", 40)

            if self.isCanceled():
                return False

            # Step 4: Extract buffer geometries
            self.log("Extracting buffer geometries...", 45)
            buffer_geometry = None
            for feature in buffered_reference.getFeatures():
                buffer_geometry = feature.geometry()
                break  # Only one feature due to DISSOLVE

            if not buffer_geometry:
                raise Exception("Buffer geometry is empty")

            # Extract exact match geometry if available
            exact_geometry = None
            if exact_match_reference:
                for feature in exact_match_reference.getFeatures():
                    exact_geometry = feature.geometry()
                    break

            # Step 5: Process features with spatial logic
            self.log("Analyzing features with spatial index...", 50)

            # Create output layer
            output_layer = QgsVectorLayer(
                "LineString?crs=" + working_input.crs().authid(),
                self.output_name,
                "memory",
            )
            output_layer.dataProvider().addAttributes(
                [
                    create_intersects_field(name="intersects"),
                    create_intersects_field(name="is_boundary"),
                ]
            )
            output_layer.updateFields()

            total_features = working_input.featureCount()
            features_to_add = []

            within_count = 0
            outside_count = 0
            crossing_count = 0
            boundary_within = 0
            boundary_outside = 0

            # Process each feature
            for idx, feature in enumerate(working_input.getFeatures()):
                if self.isCanceled():
                    return False

                # Update progress every 10%
                if idx % max(1, total_features // 10) == 0:
                    progress = 50 + int((idx / total_features) * 40)
                    self.log(
                        f"Processing feature {idx + 1}/{total_features}...", progress
                    )

                geom = feature.geometry()
                is_boundary = (
                    self.is_boundary_feature(feature) if self.boundary_field else False
                )

                # Choose which buffer to check against
                check_geometry = (
                    exact_geometry
                    if (is_boundary and exact_geometry)
                    else buffer_geometry
                )

                # Log first boundary feature found
                if is_boundary and boundary_within == 0 and boundary_outside == 0:
                    self.log(
                        "Processing boundary features with exact match (0m buffer)..."
                    )

                # Check spatial relationship with appropriate buffer
                if check_geometry.contains(geom):
                    # Completely inside buffer
                    new_feature = QgsFeature(output_layer.fields())
                    new_feature.setGeometry(geom)
                    new_feature.setAttribute("intersects", True)
                    new_feature.setAttribute("is_boundary", is_boundary)
                    features_to_add.append(new_feature)
                    within_count += 1
                    if is_boundary:
                        boundary_within += 1

                elif not check_geometry.intersects(geom):
                    # Completely outside buffer
                    new_feature = QgsFeature(output_layer.fields())
                    new_feature.setGeometry(geom)
                    new_feature.setAttribute("intersects", False)
                    new_feature.setAttribute("is_boundary", is_boundary)
                    features_to_add.append(new_feature)
                    outside_count += 1
                    if is_boundary:
                        boundary_outside += 1

                else:
                    # Crosses buffer boundary - need to split
                    crossing_count += 1

                    # Part inside buffer
                    inside_geom = geom.intersection(check_geometry)
                    if not inside_geom.isEmpty():
                        # Handle both single and multi-part geometries
                        if inside_geom.isMultipart():
                            for part in inside_geom.asGeometryCollection():
                                new_feature = QgsFeature(output_layer.fields())
                                new_feature.setGeometry(part)
                                new_feature.setAttribute("intersects", True)
                                new_feature.setAttribute("is_boundary", is_boundary)
                                features_to_add.append(new_feature)
                        else:
                            new_feature = QgsFeature(output_layer.fields())
                            new_feature.setGeometry(inside_geom)
                            new_feature.setAttribute("intersects", True)
                            new_feature.setAttribute("is_boundary", is_boundary)
                            features_to_add.append(new_feature)

                    # Part outside buffer
                    outside_geom = geom.difference(check_geometry)
                    if not outside_geom.isEmpty():
                        # Handle both single and multi-part geometries
                        if outside_geom.isMultipart():
                            for part in outside_geom.asGeometryCollection():
                                new_feature = QgsFeature(output_layer.fields())
                                new_feature.setGeometry(part)
                                new_feature.setAttribute("intersects", False)
                                new_feature.setAttribute("is_boundary", is_boundary)
                                features_to_add.append(new_feature)
                        else:
                            new_feature = QgsFeature(output_layer.fields())
                            new_feature.setGeometry(outside_geom)
                            new_feature.setAttribute("intersects", False)
                            new_feature.setAttribute("is_boundary", is_boundary)
                            features_to_add.append(new_feature)

            self.log("Adding features to output layer...", 92)
            output_layer.dataProvider().addFeatures(features_to_add)
            output_layer.updateExtents()

            self.result_layer = output_layer

            total_segments = len(features_to_add)

            # Build summary message
            summary = (
                f"Analysis complete! Total input: {total_features} features | "
                f"Completely inside: {within_count} | "
                f"Completely outside: {outside_count} | "
                f"Crossing boundary: {crossing_count} | "
                f"Total output segments: {total_segments}"
            )

            if self.use_boundary_check and self.boundary_field:
                boundary_total = boundary_within + boundary_outside
                summary += (
                    f"\nBoundary features: {boundary_total} "
                    f"(exact match check: {boundary_within} within, {boundary_outside} outside)"
                )

            self.log(summary, 100)

            return True

        except Exception as e:
            self.exception = e
            error_msg = f"Error in analysis: {str(e)}"
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", Qgis.Critical)
            import traceback

            QgsMessageLog.logMessage(
                traceback.format_exc(), "GeoLinesQC", Qgis.Critical
            )
            self.log(error_msg, None)
            return False

    def get_region_source(self):
        """Get the appropriate source for region layer (selected features or all)"""
        if self.region_layer.selectedFeatureCount() > 0:
            QgsMessageLog.logMessage(
                f"Using {self.region_layer.selectedFeatureCount()} selected features for clipping",
                "GeoLinesQC",
                Qgis.Info,
            )
            return QgsProcessingFeatureSourceDefinition(
                self.region_layer.id(), selectedFeaturesOnly=True
            )
        QgsMessageLog.logMessage(
            "Using all features from region layer", "GeoLinesQC", Qgis.Info
        )
        return self.region_layer

    def finished(self, result):
        """Called when task completes"""
        if result:
            QgsMessageLog.logMessage(
                "✓ Analysis completed successfully", "GeoLinesQC", Qgis.Success
            )
            self.analysisComplete.emit(self.result_layer)
        else:
            if self.exception:
                self.analysisError.emit(str(self.exception))
            elif self.isCanceled():
                QgsMessageLog.logMessage(
                    "⚠ Analysis canceled by user", "GeoLinesQC", Qgis.Warning
                )
            else:
                self.analysisError.emit("Analysis failed for unknown reason")


class GeolinesQCPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&GeoLines QC")
        self.styles_dir = os.path.join(self.plugin_dir, "styles")
        self.current_task = None
        self.progress_dialog = None

    def tr(self, message):
        return QCoreApplication.translate("GeoLinesQC", message)

    def initGui(self):
        """Initialize the plugin GUI"""
        self.action = QAction(
            QIcon(":/plugins/GeoLinesQC/icons8-line-chart-50.png"),
            "GeoLines QC",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """Remove plugin menu and icon"""
        self.iface.removePluginMenu("&GeoLines QC", self.action)
        self.iface.removeToolBarIcon(self.action)
        # Cancel any running task
        if self.current_task:
            self.current_task.cancel()
        if self.progress_dialog:
            self.progress_dialog.close()

    def get_all_layers_from_tree(self, group=None):
        """
        Recursively get all layers from layer tree, including nested groups.
        Returns a list of tuples: (layer_name, layer_object)
        """
        if group is None:
            group = QgsProject.instance().layerTreeRoot()

        layers = []
        for child in group.children():
            if hasattr(child, "layer") and child.layer():
                # It's a layer
                layer = child.layer()
                # Get the display name from the tree
                display_name = child.name()
                # Check if it's in a group and add group prefix
                parent = child.parent()
                group_path = []
                while parent and parent != QgsProject.instance().layerTreeRoot():
                    group_path.insert(0, parent.name())
                    parent = parent.parent()

                if group_path:
                    full_name = " / ".join(group_path) + " / " + display_name
                else:
                    full_name = display_name

                layers.append((full_name, layer))
            elif hasattr(child, "children"):
                # It's a group, recurse
                layers.extend(self.get_all_layers_from_tree(child))

        return layers

    def run(self):
        """Show the dialog and start the analysis"""
        self.dialog = QDialog()
        self.dialog.setWindowTitle("GeoLines QC")
        self.dialog.setFixedWidth(DIALOG_WIDTH)
        layout = QVBoxLayout()

        # Add input fields
        self.layer1_combo = QComboBox()
        self.layer2_combo = QComboBox()
        self.region_combo = QComboBox()
        self.threshold_input = QLineEdit()
        self.threshold_input.setPlaceholderText(
            f"Optional: buffer distance [m] (default: {DEFAULT_BUFFER})"
        )

        # Add boundary check checkbox
        self.boundary_check = QCheckBox(
            "Use exact match for boundary lines (MP_BOUNDARY)"
        )
        self.boundary_check.setToolTip(
            "If checked, lines marked with 'MP_BOUNDARY' attribute will use exact matching (0m buffer)\n"
            "instead of the specified buffer distance. Useful for project boundary lines that must\n"
            "exactly match the reference dataset.\n\n"
            "Looks for field names starting with 'mp_bound' (case-insensitive).\n"
            "Accepts boolean (True/False) or text values ('yes', 'true', '1', etc.)"
        )

        layout.addWidget(QLabel("Layer to Check:"))
        layout.addWidget(self.layer1_combo)
        layout.addWidget(QLabel("Reference Layer:"))
        layout.addWidget(self.layer2_combo)
        layout.addWidget(QLabel("Buffer Distance:"))
        layout.addWidget(self.threshold_input)
        layout.addWidget(self.boundary_check)
        layout.addWidget(QLabel("Region Layer (optional):"))
        layout.addWidget(self.region_combo)

        # Get all layers including those in groups
        all_layers = self.get_all_layers_from_tree()

        # Store layer objects for later retrieval
        self.layer_map = {name: layer for name, layer in all_layers}

        # Populate combos with layer names
        layer_names = [name for name, _ in all_layers]

        self.layer1_combo.clear()
        self.layer1_combo.addItems(layer_names)

        self.layer2_combo.clear()
        self.layer2_combo.addItems(layer_names)

        self.region_combo.clear()
        self.region_combo.addItem("None")
        self.region_combo.addItems(layer_names)

        # Add run button
        self.run_button = QPushButton("Run Analysis")
        self.run_button.clicked.connect(self.start_analysis)
        layout.addWidget(self.run_button)

        self.dialog.setLayout(layout)
        self.dialog.exec_()

    def start_analysis(self):
        """Start the background analysis task"""
        # Get parameters
        layer1_name = self.layer1_combo.currentText()
        layer2_name = self.layer2_combo.currentText()
        region_name = self.region_combo.currentText()
        use_boundary_check = self.boundary_check.isChecked()

        buffer_distance = (
            float(self.threshold_input.text())
            if self.threshold_input.text()
            else DEFAULT_BUFFER
        )

        # Get actual layer objects
        input_layer = self.layer_map.get(layer1_name)
        reference_layer = self.layer_map.get(layer2_name)
        region_layer = (
            self.layer_map.get(region_name) if region_name != "None" else None
        )

        # Validate inputs
        if not input_layer or not reference_layer:
            QMessageBox.warning(
                self.dialog,
                "Invalid Selection",
                "Please select valid input and reference layers.",
            )
            return

        # Validate that layers are line geometries
        if input_layer.geometryType() != 1:  # 1 = Line
            QMessageBox.warning(
                self.dialog, "Invalid Geometry", "Input layer must be a line layer."
            )
            return

        if reference_layer.geometryType() != 1:
            QMessageBox.warning(
                self.dialog, "Invalid Geometry", "Reference layer must be a line layer."
            )
            return

        # Create output name
        output_name = f"{layer1_name.split('/')[-1]} — {layer2_name.split('/')[-1]} ({buffer_distance}m)"
        if use_boundary_check:
            output_name += " [+boundary check]"

        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Initializing analysis...", "Cancel", 0, 100, self.iface.mainWindow()
        )
        self.progress_dialog.setWindowTitle("GeoLines QC Analysis")
        self.progress_dialog.setWindowModality(
            Qt.NonModal
        )  # Non-modal so user can work
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()

        # Create and start the task
        self.current_task = QCAnalysisTask(
            "GeoLines QC Analysis",
            input_layer,
            reference_layer,
            buffer_distance,
            region_layer,
            output_name,
            use_boundary_check,
        )

        # Connect signals
        self.current_task.progressChanged.connect(self.update_progress)
        self.current_task.analysisComplete.connect(self.on_analysis_complete)
        self.current_task.analysisError.connect(self.on_analysis_error)
        self.progress_dialog.canceled.connect(self.on_cancel_clicked)

        # Add to task manager
        QgsApplication.taskManager().addTask(self.current_task)

        # Show message bar
        msg = "Analysis started. Using optimized spatial logic."
        if use_boundary_check:
            msg += " Boundary lines will use exact matching."
        self.iface.messageBar().pushMessage(
            "GeoLines QC", msg, level=Qgis.Info, duration=5
        )

        # Close settings dialog
        self.dialog.close()

    def update_progress(self, message, value):
        """Update progress dialog with current step"""
        if self.progress_dialog:
            self.progress_dialog.setLabelText(message)
            self.progress_dialog.setValue(value)

            # Also update message bar occasionally for key steps
            if value in [25, 40, 50, 70, 92]:
                self.iface.messageBar().pushMessage(
                    "GeoLines QC", message, level=Qgis.Info, duration=2
                )

    def on_cancel_clicked(self):
        """Handle cancel button in progress dialog"""
        if self.current_task:
            self.current_task.cancel()
            self.iface.messageBar().pushMessage(
                "GeoLines QC", "Canceling analysis...", level=Qgis.Warning, duration=3
            )

    def on_analysis_complete(self, result_layer):
        """Called when analysis completes successfully"""
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if result_layer:
            # Load style
            style_path = os.path.join(self.styles_dir, "intersects.qml")
            if os.path.exists(style_path):
                result_layer.loadNamedStyle(style_path)

            # Add to map
            QgsProject.instance().addMapLayer(result_layer)

            # Calculate statistics
            within_count = sum(1 for f in result_layer.getFeatures() if f["intersects"])
            outside_count = sum(
                1 for f in result_layer.getFeatures() if not f["intersects"]
            )
            total_count = within_count + outside_count

            # Calculate boundary statistics if available
            boundary_within = sum(
                1
                for f in result_layer.getFeatures()
                if f["intersects"] and f["is_boundary"]
            )
            boundary_outside = sum(
                1
                for f in result_layer.getFeatures()
                if not f["intersects"] and f["is_boundary"]
            )
            boundary_total = boundary_within + boundary_outside

            # Calculate lengths
            within_length = sum(
                f.geometry().length()
                for f in result_layer.getFeatures()
                if f["intersects"]
            )
            outside_length = sum(
                f.geometry().length()
                for f in result_layer.getFeatures()
                if not f["intersects"]
            )
            total_length = within_length + outside_length

            # Calculate quality score
            quality_score = (
                (within_length / total_length * 100) if total_length > 0 else 0
            )

            # Show success message in message bar
            msg = f"Layer '{result_layer.name()}' added | {within_count} within, {outside_count} outside"
            if boundary_total > 0:
                msg += f" | {boundary_total} boundary features"

            self.iface.messageBar().pushMessage(
                "✓ Analysis Complete", msg, level=Qgis.Success, duration=10
            )

            # Show detailed statistics dialog
            stats_message = f"""<b>GeoLines QC Results</b><br><br>
<b>Segments:</b><br>
• Within buffer: {within_count} segments<br>
• Outside buffer: {outside_count} segments<br>
• Total: {total_count} segments<br><br>

<b>Lengths:</b><br>
• Within buffer: {within_length:.2f} m<br>
• Outside buffer: {outside_length:.2f} m<br>
• Total: {total_length:.2f} m<br><br>

<b>Quality Score: {quality_score:.1f}%</b><br>
(percentage of line length within buffer)<br><br>"""

            if boundary_total > 0:
                boundary_quality = (
                    (boundary_within / boundary_total * 100)
                    if boundary_total > 0
                    else 0
                )
                stats_message += f"""<b>Boundary Features (exact match):</b><br>
• Within reference: {boundary_within} segments<br>
• Outside reference: {boundary_outside} segments<br>
• Total boundary: {boundary_total} segments<br>
• Boundary quality: {boundary_quality:.1f}%<br><br>"""

            stats_message += """<i>Green lines = within buffer<br>
Red lines = outside buffer (need review)</i>"""

            msg_box = QMessageBox(self.iface.mainWindow())
            msg_box.setWindowTitle("Analysis Complete")
            msg_box.setTextFormat(Qt.RichText)
            msg_box.setText(stats_message)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.exec_()

        self.current_task = None

    def on_analysis_error(self, error_message):
        """Called when analysis fails"""
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.iface.messageBar().pushMessage(
            "✗ Analysis Failed", error_message, level=Qgis.Critical, duration=10
        )

        QMessageBox.critical(
            self.iface.mainWindow(),
            "Analysis Error",
            f"An error occurred during analysis:\n\n{error_message}\n\n"
            f"Check the Log Messages panel (View → Panels → Log Messages) for details.",
        )

        self.current_task = None
