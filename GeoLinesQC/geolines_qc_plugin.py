# -*- coding: utf-8 -*-

import os
from datetime import datetime

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
    
    def __init__(self, description, input_layer, reference_layer, buffer_distance, 
                 region_layer=None, output_name="QC Result"):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.buffer_distance = buffer_distance
        self.region_layer = region_layer
        self.output_name = output_name
        self.result_layer = None
        self.exception = None
        
    def log(self, message, progress=None):
        """Log message to both QGIS log and emit signal for progress dialog"""
        QgsMessageLog.logMessage(message, "GeoLinesQC", Qgis.Info)
        if progress is not None:
            self.progressChanged.emit(message, progress)
            self.setProgress(progress)
        
    def run(self):
        """Execute the analysis in background"""
        try:
            self.log("Starting GeoLines QC analysis...", 0)
            
            # Step 1: Clip layers if region is provided
            working_input = self.input_layer
            working_reference = self.reference_layer
            
            if self.region_layer:
                self.log("Clipping input layer to region...", 10)
                if self.isCanceled():
                    return False
                
                # Clip input layer
                clip_params = {
                    'INPUT': self.input_layer,
                    'OVERLAY': self.get_region_source(),
                    'OUTPUT': 'memory:'
                }
                clip_result = processing.run("native:clip", clip_params)
                working_input = clip_result['OUTPUT']
                
                input_count = working_input.featureCount()
                self.log(f"Input layer clipped: {input_count} features", 20)
                
                if self.isCanceled():
                    return False
                    
                # Clip reference layer
                self.log("Clipping reference layer to region...", 25)
                clip_params['INPUT'] = self.reference_layer
                clip_result = processing.run("native:clip", clip_params)
                working_reference = clip_result['OUTPUT']
                
                ref_count = working_reference.featureCount()
                self.log(f"Reference layer clipped: {ref_count} features", 30)
            else:
                input_count = working_input.featureCount()
                ref_count = working_reference.featureCount()
                self.log(f"Using full datasets: {input_count} input, {ref_count} reference features", 10)
                self.setProgress(30)
                
            if self.isCanceled():
                return False
                
            # Step 2: Buffer the reference layer
            self.log(f"Creating {self.buffer_distance}m buffer around reference layer...", 35)
            buffer_params = {
                'INPUT': working_reference,
                'DISTANCE': self.buffer_distance,
                'SEGMENTS': 5,
                'END_CAP_STYLE': 0,  # Round
                'JOIN_STYLE': 0,  # Round
                'MITER_LIMIT': 2,
                'DISSOLVE': True,  # Dissolve all buffers into one
                'OUTPUT': 'memory:'
            }
            buffer_result = processing.run("native:buffer", buffer_params)
            buffered_reference = buffer_result['OUTPUT']
            self.log("Buffer created successfully", 50)
            
            if self.isCanceled():
                return False
                
            # Step 3: Get lines WITHIN buffer (intersects = True)
            self.log("Finding lines within buffer zone...", 55)
            intersect_params = {
                'INPUT': working_input,
                'OVERLAY': buffered_reference,
                'OUTPUT': 'memory:'
            }
            intersect_result = processing.run("native:intersection", intersect_params)
            lines_within = intersect_result['OUTPUT']
            
            within_count = lines_within.featureCount()
            self.log(f"Found {within_count} line segments within buffer", 70)
            
            if self.isCanceled():
                return False
                
            # Step 4: Get lines OUTSIDE buffer (intersects = False)
            self.log("Finding lines outside buffer zone...", 75)
            difference_params = {
                'INPUT': working_input,
                'OVERLAY': buffered_reference,
                'OUTPUT': 'memory:'
            }
            difference_result = processing.run("native:difference", difference_params)
            lines_outside = difference_result['OUTPUT']
            
            outside_count = lines_outside.featureCount()
            self.log(f"Found {outside_count} line segments outside buffer", 85)
            
            if self.isCanceled():
                return False
                
            # Step 5: Add 'intersects' field to both layers and merge
            self.log("Tagging line segments...", 90)
            
            # Add field to lines_within and set to True
            lines_within.dataProvider().addAttributes([QgsField("intersects", QVariant.Bool)])
            lines_within.updateFields()
            lines_within.startEditing()
            for feature in lines_within.getFeatures():
                lines_within.changeAttributeValue(feature.id(), 
                    lines_within.fields().indexFromName("intersects"), True)
            lines_within.commitChanges()
            
            # Add field to lines_outside and set to False
            lines_outside.dataProvider().addAttributes([QgsField("intersects", QVariant.Bool)])
            lines_outside.updateFields()
            lines_outside.startEditing()
            for feature in lines_outside.getFeatures():
                lines_outside.changeAttributeValue(feature.id(), 
                    lines_outside.fields().indexFromName("intersects"), False)
            lines_outside.commitChanges()
            
            self.log("Merging results...", 95)
            
            # Merge the two layers
            merge_params = {
                'LAYERS': [lines_within, lines_outside],
                'CRS': working_input.crs(),
                'OUTPUT': 'memory:'
            }
            merge_result = processing.run("native:mergevectorlayers", merge_params)
            self.result_layer = merge_result['OUTPUT']
            self.result_layer.setName(self.output_name)
            
            total_count = within_count + outside_count
            self.log(f"Analysis complete! Total: {total_count} segments ({within_count} within, {outside_count} outside)", 100)
            
            return True
            
        except Exception as e:
            self.exception = e
            error_msg = f"Error in analysis: {str(e)}"
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", Qgis.Critical)
            self.log(error_msg, None)
            return False
    
    def get_region_source(self):
        """Get the appropriate source for region layer (selected features or all)"""
        if self.region_layer.selectedFeatureCount() > 0:
            QgsMessageLog.logMessage(
                f"Using {self.region_layer.selectedFeatureCount()} selected features for clipping",
                "GeoLinesQC", 
                Qgis.Info
            )
            return QgsProcessingFeatureSourceDefinition(
                self.region_layer.id(), 
                selectedFeaturesOnly=True
            )
        QgsMessageLog.logMessage("Using all features from region layer", "GeoLinesQC", Qgis.Info)
        return self.region_layer
    
    def finished(self, result):
        """Called when task completes"""
        if result:
            QgsMessageLog.logMessage("✓ Analysis completed successfully", "GeoLinesQC", Qgis.Success)
            self.analysisComplete.emit(self.result_layer)
        else:
            if self.exception:
                self.analysisError.emit(str(self.exception))
            elif self.isCanceled():
                QgsMessageLog.logMessage("⚠ Analysis canceled by user", "GeoLinesQC", Qgis.Warning)
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
            if hasattr(child, 'layer') and child.layer():
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
            elif hasattr(child, 'children'):
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
        
        buffer_distance = (
            float(self.threshold_input.text())
            if self.threshold_input.text()
            else DEFAULT_BUFFER
        )

        # Get actual layer objects
        input_layer = self.layer_map.get(layer1_name)
        reference_layer = self.layer_map.get(layer2_name)
        region_layer = self.layer_map.get(region_name) if region_name != "None" else None

        # Validate inputs
        if not input_layer or not reference_layer:
            QMessageBox.warning(
                self.dialog,
                "Invalid Selection",
                "Please select valid input and reference layers."
            )
            return
        
        # Validate that layers are line geometries
        if input_layer.geometryType() != 1:  # 1 = Line
            QMessageBox.warning(
                self.dialog,
                "Invalid Geometry",
                "Input layer must be a line layer."
            )
            return
            
        if reference_layer.geometryType() != 1:
            QMessageBox.warning(
                self.dialog,
                "Invalid Geometry",
                "Reference layer must be a line layer."
            )
            return

        # Create output name
        output_name = f"{layer1_name.split('/')[-1]} — {layer2_name.split('/')[-1]} ({buffer_distance}m)"

        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Initializing analysis...",
            "Cancel",
            0,
            100,
            self.iface.mainWindow()
        )
        self.progress_dialog.setWindowTitle("GeoLines QC Analysis")
        self.progress_dialog.setWindowModality(Qt.NonModal)  # Non-modal so user can work
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
            output_name
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
            duration=3
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
                    "GeoLines QC",
                    message,
                    level=Qgis.Info,
                    duration=2
                )

    def on_cancel_clicked(self):
        """Handle cancel button in progress dialog"""
        if self.current_task:
            self.current_task.cancel()
            self.iface.messageBar().pushMessage(
                "GeoLines QC",
                "Canceling analysis...",
                level=Qgis.Warning,
                duration=3
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
            within_count = sum(1 for f in result_layer.getFeatures() if f['intersects'])
            outside_count = sum(1 for f in result_layer.getFeatures() if not f['intersects'])
            total_count = within_count + outside_count
            
            # Calculate lengths
            within_length = sum(f.geometry().length() for f in result_layer.getFeatures() if f['intersects'])
            outside_length = sum(f.geometry().length() for f in result_layer.getFeatures() if not f['intersects'])
            total_length = within_length + outside_length
            
            # Calculate quality score
            quality_score = (within_length / total_length * 100) if total_length > 0 else 0
            
            # Show success message in message bar
            self.iface.messageBar().pushMessage(
                "✓ Analysis Complete",
                f"Layer '{result_layer.name()}' added to map | {within_count} within, {outside_count} outside buffer",
                level=Qgis.Success,
                duration=10
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
            "✗ Analysis Failed",
            error_message,
            level=Qgis.Critical,
            duration=10
        )
        
        QMessageBox.critical(
            self.iface.mainWindow(),
            "Analysis Error",
            f"An error occurred during analysis:\n\n{error_message}\n\n"
            f"Check the Log Messages panel (View → Panels → Log Messages) for details."
        )
        
        self.current_task = None
