from qgis.core import QgsFeature, QgsProject, QgsVectorLayer


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
