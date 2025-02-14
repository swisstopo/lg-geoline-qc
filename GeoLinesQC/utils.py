from qgis.core import QgsProject
from qgis.utils import iface


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

