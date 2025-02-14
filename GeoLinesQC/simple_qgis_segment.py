from qgis.core import QgsGeometry, QgsPointXY, QgsProject, QgsFeature, QgsVectorLayer
from qgis.PyQt.QtCore import QVariant


from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsPoint,
    QgsProject,
    QgsFeature,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from qgis.core import QgsGeometry, QgsPoint, QgsProject, QgsFeature, QgsVectorLayer
from qgis.core import QgsSpatialIndex


def buffer_and_check_intersections(segment, reference_layer, buffer_distance):
    """
    Buffers a segment and checks if it intersects with any features in a reference layer.

    Args:
        segment (QgsGeometry): The segment to buffer.
        reference_layer (QgsVectorLayer): The reference layer to check for intersections.
        buffer_distance (float): The buffer distance.

    Returns:
        bool: True if the buffer intersects any features in the reference layer, False otherwise.
    """
    try:
        # Create a buffer around the segment
        segment_buffer = segment.buffer(
            buffer_distance, 5
        )  # 5 is the number of segments to approximate the buffer

        # Check for intersections with the reference layer
        for feature in reference_layer.getFeatures():
            reference_geometry = feature.geometry()
            if segment_buffer.intersects(reference_geometry):
                return True  # Intersection found

        return False  # No intersection found

    except Exception as e:
        print(f"Error: {e}")
        return False


def segment_line(line, segment_length):
    """
    Splits a line into segments of equal length using QGIS native functions.

    Args:
        line (QgsGeometry): The input line geometry.
        segment_length (float): The desired length of each segment.

    Returns:
        list: A list of QgsGeometry objects representing the segments.
    """
    try:
        # Extract vertices from the line
        vertices = line.asPolyline()  # Returns a list of QgsPointXY
        if len(vertices) < 2:
            print("Invalid line: Not enough vertices.")
            return [line]

        new_segments = []
        current_segment = [QgsPoint(vertices[0])]  # Convert QgsPointXY to QgsPoint
        accumulated_length = 0.0

        for i in range(1, len(vertices)):
            prev_point = QgsPoint(vertices[i - 1])  # Convert QgsPointXY to QgsPoint
            current_point = QgsPoint(vertices[i])  # Convert QgsPointXY to QgsPoint
            segment = QgsGeometry.fromPolyline([prev_point, current_point])
            segment_length_current = segment.length()

            while accumulated_length + segment_length_current >= segment_length:
                # Calculate the remaining length to reach the segment_length
                remaining_length = segment_length - accumulated_length
                cut_point = segment.interpolate(remaining_length).asPoint()

                # Add the cut point to the current segment
                current_segment.append(
                    QgsPoint(cut_point)
                )  # Convert QgsPointXY to QgsPoint
                new_segments.append(QgsGeometry.fromPolyline(current_segment))

                # Start a new segment from the cut point
                current_segment = [
                    QgsPoint(cut_point)
                ]  # Convert QgsPointXY to QgsPoint
                accumulated_length = 0.0

                # Update the segment with the remaining part after the cut
                segment = QgsGeometry.fromPolyline([QgsPoint(cut_point), current_point])
                segment_length_current = segment.length()

            # Add the current point to the segment
            current_segment.append(current_point)
            accumulated_length += segment_length_current

        # Add the last segment if it has more than one point
        if len(current_segment) > 1:
            new_segments.append(QgsGeometry.fromPolyline(current_segment))

        return new_segments

    except Exception as e:
        print(f"Error: {e}")
        return [line]


# Load the input line layer

# Load the input line layer and reference layer
input_layer = QgsProject.instance().mapLayersByName("line_segment")[0]
reference_layer = QgsProject.instance().mapLayersByName("ref_lines")[0]

# Create a new memory layer to store the segmented lines with intersection results
output_layer = QgsVectorLayer(
    "LineString?crs=" + input_layer.crs().authid(),
    "segmented_lines_with_intersections",
    "memory",
)
output_layer.dataProvider().addAttributes(
    [
        QgsField("id", QVariant.Int),
        QgsField(
            "intersects", QVariant.Bool
        ),  # Add a field to store intersection results
    ]
)
output_layer.updateFields()

# Segment each feature in the input layer
segment_length = 100.0  # Desired segment length
buffer_distance = 500.0  # Buffer distance for intersection check
for feature in input_layer.getFeatures():
    line_geometry = feature.geometry()
    segments = segment_line(line_geometry, segment_length)

    # Add each segment to the output layer with intersection results
    for segment in segments:
        new_feature = QgsFeature(output_layer.fields())
        new_feature.setGeometry(segment)

        # Check for intersections with the reference layer
        intersects = buffer_and_check_intersections(
            segment, reference_layer, buffer_distance
        )
        new_feature.setAttribute("intersects", intersects)

        output_layer.dataProvider().addFeature(new_feature)

# Add the output layer to the map
QgsProject.instance().addMapLayer(output_layer)
print("Segmentation and intersection check complete. Output layer added to the map.")
