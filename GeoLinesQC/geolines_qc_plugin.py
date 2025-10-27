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
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsProcessingFeatureSourceDefinition,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsTask,
    QgsApplication,
    QgsWkbTypes,
    QgsSpatialIndex,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, QVariant, pyqtSignal
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
)


DEFAULT_BUFFER = 500.0
DIALOG_WIDTH = 400


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
    ):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.buffer_distance = buffer_distance
        self.region_layer = region_layer
        self.output_name = output_name
        self.result_layer = None
        self.exception = None

        # Create processing context and feedback for background task
        self.context = QgsProcessingContext()
        self.context.setProject(QgsProject.instance())
        self.feedback = QgsProcessingFeedback()

    def cancel(self):
        """Override cancel to also cancel feedback"""
        self.feedback.cancel()
        super().cancel()

    def log(self, message, level=Qgis.Info, progress=None):
        """Log message to both QGIS log and emit signal for progress dialog"""
        QgsMessageLog.logMessage(message, "GeoLinesQC", level)
        if progress is not None:
            self.progressChanged.emit(message, progress)
            self.setProgress(progress)

    def run(self):
        """Execute the analysis in background"""
        try:
            self.log("Starting GeoLines QC analysis...", Qgis.Info, 0)

            # Step 1: Determine clipping strategy
            working_input = self.input_layer
            working_reference = self.reference_layer

            if self.region_layer:
                # Use regional filter
                working_input, working_reference = self._clip_to_region()
            else:
                # Use oriented bounding box optimization
                working_reference = self._clip_to_input_extent(working_reference)

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            input_count = working_input.featureCount()
            ref_count = working_reference.featureCount()
            self.log(
                f"Working with {input_count} input and {ref_count} reference features",
                Qgis.Info,
                35,
            )

            if ref_count == 0:
                raise Exception(
                    "No reference features in the working area. Check your region filter or input extent."
                )

            if input_count == 0:
                raise Exception(
                    "No input features in the working area. Check your region filter."
                )

            # Step 2: Buffer the reference layer
            self.log(
                f"Creating {self.buffer_distance}m buffer around reference layer...",
                Qgis.Info,
                40,
            )
            buffered_reference = self._create_buffer(working_reference)
            self.log("Buffer created successfully", Qgis.Info, 55)

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            # Step 3: Split input lines by buffer intersection
            lines_within, lines_outside = self._split_by_buffer(
                working_input, buffered_reference
            )

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            # Step 4: Merge results with tagging
            self.result_layer = self._merge_and_tag(
                lines_within, lines_outside, working_input
            )

            within_count = sum(
                1 for f in self.result_layer.getFeatures() if f["intersects"]
            )
            outside_count = sum(
                1 for f in self.result_layer.getFeatures() if not f["intersects"]
            )

            self.log(
                f"Analysis complete! {within_count} segments within, {outside_count} outside buffer",
                Qgis.Success,
                100,
            )

            return True

        except Exception as e:
            import traceback

            self.exception = e
            error_msg = f"Error in analysis: {str(e)}"
            tb = traceback.format_exc()
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", Qgis.Critical)
            QgsMessageLog.logMessage(tb, "GeoLinesQC", Qgis.Critical)
            self.log(error_msg, Qgis.Critical)
            return False

    def _clip_to_region(self):
        """Clip both input and reference layers to the region using spatial filtering"""
        self.log("Using regional filter...", Qgis.Info, 10)

        # Get region geometries
        region_geoms = []
        if self.region_layer.selectedFeatureCount() > 0:
            region_geoms = [
                f.geometry() for f in self.region_layer.getSelectedFeatures()
            ]
            self.log(f"Using {len(region_geoms)} selected region features", Qgis.Info)
        else:
            region_geoms = [f.geometry() for f in self.region_layer.getFeatures()]
            self.log(f"Using all {len(region_geoms)} region features", Qgis.Info)

        # Combine all region geometries into one
        combined_region = QgsGeometry.unaryUnion(region_geoms)
        region_bbox = combined_region.boundingBox()

        if self.isCanceled() or self.feedback.isCanceled():
            return None, None

        # Filter input layer
        self.log("Filtering input layer to region...", Qgis.Info, 15)
        clipped_input = self._filter_layer_by_geometry(
            self.input_layer, combined_region, region_bbox
        )
        input_count = clipped_input.featureCount()
        self.log(f"Input layer filtered: {input_count} features", Qgis.Info, 20)

        if self.isCanceled() or self.feedback.isCanceled():
            return None, None

        # Filter reference layer
        self.log("Filtering reference layer to region...", Qgis.Info, 25)
        clipped_reference = self._filter_layer_by_geometry(
            self.reference_layer, combined_region, region_bbox
        )
        ref_count = clipped_reference.featureCount()
        self.log(f"Reference layer filtered: {ref_count} features", Qgis.Info, 30)

        return clipped_input, clipped_reference

    def _filter_layer_by_geometry(self, input_layer, filter_geom, filter_bbox):
        """Filter a layer by intersection with a geometry - most reliable method"""
        # Create output memory layer
        filtered_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "filtered",
            "memory",
        )

        filtered_provider = filtered_layer.dataProvider()
        filtered_provider.addAttributes(input_layer.fields())
        filtered_layer.updateFields()

        # Filter features
        filtered_features = []
        for feat in input_layer.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                break

            feat_geom = feat.geometry()
            if not feat_geom:
                continue

            # Quick bbox check first
            if not feat_geom.boundingBox().intersects(filter_bbox):
                continue

            # Then precise intersection test
            if feat_geom.intersects(filter_geom):
                filtered_features.append(feat)

        # Add filtered features
        filtered_provider.addFeatures(filtered_features)
        filtered_layer.updateExtents()

        return filtered_layer

    def _prepare_region_layer(self):
        """
        Prepare region layer for clipping by creating a memory layer
        with selected features or all features
        """
        # Create memory layer for region
        region_memory = QgsVectorLayer(
            f"Polygon?crs={self.region_layer.crs().authid()}", "region_temp", "memory"
        )
        region_provider = region_memory.dataProvider()

        # Get features (selected or all)
        if self.region_layer.selectedFeatureCount() > 0:
            features = list(self.region_layer.getSelectedFeatures())
            self.log(
                f"Using {len(features)} selected features from region layer", Qgis.Info
            )
        else:
            features = list(self.region_layer.getFeatures())
            self.log(f"Using all {len(features)} features from region layer", Qgis.Info)

        # Add features to memory layer
        region_provider.addFeatures(features)
        region_memory.updateExtents()

        return region_memory

    def _clip_layer(self, input_layer, overlay_layer):
        """Extract features using spatial relationship instead of clipping"""
        self.log("Extracting features by location...", Qgis.Info)

        # Use extract by location instead of clip - more robust in background tasks
        extract_params = {
            "INPUT": input_layer,
            "PREDICATE": [0],  # intersects
            "INTERSECT": overlay_layer,
            "OUTPUT": "memory:",
        }

        try:
            extract_result = processing.run(
                "native:extractbylocation",
                extract_params,
                context=self.context,
                feedback=self.feedback,
            )
            self.log(
                f"Extracted {extract_result['OUTPUT'].featureCount()} features",
                Qgis.Info,
            )
            return extract_result["OUTPUT"]
        except Exception as e:
            self.log(f"Extract by location failed: {str(e)}", Qgis.Critical)
            # Last resort: manual filtering with spatial index
            return self._manual_spatial_filter(input_layer, overlay_layer)

    def _manual_spatial_filter(self, input_layer, overlay_layer):
        """Manually filter features using spatial index - most robust method"""
        self.log("Using manual spatial filtering...", Qgis.Warning)

        # Create spatial index for overlay
        overlay_index = QgsSpatialIndex(overlay_layer.getFeatures())

        # Create output memory layer
        output_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "filtered",
            "memory",
        )

        output_provider = output_layer.dataProvider()
        output_provider.addAttributes(input_layer.fields())
        output_layer.updateFields()

        # Get overlay geometries for intersection test
        overlay_geoms = {}
        for feat in overlay_layer.getFeatures():
            overlay_geoms[feat.id()] = feat.geometry()

        # Filter input features
        filtered_features = []
        for feat in input_layer.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                break

            feat_geom = feat.geometry()
            # Get candidate IDs from spatial index
            candidate_ids = overlay_index.intersects(feat_geom.boundingBox())

            # Test actual intersection with candidates
            intersects = False
            for overlay_id in candidate_ids:
                if feat_geom.intersects(overlay_geoms[overlay_id]):
                    intersects = True
                    break

            if intersects:
                filtered_features.append(feat)

        output_provider.addFeatures(filtered_features)
        output_layer.updateExtents()

        self.log(f"Manually filtered to {len(filtered_features)} features", Qgis.Info)
        return output_layer

    def _clip_to_input_extent(self, reference_layer):
        """
        Filter reference layer to an expanded bounding box of input layer.
        This optimizes performance when no regional filter is provided.
        Uses direct filtering instead of clip operations for reliability.
        """
        self.log(
            "Optimizing: filtering reference to input extent + buffer...", Qgis.Info, 10
        )

        # Get input layer extent
        input_extent = self.input_layer.extent()

        # Expand extent by buffer distance (with some margin)
        margin = self.buffer_distance * 1.5  # 50% extra margin for safety
        expanded_extent = QgsRectangle(
            input_extent.xMinimum() - margin,
            input_extent.yMinimum() - margin,
            input_extent.xMaximum() + margin,
            input_extent.yMaximum() + margin,
        )

        self.log(
            f"Filtering reference to expanded extent: {expanded_extent}", Qgis.Info
        )

        # Create output memory layer with same structure as reference
        filtered_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(reference_layer.wkbType())}?crs={reference_layer.crs().authid()}",
            "filtered_reference",
            "memory",
        )

        filtered_provider = filtered_layer.dataProvider()
        filtered_provider.addAttributes(reference_layer.fields())
        filtered_layer.updateFields()

        # Filter features by bounding box
        filtered_features = []
        for feat in reference_layer.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                break

            feat_geom = feat.geometry()
            if feat_geom and feat_geom.boundingBox().intersects(expanded_extent):
                filtered_features.append(feat)

        # Add filtered features to output layer
        filtered_provider.addFeatures(filtered_features)
        filtered_layer.updateExtents()

        ref_count = len(filtered_features)
        self.log(
            f"Reference layer filtered to extent: {ref_count} features", Qgis.Info, 30
        )

        return filtered_layer

    def _create_buffer(self, layer):
        """Create dissolved buffer around layer"""
        buffer_params = {
            "INPUT": layer,
            "DISTANCE": self.buffer_distance,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,  # Round
            "JOIN_STYLE": 0,  # Round
            "MITER_LIMIT": 2,
            "DISSOLVE": True,  # Dissolve all buffers into one
            "OUTPUT": "memory:",
        }
        buffer_result = processing.run(
            "native:buffer", buffer_params, context=self.context, feedback=self.feedback
        )
        return buffer_result["OUTPUT"]

    def _split_by_buffer(self, input_layer, buffered_reference):
        """Split input lines into those within and outside the buffer"""
        # Step 1: Get lines WITHIN buffer (intersection)
        self.log("Finding lines within buffer zone...", Qgis.Info, 60)
        intersect_params = {
            "INPUT": input_layer,
            "OVERLAY": buffered_reference,
            "OUTPUT": "memory:",
        }
        intersect_result = processing.run(
            "native:intersection",
            intersect_params,
            context=self.context,
            feedback=self.feedback,
        )
        lines_within = intersect_result["OUTPUT"]

        within_count = lines_within.featureCount()
        self.log(f"Found {within_count} line segments within buffer", Qgis.Info, 75)

        if self.isCanceled() or self.feedback.isCanceled():
            return None, None

        # Step 2: Get lines OUTSIDE buffer (difference)
        self.log("Finding lines outside buffer zone...", Qgis.Info, 80)
        difference_params = {
            "INPUT": input_layer,
            "OVERLAY": buffered_reference,
            "OUTPUT": "memory:",
        }
        difference_result = processing.run(
            "native:difference",
            difference_params,
            context=self.context,
            feedback=self.feedback,
        )
        lines_outside = difference_result["OUTPUT"]

        outside_count = lines_outside.featureCount()
        self.log(f"Found {outside_count} line segments outside buffer", Qgis.Info, 85)

        return lines_within, lines_outside

    def _merge_and_tag(self, lines_within, lines_outside, original_layer):
        """Add 'intersects' field to both layers and merge them"""
        self.log("Tagging line segments...", Qgis.Info, 90)

        # Add field to lines_within and set to True
        lines_within.dataProvider().addAttributes(
            [QgsField("intersects", QVariant.Bool)]
        )
        lines_within.updateFields()
        lines_within.startEditing()
        for feature in lines_within.getFeatures():
            lines_within.changeAttributeValue(
                feature.id(), lines_within.fields().indexFromName("intersects"), True
            )
        lines_within.commitChanges()

        # Add field to lines_outside and set to False
        lines_outside.dataProvider().addAttributes(
            [QgsField("intersects", QVariant.Bool)]
        )
        lines_outside.updateFields()
        lines_outside.startEditing()
        for feature in lines_outside.getFeatures():
            lines_outside.changeAttributeValue(
                feature.id(), lines_outside.fields().indexFromName("intersects"), False
            )
        lines_outside.commitChanges()

        self.log("Merging results...", Qgis.Info, 95)

        # Merge the two layers
        merge_params = {
            "LAYERS": [lines_within, lines_outside],
            "CRS": original_layer.crs(),
            "OUTPUT": "memory:",
        }
        merge_result = processing.run(
            "native:mergevectorlayers",
            merge_params,
            context=self.context,
            feedback=self.feedback,
        )
        result_layer = merge_result["OUTPUT"]
        result_layer.setName(self.output_name)

        return result_layer

    def finished(self, result):
        """Called when task completes"""
        if result:
            QgsMessageLog.logMessage(
                "✓ Analysis completed successfully", "GeoLinesQC", Qgis.Success
            )
            self.analysisComplete.emit(self.result_layer)
        else:
            if self.exception:
                import traceback

                tb = traceback.format_exc()
                QgsMessageLog.logMessage(tb, "GeoLinesQC", Qgis.Critical)
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

        layout.addWidget(QLabel("Layer to Check:"))
        layout.addWidget(self.layer1_combo)
        layout.addWidget(QLabel("Reference Layer:"))
        layout.addWidget(self.layer2_combo)
        layout.addWidget(QLabel("Buffer Distance:"))
        layout.addWidget(self.threshold_input)
        layout.addWidget(QLabel("Region Layer (optional):"))
        layout.addWidget(self.region_combo)

        # Get all layers including those in groups
        all_layers = self.get_all_layers_from_tree()

        # Store layer objects for later retrieval
        self.layer_map = {name: layer for name, layer in all_layers}

        # Filter layers: only show line layers for input/reference, polygon for region
        line_layers = [
            (name, layer)
            for name, layer in all_layers
            if layer.geometryType() == QgsWkbTypes.LineGeometry
        ]
        polygon_layers = [
            (name, layer)
            for name, layer in all_layers
            if layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]

        # Populate line layer combos
        line_layer_names = [name for name, _ in line_layers]
        self.layer1_combo.clear()
        self.layer1_combo.addItems(line_layer_names)

        self.layer2_combo.clear()
        self.layer2_combo.addItems(line_layer_names)

        # Populate region combo with polygon layers
        polygon_layer_names = [name for name, _ in polygon_layers]
        self.region_combo.clear()
        self.region_combo.addItem("None (use input extent)")
        self.region_combo.addItems(polygon_layer_names)

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

        try:
            buffer_distance = (
                float(self.threshold_input.text())
                if self.threshold_input.text()
                else DEFAULT_BUFFER
            )
        except ValueError:
            QMessageBox.warning(
                self.dialog,
                "Invalid Input",
                "Please enter a valid number for buffer distance.",
            )
            return

        # Get actual layer objects
        input_layer = self.layer_map.get(layer1_name)
        reference_layer = self.layer_map.get(layer2_name)
        region_layer = (
            self.layer_map.get(region_name)
            if region_name and region_name != "None (use input extent)"
            else None
        )

        # Validate inputs
        if not input_layer or not reference_layer:
            QMessageBox.warning(
                self.dialog,
                "Invalid Selection",
                "Please select valid input and reference layers.",
            )
            return

        # Check if layers have the same CRS
        if input_layer.crs() != reference_layer.crs():
            QMessageBox.warning(
                self.dialog,
                "CRS Mismatch",
                f"Input and reference layers have different CRS:\n"
                f"Input: {input_layer.crs().authid()}\n"
                f"Reference: {reference_layer.crs().authid()}\n\n"
                f"Please reproject one of them to match the other.",
            )
            return

        if region_layer and region_layer.crs() != input_layer.crs():
            QMessageBox.warning(
                self.dialog,
                "CRS Mismatch",
                f"Region layer has different CRS than input layer:\n"
                f"Region: {region_layer.crs().authid()}\n"
                f"Input: {input_layer.crs().authid()}\n\n"
                f"Please reproject the region layer to match.",
            )
            return

        # Create output name
        layer1_short = layer1_name.split("/")[-1]
        layer2_short = layer2_name.split("/")[-1]
        output_name = f"{layer1_short} vs {layer2_short} ({buffer_distance}m)"

        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Initializing analysis...", "Cancel", 0, 100, self.iface.mainWindow()
        )
        self.progress_dialog.setWindowTitle("GeoLines QC Analysis")
        self.progress_dialog.setWindowModality(Qt.NonModal)
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
        )

        # Connect signals
        self.current_task.progressChanged.connect(self.update_progress)
        self.current_task.analysisComplete.connect(self.on_analysis_complete)
        self.current_task.analysisError.connect(self.on_analysis_error)
        self.progress_dialog.canceled.connect(self.on_cancel_clicked)

        # Add to task manager
        QgsApplication.taskManager().addTask(self.current_task)

        # Show message bar
        self.iface.messageBar().pushMessage(
            "GeoLines QC",
            "Analysis started in background. Check progress dialog and task manager.",
            level=Qgis.Info,
            duration=3,
        )

        # Close settings dialog
        self.dialog.close()

    def update_progress(self, message, value):
        """Update progress dialog with current step"""
        if self.progress_dialog:
            self.progress_dialog.setLabelText(message)
            self.progress_dialog.setValue(value)

            # Also update message bar occasionally for key steps
            if value in [30, 50, 70, 90]:
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
            self.iface.messageBar().pushMessage(
                "✓ Analysis Complete",
                f"Layer '{result_layer.name()}' added | {within_count} within, {outside_count} outside",
                level=Qgis.Success,
                duration=10,
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
(percentage of line length within buffer)<br><br>

<i>Green lines = within buffer<br>
Red lines = outside buffer (need review)</i>
"""

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
