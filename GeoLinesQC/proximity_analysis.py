import os

import processing
from qgis import processing
from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterDistance,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

from GeoLinesQC.logger import log_message


class ProximityAnalysisAlgorithm(QgsProcessingAlgorithm):
    """
    Custom QGIS Processing Algorithm for Proximity Analysis
    """

    # Input layer parameter
    INPUT_LAYER = "INPUT_LAYER"
    # Reference layer parameter
    REFERENCE_LAYER = "REFERENCE_LAYER"
    # Distance parameter
    PROXIMITY_DISTANCE = "PROXIMITY_DISTANCE"
    # Output layer parameter
    OUTPUT_LAYER = "OUTPUT_LAYER"

    def tr(self, string):
        """
        Translate method for internationalization
        """
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        """
        Create a new instance of the algorithm
        """
        return ProximityAnalysisAlgorithm()

    def name(self):
        """
        Returns the unique algorithm name
        """
        return "qc"

    def displayName(self):
        """
        Returns the translated algorithm name
        """
        return self.tr("Quality Control")

    def group(self):
        """
        Returns the algorithm group
        """
        return self.tr("Swiss Alps 3D")

    def groupId(self):
        """
        Returns the algorithm group ID
        """
        return "sa3d"

    def shortHelpString(self):
        """
        Returns a short help description for the algorithm
        """
        return self.tr(
            "Performs proximity analysis between an input layer and a reference layer. "
            "Identifies and marks segments of the input layer within a specified distance "
            "of the reference layer features."
        )

    def initAlgorithm(self, config=None):
        """
        Define the input and output parameters
        """
        # Add input vector layer parameter
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER, self.tr("Input Layer"), [QgsProcessing.TypeVectorLine]
            )
        )

        # Add reference vector layer parameter
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.REFERENCE_LAYER,
                self.tr("Reference Layer"),
                [QgsProcessing.TypeVectorLine, QgsProcessing.TypeVectorPolygon],
            )
        )

        # Add proximity distance parameter
        self.addParameter(
            QgsProcessingParameterDistance(
                self.PROXIMITY_DISTANCE,
                self.tr("Proximity Distance"),
                defaultValue=100.0,
                parentParameterName=self.INPUT_LAYER,
            )
        )

        # Add output layer parameter
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_LAYER, self.tr("Output Proximity Layer")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        The core processing method
        """
        # Retrieve input parameters
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        reference_layer = self.parameterAsVectorLayer(
            parameters, self.REFERENCE_LAYER, context
        )
        proximity_distance = self.parameterAsDouble(
            parameters, self.PROXIMITY_DISTANCE, context
        )
        output_layer_path = self.parameterAsOutputLayer(
            parameters, self.OUTPUT_LAYER, context
        )

        # Buffer the reference layer
        buffered_reference = processing.run(
            "native:buffer",
            {
                "INPUT": reference_layer,
                "DISTANCE": proximity_distance,
                "SEGMENTS": 5,
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2,
                "DISSOLVE": False,
                "OUTPUT": "memory:",
            },
            context=context,
            feedback=feedback,
        )["OUTPUT"]

        # Prepare the output layer with the same fields as input layer
        fields = input_layer.fields()
        fields.append(QgsField("has_nearby_features", QVariant.Bool))

        # Create the output vector layer
        output_layer = QgsVectorLayer(
            f"LineString?crs={input_layer.crs().authid()}&index=yes",
            "Proximity_Analysis",
            "memory",
        )
        output_layer.dataProvider().addAttributes(fields)
        output_layer.updateFields()

        # Process features
        total_features = input_layer.featureCount()
        for current, input_feature in enumerate(input_layer.getFeatures()):
            # Check for cancellation
            if feedback.isCanceled():
                break

            # Update progress
            feedback.setProgress(int(current * 100 / total_features))

            # Get input feature geometry
            input_geom = input_feature.geometry()

            # Check proximity to buffered reference layer
            proximity_status = 0
            for ref_feature in buffered_reference.getFeatures():
                if input_geom.intersects(ref_feature.geometry()):
                    proximity_status = 1
                    break

            # Create output feature
            output_feature = QgsFeature(fields)
            output_feature.setGeometry(input_geom)

            # Copy attributes from input feature
            for idx, attr in enumerate(input_feature.attributes()):
                output_feature[idx] = attr

            # Set proximity status
            output_feature["has_nearby_features"] = proximity_status

            # Add feature to output layer
            output_layer.dataProvider().addFeature(output_feature)

        #

        # Write the output layer
        output_layer.updateExtents()

        log_message(f"Saving to {output_layer_path}")
        """QgsVectorFileWriter.writeAsVectorFormat(output_layer, output_layer_path,
                                       'utf-8', output_layer.crs(),
                                       'GPKG')"""
        # Apply styling (using either Method 1 or 2 from previous examples)
        self.apply_style(output_layer)

        # Add layer to project
        QgsProject.instance().addMapLayer(output_layer)

        return {self.OUTPUT_LAYER: output_layer_path}

    def apply_style(self, output_layer):
        # Get the path to your QML file
        plugin_path = os.path.dirname(__file__)
        qml_path = os.path.join(plugin_path, "styles", "has_nearby_features.qml")

        # Apply the style
        if os.path.exists(qml_path):
            log_message(f"Using style {qml_path}")
            output_layer.loadNamedStyle(qml_path)
            output_layer.triggerRepaint()


'''
# Register the algorithm
def register_proximity_analysis_algorithm():
    """
    Register the proximity analysis algorithm with QGIS processing framework
    """
    QgsProcessingProvider.addAlgorithm(ProximityAnalysisAlgorithm())'''
