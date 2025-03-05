from qgis.core import (QgsFeature, Qgis, QgsMessageLog, QgsProject, QgsVectorLayer,
                       QgsWkbTypes)


def check_line_similarity(segment, reference_layer, tolerance=0.001):
    """
    Compare a line segment with lines in a reference layer to check for similarity.

    :param segment: QgsGeometry of the line segment to check
    :param reference_layer: QgsVectorLayer containing reference lines
    :param tolerance: Spatial tolerance for coordinate comparisons (default 0.001)
    :return: Boolean indicating if a similar line exists in the reference layer
    """
    # Ensure the segment is a line geometry
    if segment.type() != QgsWkbTypes.LineGeometry:
        return False

    # Get the line's vertices
    segment_vertices = segment.vertices()

    # Iterate through features in the reference layer
    for reference_feature in reference_layer.getFeatures():
        reference_geom = reference_feature.geometry()

        # Check if geometries are of similar type
        if reference_geom.type() != QgsWkbTypes.LineGeometry:
            continue

        # Get reference line vertices
        reference_vertices = reference_geom.vertices()

        # Compare vertex counts (quick initial check)
        if abs(len(list(segment_vertices)) - len(list(reference_vertices))) > 1:
            continue

        # Comprehensive similarity check
        is_similar = _compare_line_vertices(segment, reference_geom, tolerance)

        if is_similar:
            return True

    return False


def _compare_line_vertices(line1, line2, tolerance=0.001):
    """
    Detailed comparison of line vertices with tolerance.

    :param line1: First line geometry
    :param line2: Second line geometry
    :param tolerance: Spatial tolerance for coordinate comparisons
    :return: Boolean indicating if lines are similar
    """
    # Convert vertices to lists
    vertices1 = [v for v in line1.vertices()]
    vertices2 = [v for v in line2.vertices()]

    # Check if vertex counts are close
    if abs(len(vertices1) - len(vertices2)) > 1:
        return False

    # Try forward and reverse matching
    def _match_vertices(v1_list, v2_list, tolerance):
        for i in range(len(v1_list)):
            # Check if all vertices match within tolerance
            if all(
                v1.distance(v2) <= tolerance
                for v1, v2 in zip(v1_list[i:] + v1_list[:i], v2_list)
            ):
                return True
        return False

    # Check forward and reverse directions
    return _match_vertices(vertices1, vertices2, tolerance) or _match_vertices(
        vertices1[::-1], vertices2, tolerance
    )


# Example usage in a QGIS plugin method
def check_line_overlap(self, segment, reference_layer):
    """
    Check if a line segment overlaps with lines in a reference layer.

    :param segment: QgsGeometry of the line segment
    :param reference_layer: QgsVectorLayer containing reference lines
    :return: Boolean indicating overlap or similarity
    """
    try:
        # Use the similarity check method
        is_similar = check_line_similarity(
            segment,
            reference_layer,
            tolerance=0.001,  # Adjust tolerance as needed
        )

        return is_similar

    except Exception as e:
        # Log or handle any errors
        QgsMessageLog.logMessage(
            f"Error in line overlap check: {str(e)}",
            "LineComparisonPlugin",
            Qgis.Warning,
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
