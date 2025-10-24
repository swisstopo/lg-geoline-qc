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
)


DEFAULT_BUFFER = 500.0
DIALOG_WIDTH = 400


class QCAnalysisTask(QgsTask):
    """Background task for running the QC analysis"""
    
    # Signals for progress updates
    progressUpdated = pyqtSignal(str, int)
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
        
    def run(self):
        """Execute the analysis in background"""
        try:
            # Step 1: Clip layers if region is provided
            self.setProgress(10)
            if self.isCanceled():
                return False
                
            working_input = self.input_layer
            working_reference = self.reference_layer
            
            if self.region_layer:
                QgsMessageLog.logMessage("Clipping layers to region...", "GeoLinesQC", Qgis.Info)
                
                # Clip input layer
                clip_params = {
                    'INPUT': self.input_layer,
                    'OVERLAY': self.get_region_source(),
                    'OUTPUT': 'memory:'
                }
                clip_result = processing.run("native:clip", clip_params)
                working_input = clip_result['OUTPUT']
                
                if self.isCanceled():
                    return False
                    
                # Clip reference layer
                clip_params['INPUT'] = self.reference_layer
                clip_result = processing.run("native:clip", clip_params)
                working_reference = clip_result['OUTPUT']
                
            self.setProgress(30)
            if self.isCanceled():
                return False
                
            # Step 2: Buffer the reference layer
            QgsMessageLog.logMessage(f"Buffering reference layer by {self.buffer_distance}m...", 
                                    "GeoLinesQC", Qgis.Info)
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
            
            self.setProgress(50)
            if self.isCanceled():
                return False
                
            # Step 3: Get lines WITHIN buffer (intersects = True)
            QgsMessageLog.logMessage("Finding lines within buffer...", "GeoLinesQC", Qgis.Info)
            intersect_params = {
                'INPUT': working_input,
                'OVERLAY': buffered_reference,
                'OUTPUT': 'memory:'
            }
            intersect_result = processing.run("native:intersection", intersect_params)
            lines_within = intersect_result['OUTPUT']
            
            self.setProgress(70)
            if self.isCanceled():
                return False
                
            # Step 4: Get lines OUTSIDE buffer (intersects = False)
            QgsMessageLog.logMessage("Finding lines outside buffer...", "GeoLinesQC", Qgis.Info)
            difference_params = {
                'INPUT': working_input,
                'OVERLAY': buffered_reference,
                'OUTPUT': 'memory:'
            }
            difference_result = processing.run("native:difference", difference_params)
            lines_outside = difference_result['OUTPUT']
            
            self.setProgress(85)
            if self.isCanceled():
                return False
                
            # Step 5: Add 'intersects' field to both layers and merge
            QgsMessageLog.logMessage("Tagging and merging results...", "GeoLinesQC", Qgis.Info)
            
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
            
            # Merge the two layers
            merge_params = {
                'LAYERS': [lines_within, lines_outside],
                'CRS': working_input.crs(),
                'OUTPUT': 'memory:'
            }
            merge_result = processing.run("native:mergevectorlayers", merge_params)
            self.result_layer = merge_result['OUTPUT']
            self.result_layer.setName(self.output_name)
            
            self.setProgress(100)
            return True
            
        except Exception as e:
            self.exception = e
            QgsMessageLog.logMessage(f"Error in analysis: {str(e)}", "GeoLinesQC", Qgis.Critical)
            return False
    
    def get_region_source(self):
        """Get the appropriate source for region layer (selected features or all)"""
        if self.region_layer.selectedFeatureCount() > 0:
            return QgsProcessingFeatureSourceDefinition(
                self.region_layer.id(), 
                selectedFeaturesOnly=True
            )
        return self.region_layer
    
    def finished(self, result):
        """Called when task completes"""
        if result:
            QgsMessageLog.logMessage("Analysis completed successfully", "GeoLinesQC", Qgis.Success)
            self.analysisComplete.emit(self.result_layer)
        else:
            if self.exception:
                self.analysisError.emit(str(self.exception))
            elif self.isCanceled():
                QgsMessageLog.logMessage("Analysis canceled by user", "GeoLinesQC", Qgis.Warning)
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
        self.current_task.analysisComplete.connect(self.on_analysis_complete)
        self.current_task.analysisError.connect(self.on_analysis_error)
        
        # Add to task manager
        QgsApplication.taskManager().addTask(self.current_task)
        
        # Show message
        self.iface.messageBar().pushMessage(
            "Info",
            "Analysis started in background. You can continue working...",
            level=Qgis.Info,
            duration=5
        )
        
        # Close dialog
        self.dialog.close()

    def on_analysis_complete(self, result_layer):
        """Called when analysis completes successfully"""
        if result_layer:
            # Load style
            style_path = os.path.join(self.styles_dir, "intersects.qml")
            if os.path.exists(style_path):
                result_layer.loadNamedStyle(style_path)
            
            # Add to map
            QgsProject.instance().addMapLayer(result_layer)
            
            # Show success message
            self.iface.messageBar().pushMessage(
                "Success",
                f"Analysis complete! Layer '{result_layer.name()}' added to map.",
                level=Qgis.Success,
                duration=5
            )
            
            # Show statistics
            within_count = sum(1 for f in result_layer.getFeatures() if f['intersects'])
            outside_count = sum(1 for f in result_layer.getFeatures() if not f['intersects'])
            
            QMessageBox.information(
                self.iface.mainWindow(),
                "Analysis Complete",
                f"Results:\n\n"
                f"Lines within buffer: {within_count}\n"
                f"Lines outside buffer: {outside_count}\n\n"
                f"Total segments: {within_count + outside_count}"
            )
        
        self.current_task = None

    def on_analysis_error(self, error_message):
        """Called when analysis fails"""
        self.iface.messageBar().pushMessage(
            "Error",
            f"Analysis failed: {error_message}",
            level=Qgis.Critical,
            duration=10
        )
        
        QMessageBox.critical(
            self.iface.mainWindow(),
            "Analysis Error",
            f"An error occurred during analysis:\n\n{error_message}"
        )
        
        self.current_task = None
