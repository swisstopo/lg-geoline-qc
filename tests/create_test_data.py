"""
Script to create test data for GeoLines QC tests
"""

from qgis.core import (
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
)
import os


def create_simple_test_data(output_dir):
    """Create simple test data files"""

    # Create input layer - a long straight line
    input_layer = QgsVectorLayer("LineString?crs=EPSG:2056", "input", "memory")
    input_provider = input_layer.dataProvider()

    feat = QgsFeature()
    feat.setGeometry(
        QgsGeometry.fromPolylineXY(
            [
                QgsPointXY(2600000, 1200000),
                QgsPointXY(2605000, 1200000),  # 5km line
            ]
        )
    )
    input_provider.addFeatures([feat])

    # Save input layer
    QgsVectorFileWriter.writeAsVectorFormat(
        input_layer,
        os.path.join(output_dir, "input_test_line.geojson"),
        "UTF-8",
        QgsCoordinateReferenceSystem("EPSG:2056"),
        "GeoJSON",
    )

    # Create reference layer - perpendicular lines at intervals
    ref_layer = QgsVectorLayer("LineString?crs=EPSG:2056", "reference", "memory")
    ref_provider = ref_layer.dataProvider()

    for x in range(2600500, 2605000, 500):
        feat = QgsFeature()
        feat.setGeometry(
            QgsGeometry.fromPolylineXY([QgsPointXY(x, 1199900), QgsPointXY(x, 1200100)])
        )
        ref_provider.addFeatures([feat])

    # Save reference layer
    QgsVectorFileWriter.writeAsVectorFormat(
        ref_layer,
        os.path.join(output_dir, "reference_test_line.geojson"),
        "UTF-8",
        QgsCoordinateReferenceSystem("EPSG:2056"),
        "GeoJSON",
    )

    print(f"Test data created in {output_dir}")


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(output_dir, exist_ok=True)
    create_simple_test_data(output_dir)
