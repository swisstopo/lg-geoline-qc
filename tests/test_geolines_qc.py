# tests/test_geolines_qc.py
"""
Tests for GeoLines QC plugin with visualization
"""

import os
import sys
import matplotlib.pyplot as plt
import warnings

from processing.core.Processing import Processing
from qgis import processing

from matplotlib.collections import LineCollection
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant
from qgis.testing import start_app, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Initialize QGIS application FIRST
QGIS_APP = start_app()


def create_intersects_field():
    """
    Create the intersects Boolean field - compatible across QGIS versions

    Supports:
    - QGIS 3.34 (GitHub Actions CI)
    - QGIS 3.40 (Bratislava)
    - QGIS 3.42+ (Münster)
    """
    qgis_version = Qgis.versionInt()

    if qgis_version >= 34000:  # QGIS 3.40+
        try:
            from qgis.PyQt.QtCore import QMetaType
            field = QgsField(name="intersects", type=QMetaType.Type.Bool, typeName="Bool")
            return field
        except (ImportError, AttributeError, TypeError):
            pass  # Fall through to legacy API

    # Legacy API for QGIS 3.34 and fallback
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        field = QgsField("intersects", QVariant.Bool)
        return field


class TestGeoLinesQC(unittest.TestCase):
    """Test suite for GeoLines QC plugin"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures used by all tests"""
        # Initialize Processing framework
        Processing.initialize()

        cls.test_data_dir = os.path.join(os.path.dirname(__file__), "data")
        cls.plots_dir = os.path.join(os.path.dirname(__file__), "plots")
        os.makedirs(cls.plots_dir, exist_ok=True)

        cls.crs = QgsCoordinateReferenceSystem("EPSG:2056")

        print("\n" + "=" * 60)
        print("QGIS Processing Framework Initialized")
        print(f"Test plots will be saved to: {cls.plots_dir}")
        print("=" * 60)

    def setUp(self):
        """Set up before each test"""
        QgsProject.instance().removeAllMapLayers()

    def tearDown(self):
        """Clean up after each test"""
        QgsProject.instance().removeAllMapLayers()

    # ===== BASIC TESTS =====

    def test_simple_intersection_all_within_buffer(self):
        """Test 1: All input lines should be within buffer"""
        # Create input: horizontal line
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(2600000, 1200000),
                        QgsPointXY(2601000, 1200000),  # 1km line
                    ]
                )
            ],
        )

        # Create reference: same line (should be 100% within buffer)
        reference_layer = self.create_line_layer(
            "reference",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2601000, 1200000)]
                )
            ],
        )

        buffer_distance = 100.0

        # Run analysis
        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_01_all_within_buffer.png",
            "Test 1: All Lines Within Buffer\n(Input overlaps reference perfectly)",
        )

        # Check that intersects field exists
        self.assertIn("intersects", [f.name() for f in result_layer.fields()])

        # All features should have intersects=True
        for feature in result_layer.getFeatures():
            self.assertTrue(
                feature["intersects"], "Feature should intersect (line is on reference)"
            )

    def test_simple_intersection_all_outside_buffer(self):
        """Test 2: All input lines should be outside buffer"""
        # Create input: line at y=0
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2601000, 1200000)]
                )
            ],
        )

        # Create reference: line far away at y=2000
        reference_layer = self.create_line_layer(
            "reference",
            [
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(2600000, 1202000),  # 2km away
                        QgsPointXY(2601000, 1202000),
                    ]
                )
            ],
        )

        buffer_distance = 100.0  # Only 100m buffer, too small

        # Run analysis
        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_02_all_outside_buffer.png",
            "Test 2: All Lines Outside Buffer\n(Input is 2km away from reference)",
        )

        # All features should have intersects=False
        for feature in result_layer.getFeatures():
            self.assertFalse(
                feature["intersects"],
                "Feature should NOT intersect (line is too far from reference)",
            )

    def test_intersects_field_type(self):
        """Test 3: Verify intersects field has correct type"""
        input_layer, reference_layer = self.create_simple_test_layers()

        result_layer = self.run_analysis_sync(input_layer, reference_layer, 100.0)

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            100.0,
            "test_03_field_type_check.png",
            "Test 3: Field Type Verification\n(Checking intersects field is Boolean)",
        )

        # Check field exists
        fields = result_layer.fields()
        field_names = [field.name() for field in fields]
        self.assertIn("intersects", field_names)

        # Check field type is Boolean
        intersects_field = fields.field("intersects")
        self.assertEqual(
            intersects_field.type(),
            QVariant.Bool,
            "intersects field should be Boolean type",
        )

    def test_mixed_intersection(self):
        """Test 4: Some segments within, some outside buffer"""
        # Create input: long horizontal line
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(2600000, 1200000),
                        QgsPointXY(2601000, 1200000),  # 1km line
                    ]
                )
            ],
        )

        # Create reference: short vertical line in the middle
        reference_layer = self.create_line_layer(
            "reference",
            [
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(2600500, 1199950),  # Middle of input line
                        QgsPointXY(2600500, 1200050),
                    ]
                )
            ],
        )

        buffer_distance = 100.0

        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Should have both True and False values
        true_count = sum(1 for f in result_layer.getFeatures() if f["intersects"])
        false_count = sum(1 for f in result_layer.getFeatures() if not f["intersects"])

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_04_mixed_intersection.png",
            f"Test 4: Mixed Intersection\n({true_count} within buffer, {false_count} outside)",
        )

        self.assertGreater(true_count, 0, "Should have some intersecting segments")
        self.assertGreater(false_count, 0, "Should have some non-intersecting segments")

        print(f"\nMixed intersection: {true_count} within, {false_count} outside")

    # ===== COMPLEX TESTS =====

    def test_buffer_distance_accuracy(self):
        """Test 5: Verify buffer distance is accurate"""
        # Create input: horizontal line at y=0
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2600500, 1200000)]
                )
            ],
        )

        # Test multiple buffer distances
        test_cases = [
            (1200050, 100.0, True, "50m away"),
            (1200100, 100.0, True, "100m away (boundary)"),
            (1200150, 100.0, False, "150m away"),
        ]

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle("Test 5: Buffer Distance Accuracy", fontsize=16, fontweight="bold")

        for idx, (ref_y, buffer_distance, expected_intersect, description) in enumerate(
            test_cases
        ):
            # Create reference at specific distance
            reference_layer = self.create_line_layer(
                "reference",
                [
                    QgsGeometry.fromPolylineXY(
                        [QgsPointXY(2600000, ref_y), QgsPointXY(2600500, ref_y)]
                    )
                ],
            )

            result_layer = self.run_analysis_sync(
                input_layer, reference_layer, buffer_distance
            )

            # Plot on subplot
            ax = axes[idx]
            self.plot_on_axis(
                ax,
                input_layer,
                reference_layer,
                result_layer,
                buffer_distance,
                f"{description}\nExpected: {'Within' if expected_intersect else 'Outside'}",
            )

            # Check if result matches expectation
            has_intersecting = any(f["intersects"] for f in result_layer.getFeatures())

            self.assertEqual(
                has_intersecting,
                expected_intersect,
                f"{description}: expected={expected_intersect}, got={has_intersecting}",
            )

        plt.tight_layout()
        plt.savefig(
            os.path.join(self.plots_dir, "test_05_buffer_accuracy.png"),
            dpi=150,
            bbox_inches="tight",
        )
        plt.close()

    def test_multiple_reference_features(self):
        """Test 6: Multiple reference features"""
        # Create input: long line
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(2600000, 1200000),
                        QgsPointXY(2602000, 1200000),  # 2km line
                    ]
                )
            ],
        )

        # Create multiple reference features
        reference_layer = self.create_line_layer(
            "reference",
            [
                # Three perpendicular lines at different positions
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600500, 1199950), QgsPointXY(2600500, 1200050)]
                ),
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2601000, 1199950), QgsPointXY(2601000, 1200050)]
                ),
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2601500, 1199950), QgsPointXY(2601500, 1200050)]
                ),
            ],
        )

        buffer_distance = 100.0

        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Should have segments near each reference
        intersecting_segments = [
            f for f in result_layer.getFeatures() if f["intersects"]
        ]
        non_intersecting_segments = [
            f for f in result_layer.getFeatures() if not f["intersects"]
        ]

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_06_multiple_references.png",
            f"Test 6: Multiple Reference Features\n({len(intersecting_segments)} within, {len(non_intersecting_segments)} outside)",
        )

        self.assertGreater(
            len(intersecting_segments),
            0,
            "Should have intersecting segments near the 3 reference lines",
        )

        self.assertGreater(
            len(non_intersecting_segments),
            0,
            "Should have non-intersecting segments between reference lines",
        )

        print(
            f"\nMultiple references: {len(intersecting_segments)} within, "
            f"{len(non_intersecting_segments)} outside"
        )

    def test_statistics_calculation(self):
        """Test 7: Verify statistics match expectations"""
        input_layer, reference_layer = self.create_simple_test_layers()
        buffer_distance = 100.0

        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Calculate statistics
        total_count = result_layer.featureCount()
        within_count = sum(1 for f in result_layer.getFeatures() if f["intersects"])
        outside_count = total_count - within_count

        # Calculate lengths
        within_length = sum(
            f.geometry().length() for f in result_layer.getFeatures() if f["intersects"]
        )
        outside_length = sum(
            f.geometry().length()
            for f in result_layer.getFeatures()
            if not f["intersects"]
        )
        total_length = within_length + outside_length

        # Quality score
        quality_score = (within_length / total_length * 100) if total_length > 0 else 0

        # Create visualization with statistics
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))

        self.plot_on_axis(
            ax,
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "Test 7: Statistics Calculation",
        )

        # Add statistics text box
        stats_text = f"""Statistics:
Total: {total_count} features, {total_length:.1f}m
Within buffer: {within_count} features, {within_length:.1f}m
Outside buffer: {outside_count} features, {outside_length:.1f}m
Quality score: {quality_score:.1f}%"""

        ax.text(
            0.02,
            0.98,
            stats_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8),
        )

        plt.tight_layout()
        plt.savefig(
            os.path.join(self.plots_dir, "test_07_statistics.png"),
            dpi=150,
            bbox_inches="tight",
        )
        plt.close()

        # Verify totals make sense
        self.assertEqual(total_count, within_count + outside_count)
        self.assertAlmostEqual(total_length, within_length + outside_length, places=2)

        print("\nStatistics:")
        print(f"  Total: {total_count} features, {total_length:.2f}m")
        print(f"  Within: {within_count} features, {within_length:.2f}m")
        print(f"  Outside: {outside_count} features, {outside_length:.2f}m")
        print(f"  Quality score: {quality_score:.1f}%")

        # Basic sanity checks
        self.assertGreater(total_count, 0)
        self.assertGreater(total_length, 0)

    @unittest.skip("Skipping for now...")
    def test_intersects_true_positions(self):
        """Test 8: Verify True values are at correct positions"""
        # Create input: horizontal line from x=0 to x=1000
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2601000, 1200000)]
                )
            ],
        )

        # Create reference: vertical line at x=500
        reference_layer = self.create_line_layer(
            "reference",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600500, 1199900), QgsPointXY(2600500, 1200100)]
                )
            ],
        )

        buffer_distance = 100.0

        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_08_true_positions.png",
            "Test 8: Verify TRUE Values at Correct Positions\n(Reference crosses input at midpoint)",
        )

        # Analyze positions
        for feature in result_layer.getFeatures():
            geom = feature.geometry()
            centroid = geom.centroid().asPoint()
            intersects = feature["intersects"]

            # Distance from centroid to reference line (at x=2600500)
            distance_to_ref = abs(centroid.x() - 2600500)

            if distance_to_ref <= buffer_distance:
                self.assertTrue(
                    intersects,
                    f"Feature at x={centroid.x():.1f} (distance={distance_to_ref:.1f}m) "
                    f"should intersect",
                )
            else:
                self.assertFalse(
                    intersects,
                    f"Feature at x={centroid.x():.1f} (distance={distance_to_ref:.1f}m) "
                    f"should NOT intersect",
                )

    def test_intersects_false_positions(self):
        """Test 9: Verify False values are at correct positions"""
        # Create input crossing a reference
        input_layer = self.create_line_layer(
            "input",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2601000, 1200000)]
                )
            ],
        )

        # Reference at x=500 (middle)
        reference_layer = self.create_line_layer(
            "reference",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600500, 1199900), QgsPointXY(2600500, 1200100)]
                )
            ],
        )

        buffer_distance = 50.0  # Small buffer

        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        # Create visualization
        self.plot_test_scenario(
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "test_09_false_positions.png",
            "Test 9: Verify FALSE Values at Correct Positions\n(Small 50m buffer - ends should be outside)",
        )

        # Get segments far from reference (at the ends)
        far_segments = [
            f
            for f in result_layer.getFeatures()
            if abs(f.geometry().centroid().asPoint().x() - 2600500) > 200
        ]

        # These should all be False
        for feature in far_segments:
            self.assertFalse(
                feature["intersects"],
                "Segment far from reference should not intersect",
            )

    # @unittest.skip("Real world data are too complexe for now...")
    # The test assertion is very picky, generate the result data with `generate_expected_ouput.py`
    # Alternatively, we may use a more lenient way to compare lines (i.e. only the length)
    def test_real_world_data(self):
        """Test 10: Real-world data validation"""
        # Check if test data files exist
        test_files = {
            "input": "test_lines.geojson",
            "reference": "reference_lines.geojson",
            "expected": "result_lines.geojson",
        }

        for key, filename in test_files.items():
            filepath = os.path.join(self.test_data_dir, filename)
            if not os.path.exists(filepath):
                self.skipTest(
                    f"Real-world test data not found: {filename}\n"
                    f"Please add the file to: {self.test_data_dir}"
                )

        # Load the real-world data
        print("\n" + "=" * 60)
        print("Loading real-world test data...")
        print("=" * 60)

        input_layer = self.load_test_layer("test_lines.geojson")
        reference_layer = self.load_test_layer("reference_lines.geojson")
        expected_layer = self.load_test_layer("result_lines.geojson")

        print(f"✓ Input layer: {input_layer.featureCount()} features")
        print(f"✓ Reference layer: {reference_layer.featureCount()} features")
        print(f"✓ Expected output: {expected_layer.featureCount()} features")

        # Determine buffer distance from expected results
        # (or use a default if not determinable)
        buffer_distance = 100.0  # Default

        # Try to infer buffer distance from the data if possible
        # This is optional - you can hardcode it if you know it

        print(f"✓ Using buffer distance: {buffer_distance}m")

        # Run the analysis
        print("\nRunning analysis on real-world data...")
        result_layer = self.run_analysis_sync(
            input_layer, reference_layer, buffer_distance
        )

        print(f"✓ Analysis complete: {result_layer.featureCount()} result features")

        # Calculate statistics for both expected and actual
        expected_stats = self.calculate_layer_stats(expected_layer)
        result_stats = self.calculate_layer_stats(result_layer)

        print("\n" + "=" * 60)
        print("COMPARISON: Expected vs Actual")
        print("=" * 60)
        print(
            f"Feature count - Expected: {expected_stats['total']}, Actual: {result_stats['total']}"
        )
        print(
            f"Within buffer - Expected: {expected_stats['within']}, Actual: {result_stats['within']}"
        )
        print(
            f"Outside buffer - Expected: {expected_stats['outside']}, Actual: {result_stats['outside']}"
        )
        print(
            f"Total length - Expected: {expected_stats['total_length']:.1f}m, Actual: {result_stats['total_length']:.1f}m"
        )
        print(
            f"Quality score - Expected: {expected_stats['quality_score']:.1f}%, Actual: {result_stats['quality_score']:.1f}%"
        )
        print("=" * 60)

        # Create comprehensive visualization
        self.plot_real_world_comparison(
            input_layer,
            reference_layer,
            result_layer,
            expected_layer,
            buffer_distance,
            result_stats,
            expected_stats,
        )

        # Perform assertions
        # Allow some tolerance for floating point differences
        self.assertEqual(
            result_stats["total"],
            expected_stats["total"],
            "Feature count should match expected output",
        )

        # Check that the split between within/outside is similar
        # (allow small differences due to processing variations)
        within_diff = abs(result_stats["within"] - expected_stats["within"])
        self.assertLess(
            within_diff,
            max(2, expected_stats["total"] * 0.05),  # Allow 5% difference or 2 features
            f"Within buffer count differs by {within_diff} features",
        )

        # Check total length is similar (allow 1% difference)
        length_ratio = result_stats["total_length"] / expected_stats["total_length"]
        self.assertAlmostEqual(
            length_ratio,
            1.0,
            delta=0.01,
            msg=f"Total length differs significantly (ratio={length_ratio:.3f})",
        )

        print("\n✅ Real-world data test passed!")

    def calculate_layer_stats(self, layer):
        """Calculate statistics for a layer"""
        total_count = layer.featureCount()

        # Check if intersects field exists
        if "intersects" not in [f.name() for f in layer.fields()]:
            return {
                "total": total_count,
                "within": 0,
                "outside": 0,
                "total_length": sum(f.geometry().length() for f in layer.getFeatures()),
                "within_length": 0,
                "outside_length": 0,
                "quality_score": 0,
            }

        within_count = sum(1 for f in layer.getFeatures() if f["intersects"])
        outside_count = total_count - within_count

        within_length = sum(
            f.geometry().length() for f in layer.getFeatures() if f["intersects"]
        )
        outside_length = sum(
            f.geometry().length() for f in layer.getFeatures() if not f["intersects"]
        )
        total_length = within_length + outside_length

        quality_score = (within_length / total_length * 100) if total_length > 0 else 0

        return {
            "total": total_count,
            "within": within_count,
            "outside": outside_count,
            "total_length": total_length,
            "within_length": within_length,
            "outside_length": outside_length,
            "quality_score": quality_score,
        }

    def plot_real_world_comparison(
        self,
        input_layer,
        reference_layer,
        result_layer,
        expected_layer,
        buffer_distance,
        result_stats,
        expected_stats,
    ):
        """Create a comprehensive plot for real-world data comparison"""

        # Create figure with two subplots
        fig = plt.figure(figsize=(20, 10))
        gs = fig.add_gridspec(
            2, 2, width_ratios=[2, 1], height_ratios=[1, 1], hspace=0.3, wspace=0.3
        )

        # Main plot (top, spanning both columns)
        ax_main = fig.add_subplot(gs[0, :])

        # Expected output (bottom left)
        ax_expected = fig.add_subplot(gs[1, 0])

        # Statistics (bottom right)
        ax_stats = fig.add_subplot(gs[1, 1])
        ax_stats.axis("off")

        # ===== MAIN PLOT: Actual Results =====
        self.plot_on_axis(
            ax_main,
            input_layer,
            reference_layer,
            result_layer,
            buffer_distance,
            "Test 10: Real-World Data Analysis\n(Actual Results)",
        )

        # Calculate and display extent
        extent = self.calculate_layer_extent(
            [input_layer, reference_layer, result_layer]
        )
        if extent:
            ax_main.set_xlim(extent[0] - 50, extent[1] + 50)
            ax_main.set_ylim(extent[2] - 50, extent[3] + 50)

        # ===== EXPECTED OUTPUT PLOT =====
        self.plot_on_axis(
            ax_expected,
            input_layer,
            reference_layer,
            expected_layer,
            buffer_distance,
            "Expected Results\n(for comparison)",
        )

        if extent:
            ax_expected.set_xlim(extent[0] - 50, extent[1] + 50)
            ax_expected.set_ylim(extent[2] - 50, extent[3] + 50)

        # ===== STATISTICS TABLE =====
        stats_text = self.create_stats_comparison_text(result_stats, expected_stats)

        ax_stats.text(
            0.1,
            0.9,
            "▇▆▅▂ STATISTICS COMPARISON",
            transform=ax_stats.transAxes,
            fontsize=14,
            fontweight="bold",
            verticalalignment="top",
        )

        ax_stats.text(
            0.1,
            0.8,
            stats_text,
            transform=ax_stats.transAxes,
            fontsize=10,
            verticalalignment="top",
            fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8),
        )

        # Add match indicator
        match_indicator = self.check_results_match(result_stats, expected_stats)
        match_color = "green" if match_indicator["match"] else "orange"
        match_symbol = "✓" if match_indicator["match"] else "⚠"

        ax_stats.text(
            0.1,
            0.15,
            f"{match_symbol} Overall Match: {match_indicator['message']}",
            transform=ax_stats.transAxes,
            fontsize=11,
            fontweight="bold",
            color=match_color,
            verticalalignment="top",
            bbox=dict(
                boxstyle="round", facecolor="white", edgecolor=match_color, linewidth=2
            ),
        )

        # Add coordinate system info
        crs_info = f"CRS: {input_layer.crs().authid()}"
        ax_stats.text(
            0.1,
            0.05,
            crs_info,
            transform=ax_stats.transAxes,
            fontsize=9,
            style="italic",
            color="gray",
        )

        # Save the plot
        plt.savefig(
            os.path.join(self.plots_dir, "test_10_real_world_data.png"),
            dpi=150,
            bbox_inches="tight",
        )
        plt.close()

        print("  ▇▆▅▂ Plot saved: test_10_real_world_data.png")

    def create_stats_comparison_text(self, result_stats, expected_stats):
        """Create formatted statistics comparison text"""

        def format_diff(actual, expected):
            diff = actual - expected
            if diff == 0:
                return "✓"
            elif abs(diff) < max(2, expected * 0.05):
                return f"~{diff:+d}"
            else:
                return f"× {diff:+d}"

        def format_length_diff(actual, expected):
            diff = actual - expected
            if abs(diff) < 1:
                return "✓"
            elif abs(diff) < expected * 0.01:
                return f"~{diff:+.1f}m"
            else:
                return f"× {diff:+.1f}m"

        text = f"""
    ┌─────────────────────────────────────┐
    │ Metric          Expected   Actual   │
    ├─────────────────────────────────────┤
    │ Total features  {expected_stats["total"]:6d}     {result_stats["total"]:6d}   │
    │                            {format_diff(result_stats["total"], expected_stats["total"]):>6s} │
    │                                     │
    │ Within buffer   {expected_stats["within"]:6d}     {result_stats["within"]:6d}   │
    │                            {format_diff(result_stats["within"], expected_stats["within"]):>6s} │
    │                                     │
    │ Outside buffer  {expected_stats["outside"]:6d}     {result_stats["outside"]:6d}   │
    │                            {format_diff(result_stats["outside"], expected_stats["outside"]):>6s} │
    │                                     │
    │ Total length    {expected_stats["total_length"]:6.0f}m    {result_stats["total_length"]:6.0f}m  │
    │                            {format_length_diff(result_stats["total_length"], expected_stats["total_length"]):>6s} │
    │                                     │
    │ Quality score   {expected_stats["quality_score"]:5.1f}%     {result_stats["quality_score"]:5.1f}%  │
    └─────────────────────────────────────┘

    Legend: ✓ = match, ~ = close, × = diff
    """
        return text

    def check_results_match(self, result_stats, expected_stats):
        """Check if results match expectations"""

        # Check feature count
        if result_stats["total"] != expected_stats["total"]:
            return {"match": False, "message": "Feature count mismatch"}

        # Check within/outside split (allow 5% tolerance)
        within_diff = abs(result_stats["within"] - expected_stats["within"])
        tolerance = max(2, expected_stats["total"] * 0.05)

        if within_diff > tolerance:
            return {
                "match": False,
                "message": f"Within/outside split differs by {within_diff} features",
            }

        # Check total length (allow 1% tolerance)
        length_diff_pct = (
            abs(result_stats["total_length"] - expected_stats["total_length"])
            / expected_stats["total_length"]
            * 100
        )

        if length_diff_pct > 1.0:
            return {
                "match": False,
                "message": f"Length differs by {length_diff_pct:.1f}%",
            }

        # Everything matches!
        return {"match": True, "message": "Results match expected output"}

    def calculate_layer_extent(self, layers):
        """Calculate the combined extent of multiple layers"""
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")

        for layer in layers:
            extent = layer.extent()
            min_x = min(min_x, extent.xMinimum())
            max_x = max(max_x, extent.xMaximum())
            min_y = min(min_y, extent.yMinimum())
            max_y = max(max_y, extent.yMaximum())

        if min_x == float("inf"):
            return None

        return (min_x, max_x, min_y, max_y)

    # ===== HELPER METHODS =====

    def create_line_layer(self, name, geometries, crs="EPSG:2056"):
        """Create a memory line layer with given geometries"""
        layer = QgsVectorLayer(f"LineString?crs={crs}", name, "memory")
        provider = layer.dataProvider()

        features = []
        for geom in geometries:
            feature = QgsFeature()
            feature.setGeometry(geom)
            features.append(feature)

        provider.addFeatures(features)
        layer.updateExtents()

        return layer

    def create_simple_test_layers(self):
        """Create simple test layers for quick testing"""
        # Input: horizontal line
        input_layer = self.create_line_layer(
            "test_input",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600000, 1200000), QgsPointXY(2601000, 1200000)]
                )
            ],
        )

        # Reference: vertical line at midpoint
        reference_layer = self.create_line_layer(
            "test_reference",
            [
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(2600500, 1199950), QgsPointXY(2600500, 1200050)]
                )
            ],
        )

        return input_layer, reference_layer

    def run_analysis_sync(
        self, input_layer, reference_layer, buffer_distance, region_layer=None
    ):
        """
        Run the analysis synchronously (blocking) for testing
        This mimics what QCAnalysisTask.run() does
        """
        # Step 1: Buffer the reference layer
        buffer_params = {
            "INPUT": reference_layer,
            "DISTANCE": buffer_distance,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,  # Round
            "JOIN_STYLE": 0,  # Round
            "MITER_LIMIT": 2,
            "DISSOLVE": True,
            "OUTPUT": "memory:",
        }
        buffer_result = processing.run("native:buffer", buffer_params)
        buffered_reference = buffer_result["OUTPUT"]

        # Step 2: Get lines WITHIN buffer (intersects = True)
        intersect_params = {
            "INPUT": input_layer,
            "OVERLAY": buffered_reference,
            "OUTPUT": "memory:",
        }
        intersect_result = processing.run("native:intersection", intersect_params)
        lines_within = intersect_result["OUTPUT"]

        # Step 3: Get lines OUTSIDE buffer (intersects = False)
        difference_params = {
            "INPUT": input_layer,
            "OVERLAY": buffered_reference,
            "OUTPUT": "memory:",
        }
        difference_result = processing.run("native:difference", difference_params)
        lines_outside = difference_result["OUTPUT"]

        # Step 4: Add 'intersects' field to both
        lines_within.dataProvider().addAttributes([create_intersects_field()])
        lines_within.updateFields()
        lines_within.startEditing()
        for feature in lines_within.getFeatures():
            lines_within.changeAttributeValue(
                feature.id(), lines_within.fields().indexFromName("intersects"), True
            )
        lines_within.commitChanges()

        lines_outside.dataProvider().addAttributes([create_intersects_field()])
        lines_outside.updateFields()
        lines_outside.startEditing()
        for feature in lines_outside.getFeatures():
            lines_outside.changeAttributeValue(
                feature.id(), lines_outside.fields().indexFromName("intersects"), False
            )
        lines_outside.commitChanges()

        # Step 5: Merge the two layers
        merge_params = {
            "LAYERS": [lines_within, lines_outside],
            "CRS": input_layer.crs(),
            "OUTPUT": "memory:",
        }
        merge_result = processing.run("native:mergevectorlayers", merge_params)
        result_layer = merge_result["OUTPUT"]

        return result_layer

    def load_test_layer(self, filename):
        """Load a test layer from file"""
        path = os.path.join(self.test_data_dir, filename)
        layer = QgsVectorLayer(path, os.path.basename(filename), "ogr")

        if not layer.isValid():
            raise ValueError(f"Failed to load test layer: {path}")

        return layer

    def compare_layers(self, output_layer, expected_layer, tolerance=1.0):
        """Compare two layers feature by feature"""
        # Check feature counts
        self.assertEqual(
            output_layer.featureCount(),
            expected_layer.featureCount(),
            "Feature count mismatch",
        )

        # Get features sorted by geometry
        output_features = sorted(
            output_layer.getFeatures(),
            key=lambda f: (
                f.geometry().centroid().asPoint().x(),
                f.geometry().centroid().asPoint().y(),
            ),
        )
        expected_features = sorted(
            expected_layer.getFeatures(),
            key=lambda f: (
                f.geometry().centroid().asPoint().x(),
                f.geometry().centroid().asPoint().y(),
            ),
        )

        # Compare each feature
        for i, (out_feat, exp_feat) in enumerate(
            zip(output_features, expected_features)
        ):
            # Compare geometries
            out_length = out_feat.geometry().length()
            exp_length = exp_feat.geometry().length()

            self.assertAlmostEqual(
                out_length,
                exp_length,
                delta=tolerance,
                msg=f"Feature {i}: geometry length mismatch",
            )

            # Compare intersects attribute
            out_intersects = out_feat["intersects"]
            exp_intersects = exp_feat["intersects"]

            self.assertEqual(
                out_intersects,
                exp_intersects,
                f"Feature {i}: intersects attribute mismatch "
                f"(expected={exp_intersects}, got={out_intersects})",
            )

    # ===== VISUALIZATION METHODS =====

    def plot_test_scenario(
        self,
        input_layer,
        reference_layer,
        result_layer,
        buffer_distance,
        filename,
        title,
    ):
        """Create a plot showing the test scenario"""
        fig, ax = plt.subplots(figsize=(12, 8))

        self.plot_on_axis(
            ax, input_layer, reference_layer, result_layer, buffer_distance, title
        )

        plt.tight_layout()
        plt.savefig(
            os.path.join(self.plots_dir, filename), dpi=150, bbox_inches="tight"
        )
        plt.close()

        print(f"  ▇▆▅▂ Plot saved: {filename}")

    def plot_on_axis(
        self, ax, input_layer, reference_layer, result_layer, buffer_distance, title
    ):
        """Plot layers on a given matplotlib axis"""

        # 1. Plot buffer zone (semi-transparent)
        self.plot_buffer(ax, reference_layer, buffer_distance)

        # 2. Plot reference lines (thick blue)
        self.plot_layer(
            ax,
            reference_layer,
            color="blue",
            linewidth=3,
            label="Reference Line",
            linestyle="-",
            zorder=3,
        )

        # 3. Plot result lines (color-coded by intersects)
        self.plot_result_layer(ax, result_layer)

        # 4. Plot original input (thin gray, dashed, for reference)
        self.plot_layer(
            ax,
            input_layer,
            color="gray",
            linewidth=1,
            label="Original Input",
            linestyle="--",
            alpha=0.5,
            zorder=1,
        )

        # Set title and labels
        ax.set_title(title, fontsize=14, fontweight="bold", pad=20)
        ax.set_xlabel("X Coordinate (EPSG:2056)", fontsize=10)
        ax.set_ylabel("Y Coordinate (EPSG:2056)", fontsize=10)

        # Add grid
        ax.grid(True, alpha=0.3, linestyle=":", linewidth=0.5)

        # Equal aspect ratio
        ax.set_aspect("equal")

        # Legend
        ax.legend(loc="best", fontsize=9, framealpha=0.9)

        # Add buffer distance annotation
        ax.text(
            0.02,
            0.02,
            f"Buffer: {buffer_distance}m",
            transform=ax.transAxes,
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.7),
        )

    def plot_layer(
        self,
        ax,
        layer,
        color="black",
        linewidth=2,
        label=None,
        linestyle="-",
        alpha=1.0,
        zorder=2,
    ):
        """Plot a vector layer as lines"""
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                for line in lines:
                    coords = [(pt.x(), pt.y()) for pt in line]
                    xs, ys = zip(*coords)
                    ax.plot(
                        xs,
                        ys,
                        color=color,
                        linewidth=linewidth,
                        linestyle=linestyle,
                        alpha=alpha,
                        zorder=zorder,
                    )
            else:
                line = geom.asPolyline()
                coords = [(pt.x(), pt.y()) for pt in line]
                xs, ys = zip(*coords)
                ax.plot(
                    xs,
                    ys,
                    color=color,
                    linewidth=linewidth,
                    label=label,
                    linestyle=linestyle,
                    alpha=alpha,
                    zorder=zorder,
                )
                label = None  # Only label once

    def plot_result_layer(self, ax, result_layer):
        """Plot result layer with color coding based on intersects field"""
        within_lines = []
        outside_lines = []

        for feature in result_layer.getFeatures():
            geom = feature.geometry()
            intersects = feature["intersects"]

            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                for line in lines:
                    coords = [(pt.x(), pt.y()) for pt in line]
                    if intersects:
                        within_lines.append(coords)
                    else:
                        outside_lines.append(coords)
            else:
                line = geom.asPolyline()
                coords = [(pt.x(), pt.y()) for pt in line]
                if intersects:
                    within_lines.append(coords)
                else:
                    outside_lines.append(coords)

        # Plot within buffer (green)
        if within_lines:
            lc_within = LineCollection(
                within_lines,
                colors="green",
                linewidths=2.5,
                label="Within Buffer (intersects=True)",
                zorder=4,
            )
            ax.add_collection(lc_within)

        # Plot outside buffer (red)
        if outside_lines:
            lc_outside = LineCollection(
                outside_lines,
                colors="red",
                linewidths=2.5,
                label="Outside Buffer (intersects=False)",
                zorder=4,
            )
            ax.add_collection(lc_outside)

    def plot_buffer(self, ax, reference_layer, buffer_distance):
        """Plot buffer zone around reference layer"""
        # Create buffer
        buffer_params = {
            "INPUT": reference_layer,
            "DISTANCE": buffer_distance,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "DISSOLVE": True,
            "OUTPUT": "memory:",
        }
        buffer_result = processing.run("native:buffer", buffer_params)
        buffer_layer = buffer_result["OUTPUT"]

        # Plot buffer as polygon
        for feature in buffer_layer.getFeatures():
            geom = feature.geometry()
            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
                for polygon in polygons:
                    for ring in polygon:
                        coords = [(pt.x(), pt.y()) for pt in ring]
                        xs, ys = zip(*coords)
                        ax.fill(
                            xs,
                            ys,
                            color="lightblue",
                            alpha=0.3,
                            label="Buffer Zone",
                            zorder=2,
                        )
            else:
                polygon = geom.asPolygon()
                for ring in polygon:
                    coords = [(pt.x(), pt.y()) for pt in ring]
                    xs, ys = zip(*coords)
                    ax.fill(
                        xs,
                        ys,
                        color="lightblue",
                        alpha=0.3,
                        label="Buffer Zone",
                        zorder=2,
                    )


if __name__ == "__main__":
    unittest.main()
