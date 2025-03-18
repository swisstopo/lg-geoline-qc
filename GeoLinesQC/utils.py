from qgis.core import (
    Qgis,
    QgsFeature,
    QgsMessageLog,
    QgsProject,
     QgsVectorLayer,
)


def create_spatial_index(layer):
    """
    Create a spatial index for a vector layer if one doesn't exist already.
    Logs the process using QgsMessageLog.

    Args:
        layer (QgsVectorLayer): The vector layer to create spatial index for

    Returns:
        bool: True if spatial index was created or already existed, False otherwise
    """
    # Check if layer is valid and is a vector layer
    if not layer or not isinstance(layer, QgsVectorLayer):
        QgsMessageLog.logMessage(
            "Invalid or non-vector layer provided",
            "GeoLinesQC",
            level=Qgis.Error,
        )
        return False

    # Get the data provider
    provider = layer.dataProvider()

    # Check if spatial index already exists
    if provider.hasSpatialIndex():
        QgsMessageLog.logMessage(
            f"Spatial index already exists for layer '{layer.name()}'",
            "GeoLinesQC",
            level=Qgis.Warning,
        )
        return True

    # Create spatial index
    QgsMessageLog.logMessage(
        f"Creating spatial index for layer '{layer.name()}'",
        "GeoLinesQC",
        level=Qgis.Info,
    )
    result = provider.createSpatialIndex()

    if result:
        QgsMessageLog.logMessage(
            f"Successfully created spatial index for layer '{layer.name()}'",
            "GeoLinesQC",
            level=Qgis.Info,
        )
        return True
    else:
        QgsMessageLog.logMessage(
            f"Failed to create spatial index for layer '{layer.name()}'",
            "GeoLinesQC",
            level=Qgis.Warning,
        )
        return False


def geometry_to_vector_layer(geometry, layer_name="Region", crs="EPSG:2056"):
    """
    Converts a QgsGeometry object to a QgsVectorLayer.

    Args:
        geometry (QgsGeometry): The geometry to convert.
        layer_name (str): Name of the output layer.
        crs (str): Coordinate reference system of the output layer (default: EPSG:4326).

    Returns:
        QgsVectorLayer: A memory layer containing the geometry.
    """
    # Create a new memory layer
    layer = QgsVectorLayer(f"Polygon?crs={crs}", layer_name, "memory")
    provider = layer.dataProvider()

    # Create a feature and set its geometry
    feature = QgsFeature()
    feature.setGeometry(geometry)

    # Add the feature to the layer
    provider.addFeatures([feature])

    # Update the layer's extent
    layer.updateExtents()

    return layer


def get_layer_toc_name(layer):
    """
    Returns the name of the layer as it appears in the Table of Contents (TOC).

    Args:
        layer (QgsMapLayer): The layer to get the TOC name for.

    Returns:
        str: The name of the layer as displayed in the TOC.
    """
    # Get the root of the layer tree
    root = QgsProject.instance().layerTreeRoot()

    # Find the layer tree layer that corresponds to the given layer
    layer_tree_layer = root.findLayer(layer.id())

    if layer_tree_layer:
        # Return the custom name if it exists, otherwise return the layer's name
        return layer_tree_layer.name()
    else:
        # If the layer is not in the TOC, return the layer's name
        return layer.name()
