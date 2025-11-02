# -*- coding: utf-8 -*-

import os
from datetime import datetime

from qgis import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsProcessingFeatureSourceDefinition,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsTask,
    QgsApplication,
    QgsWkbTypes,
    QgsSpatialIndex,
    QgsFeatureRequest,
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
DIALOG_WIDTH = 500
CHUNK_SIZE = 100  # Process features in chunks for better feedback


# Enable high DPI scaling
if hasattr(QApplication, "setAttribute"):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


class QCAnalysisTask(QgsTask):
    """Background task for running the QC analysis"""

    # Signals for progress updates
    progressChanged = pyqtSignal(str, int)  # message, progress value
    analysisComplete = pyqtSignal(object)  # Will emit the result layer
    analysisError = pyqtSignal(str)

    def __init__(
        self,
        description,
        input_layer,
        reference_layer,
        buffer_distance,
        region_layer=None,
        output_name="QC Result",
    ):
        super().__init__(description, QgsTask.CanCancel)
        self.input_layer = input_layer
        self.reference_layer = reference_layer
        self.buffer_distance = buffer_distance
        self.region_layer = region_layer
        self.output_name = output_name
        self.result_layer = None
        self.exception = None

        # Create processing context and feedback for background task
        self.context = QgsProcessingContext()
        self.context.setProject(QgsProject.instance())
        self.feedback = QgsProcessingFeedback()

    def cancel(self):
        """Override cancel to also cancel feedback"""
        self.feedback.cancel()
        super().cancel()

    def log(self, message, level=Qgis.Info, progress=None):
        """Log message to both QGIS log and emit signal for progress dialog"""
        QgsMessageLog.logMessage(message, "GeoLinesQC", level)
        if progress is not None:
            self.progressChanged.emit(message, progress)
            self.setProgress(progress)

    def run(self):
        """Execute the analysis in background"""
        try:
            self.log("Starting GeoLines QC analysis...", Qgis.Info, 0)

            # Step 1: Determine clipping strategy
            working_input = self.input_layer
            working_reference = self.reference_layer

            if self.region_layer:
                # Use regional filter
                working_input, working_reference = self._clip_to_region()
            else:
                # Use oriented bounding box optimization
                working_reference = self._clip_to_input_extent(working_reference)

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            input_count = working_input.featureCount()
            ref_count = working_reference.featureCount()
            self.log(
                f"Working with {input_count} input and {ref_count} reference features",
                Qgis.Info,
                35,
            )

            # Log optimization info
            if not self.region_layer:
                original_ref_count = self.reference_layer.featureCount()
                reduction_pct = (
                    (1 - ref_count / original_ref_count) * 100
                    if original_ref_count > 0
                    else 0
                )
                self.log(
                    f"Optimization: Reduced reference from {original_ref_count} to {ref_count} features "
                    f"({reduction_pct:.1f}% reduction)",
                    Qgis.Info,
                )

            if ref_count == 0:
                raise Exception(
                    "No reference features in the working area. Check your region filter or input extent."
                )

            if input_count == 0:
                raise Exception(
                    "No input features in the working area. Check your region filter."
                )

            # Step 1.5: Separate boundary lines from regular lines
            boundary_lines, regular_lines = self._separate_boundary_lines(working_input)
            boundary_count = boundary_lines.featureCount() if boundary_lines else 0
            regular_count = regular_lines.featureCount() if regular_lines else 0

            if boundary_count > 0:
                self.log(
                    f"Detected {boundary_count} boundary lines (zero tolerance) and {regular_count} regular lines",
                    Qgis.Info,
                    38,
                )
            else:
                self.log(
                    f"No boundary lines detected, processing {regular_count} regular lines",
                    Qgis.Info,
                    38,
                )

            # Step 2: Buffer the reference layer for regular lines
            self.log(
                f"Creating {self.buffer_distance}m buffer around reference layer...",
                Qgis.Info,
                40,
            )
            buffered_reference = self._create_buffer(working_reference)
            self.log("Buffer created successfully", Qgis.Info, 50)

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            # Step 3: Process regular lines with buffer - OPTIMIZED METHOD
            if regular_count > 0:
                # NEW: Use optimized spatial index-based splitting
                regular_within, regular_outside = self._split_by_buffer_optimized(
                    regular_lines, buffered_reference
                )
            else:
                regular_within = None
                regular_outside = None

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            # Step 4: Process boundary lines with zero tolerance (exact match)
            if boundary_count > 0:
                self.log(
                    "Processing boundary lines with zero tolerance (exact match)...",
                    Qgis.Info,
                    87,
                )
                boundary_within, boundary_outside = self._process_boundary_lines(
                    boundary_lines, working_reference
                )
            else:
                boundary_within = None
                boundary_outside = None

            if self.isCanceled() or self.feedback.isCanceled():
                return False

            # Step 5: Merge all results with tagging
            self.result_layer = self._merge_and_tag_all(
                regular_within,
                regular_outside,
                boundary_within,
                boundary_outside,
                working_input,
            )

            # Calculate detailed statistics
            within_count = sum(
                1 for f in self.result_layer.getFeatures() if f["intersects"]
            )
            outside_count = sum(
                1 for f in self.result_layer.getFeatures() if not f["intersects"]
            )
            total_count = within_count + outside_count

            # Calculate lengths for quality assessment
            within_length = sum(
                f.geometry().length()
                for f in self.result_layer.getFeatures()
                if f["intersects"]
            )
            outside_length = sum(
                f.geometry().length()
                for f in self.result_layer.getFeatures()
                if not f["intersects"]
            )
            total_length = within_length + outside_length
            quality_pct = (
                (within_length / total_length * 100) if total_length > 0 else 0
            )

            # Calculate boundary-specific stats if applicable
            # Check if is_boundary field exists
            has_boundary_field = "is_boundary" in [
                field.name() for field in self.result_layer.fields()
            ]

            if boundary_count > 0 and has_boundary_field:
                boundary_within_count = sum(
                    1
                    for f in self.result_layer.getFeatures()
                    if f["intersects"] and f["is_boundary"]
                )
                boundary_outside_count = sum(
                    1
                    for f in self.result_layer.getFeatures()
                    if not f["intersects"] and f["is_boundary"]
                )
                self.log(
                    f"Boundary lines: {boundary_within_count} exact matches, {boundary_outside_count} no match",
                    Qgis.Info,
                )

            self.log(
                f"Analysis complete! Within: {within_count} ({within_length:.1f}m), "
                f"Outside: {outside_count} ({outside_length:.1f}m), Quality: {quality_pct:.1f}%",
                Qgis.Success,
                100,
            )

            # Warn if most lines are outside buffer
            if outside_count > within_count * 2:
                self.log(
                    f"⚠ Warning: {outside_count} segments outside vs {within_count} inside buffer. "
                    f"Consider checking: (1) Buffer distance ({self.buffer_distance}m), "
                    f"(2) Reference layer alignment, (3) Input layer quality",
                    Qgis.Warning,
                )

            return True

        except Exception as e:
            import traceback

            self.exception = e
            error_msg = f"Error in analysis: {str(e)}"
            tb = traceback.format_exc()
            QgsMessageLog.logMessage(error_msg, "GeoLinesQC", Qgis.Critical)
            QgsMessageLog.logMessage(tb, "GeoLinesQC", Qgis.Critical)
            self.log(error_msg, Qgis.Critical)
            return False

    def _split_by_buffer_optimized(self, input_layer, buffered_reference):
        """
        OPTIMIZED: Split input lines using spatial index pre-filtering and chunked processing.
        This is MUCH faster than using native:intersection and native:difference on large datasets.
        """
        self.log("Building spatial index for buffer zone...", Qgis.Info, 52)

        # Get the buffer geometry (should be a single dissolved geometry)
        buffer_geom = None
        for feat in buffered_reference.getFeatures():
            buffer_geom = feat.geometry()
            break  # Should only be one feature after dissolve

        if not buffer_geom:
            raise Exception("Buffer geometry is empty!")

        buffer_bbox = buffer_geom.boundingBox()

        # Create output memory layers
        within_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "within_buffer",
            "memory",
        )
        outside_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "outside_buffer",
            "memory",
        )

        # Copy field structure
        within_layer.dataProvider().addAttributes(input_layer.fields())
        within_layer.updateFields()
        outside_layer.dataProvider().addAttributes(input_layer.fields())
        outside_layer.updateFields()

        # Collect features for batch insertion (much faster)
        within_features = []
        outside_features = []

        # Get total count for progress reporting
        total_features = input_layer.featureCount()
        processed = 0

        # Quick pre-filter: features completely outside buffer bbox go straight to "outside"
        self.log(f"Pre-filtering {total_features} input features...", Qgis.Info, 55)

        features_to_check = []
        for feat in input_layer.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                return None, None

            feat_bbox = feat.geometry().boundingBox()

            # Quick bbox check: if feature bbox doesn't intersect buffer bbox, it's definitely outside
            if not feat_bbox.intersects(buffer_bbox):
                outside_features.append(feat)
            else:
                # Need to check geometry intersection
                features_to_check.append(feat)

            processed += 1
            if processed % 500 == 0:
                progress = 55 + int((processed / total_features) * 10)
                self.log(
                    f"Pre-filtered {processed}/{total_features} features ({len(outside_features)} clearly outside)...",
                    Qgis.Info,
                    progress,
                )

        self.log(
            f"Pre-filter complete: {len(features_to_check)} need geometry check, "
            f"{len(outside_features)} clearly outside buffer",
            Qgis.Info,
            65,
        )

        # Now process features that need actual geometry intersection check
        processed = 0
        total_to_check = len(features_to_check)

        self.log(
            f"Checking intersection for {total_to_check} features...",
            Qgis.Info,
            66,
        )

        for feat in features_to_check:
            if self.isCanceled() or self.feedback.isCanceled():
                return None, None

            feat_geom = feat.geometry()

            # Test if feature geometry intersects buffer
            if feat_geom.intersects(buffer_geom):
                # Feature intersects buffer - need to split it
                intersection = feat_geom.intersection(buffer_geom)
                difference = feat_geom.difference(buffer_geom)

                # Add intersecting part (if not empty)
                if intersection and not intersection.isEmpty():
                    within_feat = QgsFeature(feat)
                    within_feat.setGeometry(intersection)
                    within_features.append(within_feat)

                # Add non-intersecting part (if not empty)
                if difference and not difference.isEmpty():
                    outside_feat = QgsFeature(feat)
                    outside_feat.setGeometry(difference)
                    outside_features.append(outside_feat)
            else:
                # Feature doesn't intersect buffer at all
                outside_features.append(feat)

            processed += 1

            # Update progress every 100 features
            if processed % 100 == 0 or processed == total_to_check:
                progress = 66 + int((processed / total_to_check) * 20)
                self.log(
                    f"Processed {processed}/{total_to_check} features "
                    f"({len(within_features)} within, {len(outside_features)} outside)...",
                    Qgis.Info,
                    progress,
                )

        # Batch insert features (MUCH faster than one-by-one)
        self.log(
            f"Finalizing results ({len(within_features)} within, {len(outside_features)} outside)...",
            Qgis.Info,
            86,
        )

        if within_features:
            within_layer.dataProvider().addFeatures(within_features)
            within_layer.updateExtents()

        if outside_features:
            outside_layer.dataProvider().addFeatures(outside_features)
            outside_layer.updateExtents()

        self.log(
            f"Split complete: {len(within_features)} segments within, "
            f"{len(outside_features)} segments outside buffer",
            Qgis.Info,
            87,
        )

        return within_layer, outside_layer

    def _separate_boundary_lines(self, input_layer):
        """
        Separate boundary lines from regular lines based on attribute detection.
        Looks for fields containing 'boundary' (case insensitive) with truthy values.
        Returns: (boundary_layer, regular_layer)
        """
        # Find boundary field (fuzzy match for "boundary" in field names)
        boundary_field = None
        for field in input_layer.fields():
            if "mp_bound" in field.name().lower():
                boundary_field = field.name()
                self.log(f"Found boundary field: '{boundary_field}'", Qgis.Info)
                break

        if not boundary_field:
            # No boundary field found, all lines are regular
            return None, input_layer

        # Create memory layers for both types
        boundary_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "boundary_lines",
            "memory",
        )
        regular_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "regular_lines",
            "memory",
        )

        # Copy fields
        boundary_layer.dataProvider().addAttributes(input_layer.fields())
        boundary_layer.updateFields()
        regular_layer.dataProvider().addAttributes(input_layer.fields())
        regular_layer.updateFields()

        # Separate features based on boundary field value
        boundary_features = []
        regular_features = []

        for feat in input_layer.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                break

            boundary_value = feat[boundary_field]

            # Check if boundary value is truthy (True, 1, "1", "true", "yes", etc.)
            is_boundary = False
            if boundary_value is not None:
                if isinstance(boundary_value, bool):
                    is_boundary = boundary_value
                elif isinstance(boundary_value, (int, float)):
                    is_boundary = boundary_value != 0
                elif isinstance(boundary_value, str):
                    is_boundary = boundary_value.lower() in (
                        "true",
                        "1",
                        "yes",
                        "t",
                        "y",
                    )

            if is_boundary:
                boundary_features.append(feat)
            else:
                regular_features.append(feat)

        # Add features to respective layers
        if boundary_features:
            boundary_layer.dataProvider().addFeatures(boundary_features)
            boundary_layer.updateExtents()
        else:
            boundary_layer = None

        if regular_features:
            regular_layer.dataProvider().addFeatures(regular_features)
            regular_layer.updateExtents()
        else:
            regular_layer = None

        return boundary_layer, regular_layer

    def _process_boundary_lines(self, boundary_lines, reference_layer):
        """
        Process boundary lines with zero tolerance - must match reference exactly.
        Uses geometry equality test instead of buffer intersection.
        Returns: (matching_lines, non_matching_lines)
        """
        # Create spatial index of reference layer for efficiency
        reference_index = QgsSpatialIndex(reference_layer.getFeatures())

        # Build reference geometry dictionary
        reference_geoms = {}
        for ref_feat in reference_layer.getFeatures():
            reference_geoms[ref_feat.id()] = ref_feat.geometry()

        # Create output layers
        matching_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(boundary_lines.wkbType())}?crs={boundary_lines.crs().authid()}",
            "boundary_matches",
            "memory",
        )
        non_matching_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(boundary_lines.wkbType())}?crs={boundary_lines.crs().authid()}",
            "boundary_no_matches",
            "memory",
        )

        matching_layer.dataProvider().addAttributes(boundary_lines.fields())
        matching_layer.updateFields()
        non_matching_layer.dataProvider().addAttributes(boundary_lines.fields())
        non_matching_layer.updateFields()

        matching_features = []
        non_matching_features = []

        # Check each boundary line for exact match
        for feat in boundary_lines.getFeatures():
            if self.isCanceled() or self.feedback.isCanceled():
                break

            feat_geom = feat.geometry()
            feat_bbox = feat_geom.boundingBox()

            # Get candidate reference features using spatial index
            candidate_ids = reference_index.intersects(feat_bbox)

            # Test for exact geometry match with candidates
            exact_match_found = False
            for ref_id in candidate_ids:
                ref_geom = reference_geoms[ref_id]

                # Check if geometries are equal (within tiny tolerance for float precision)
                if feat_geom.equals(ref_geom):
                    exact_match_found = True
                    break

            if exact_match_found:
                matching_features.append(feat)
            else:
                non_matching_features.append(feat)

        # Add features to layers
        if matching_features:
            matching_layer.dataProvider().addFeatures(matching_features)
            matching_layer.updateExtents()

        if non_matching_features:
            non_matching_layer.dataProvider().addFeatures(non_matching_features)
            non_matching_layer.updateExtents()

        self.log(
            f"Boundary lines: {len(matching_features)} exact matches, {len(non_matching_features)} no match",
            Qgis.Info,
            88,
        )

        return matching_layer, non_matching_layer

    def _merge_and_tag_all(
        self,
        regular_within,
        regular_outside,
        boundary_within,
        boundary_outside,
        original_layer,
    ):
        """
        Merge all line segments (regular and boundary) and add 'intersects' and 'is_boundary' fields.
        """
        self.log("Tagging and merging all line segments...", Qgis.Info, 90)

        layers_to_merge = []

        # Process regular lines within buffer
        if regular_within and regular_within.featureCount() > 0:
            regular_within.dataProvider().addAttributes(
                [
                    QgsField("intersects", QVariant.Bool),
                    QgsField("is_boundary", QVariant.Bool),
                ]
            )
            regular_within.updateFields()
            regular_within.startEditing()
            for feature in regular_within.getFeatures():
                regular_within.changeAttributeValue(
                    feature.id(),
                    regular_within.fields().indexFromName("intersects"),
                    True,
                )
                regular_within.changeAttributeValue(
                    feature.id(),
                    regular_within.fields().indexFromName("is_boundary"),
                    False,
                )
            regular_within.commitChanges()
            layers_to_merge.append(regular_within)

        # Process regular lines outside buffer
        if regular_outside and regular_outside.featureCount() > 0:
            regular_outside.dataProvider().addAttributes(
                [
                    QgsField("intersects", QVariant.Bool),
                    QgsField("is_boundary", QVariant.Bool),
                ]
            )
            regular_outside.updateFields()
            regular_outside.startEditing()
            for feature in regular_outside.getFeatures():
                regular_outside.changeAttributeValue(
                    feature.id(),
                    regular_outside.fields().indexFromName("intersects"),
                    False,
                )
                regular_outside.changeAttributeValue(
                    feature.id(),
                    regular_outside.fields().indexFromName("is_boundary"),
                    False,
                )
            regular_outside.commitChanges()
            layers_to_merge.append(regular_outside)

        # Process boundary lines with exact matches
        if boundary_within and boundary_within.featureCount() > 0:
            boundary_within.dataProvider().addAttributes(
                [
                    QgsField("intersects", QVariant.Bool),
                    QgsField("is_boundary", QVariant.Bool),
                ]
            )
            boundary_within.updateFields()
            boundary_within.startEditing()
            for feature in boundary_within.getFeatures():
                boundary_within.changeAttributeValue(
                    feature.id(),
                    boundary_within.fields().indexFromName("intersects"),
                    True,
                )
                boundary_within.changeAttributeValue(
                    feature.id(),
                    boundary_within.fields().indexFromName("is_boundary"),
                    True,
                )
            boundary_within.commitChanges()
            layers_to_merge.append(boundary_within)

        # Process boundary lines without matches
        if boundary_outside and boundary_outside.featureCount() > 0:
            boundary_outside.dataProvider().addAttributes(
                [
                    QgsField("intersects", QVariant.Bool),
                    QgsField("is_boundary", QVariant.Bool),
                ]
            )
            boundary_outside.updateFields()
            boundary_outside.startEditing()
            for feature in boundary_outside.getFeatures():
                boundary_outside.changeAttributeValue(
                    feature.id(),
                    boundary_outside.fields().indexFromName("intersects"),
                    False,
                )
                boundary_outside.changeAttributeValue(
                    feature.id(),
                    boundary_outside.fields().indexFromName("is_boundary"),
                    True,
                )
            boundary_outside.commitChanges()
            layers_to_merge.append(boundary_outside)

        if not layers_to_merge:
            raise Exception("No features to merge - this should not happen!")

        self.log("Merging all results...", Qgis.Info, 95)

        # Merge all layers
        merge_params = {
            "LAYERS": layers_to_merge,
            "CRS": original_layer.crs(),
            "OUTPUT": "memory:",
        }
        merge_result = processing.run(
            "native:mergevectorlayers",
            merge_params,
            context=self.context,
            feedback=self.feedback,
        )
        result_layer = merge_result["OUTPUT"]
        result_layer.setName(self.output_name)

        return result_layer

    def _clip_to_region(self):
        """Clip both input and reference layers to the region using spatial filtering"""
        self.log("Using regional filter...", Qgis.Info, 10)

        # Get region geometries
        region_geoms = []
        if self.region_layer.selectedFeatureCount() > 0:
            region_geoms = [
                f.geometry() for f in self.region_layer.getSelectedFeatures()
            ]
            self.log(f"Using {len(region_geoms)} selected region features", Qgis.Info)
        else:
            region_geoms = [f.geometry() for f in self.region_layer.getFeatures()]
            self.log(f"Using all {len(region_geoms)} region features", Qgis.Info)

        # Combine all region geometries into one
        combined_region = QgsGeometry.unaryUnion(region_geoms)
        region_bbox = combined_region.boundingBox()

        if self.isCanceled() or self.feedback.isCanceled():
            return None, None

        # Filter input layer
        self.log("Filtering input layer to region...", Qgis.Info, 15)
        clipped_input = self._filter_layer_by_geometry(
            self.input_layer, combined_region, region_bbox
        )
        input_count = clipped_input.featureCount()
        self.log(f"Input layer filtered: {input_count} features", Qgis.Info, 20)

        if self.isCanceled() or self.feedback.isCanceled():
            return None, None

        # Filter reference layer
        self.log("Filtering reference layer to region...", Qgis.Info, 25)
        clipped_reference = self._filter_layer_by_geometry(
            self.reference_layer, combined_region, region_bbox
        )
        ref_count = clipped_reference.featureCount()
        self.log(f"Reference layer filtered: {ref_count} features", Qgis.Info, 30)

        return clipped_input, clipped_reference

    def _filter_layer_by_geometry(self, input_layer, filter_geom, filter_bbox):
        """Filter a layer by intersection with a geometry - optimized with QgsFeatureRequest"""
        # Create output memory layer
        filtered_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(input_layer.wkbType())}?crs={input_layer.crs().authid()}",
            "filtered",
            "memory",
        )

        filtered_provider = filtered_layer.dataProvider()
        filtered_provider.addAttributes(input_layer.fields())
        filtered_layer.updateFields()

        # Use QgsFeatureRequest to get only features in the bounding box first
        # This is MUCH faster than iterating all features
        request = QgsFeatureRequest()
        request.setFilterRect(filter_bbox)

        # Filter features
        filtered_features = []
        for feat in input_layer.getFeatures(request):
            if self.isCanceled() or self.feedback.isCanceled():
                break

            feat_geom = feat.geometry()
            if not feat_geom:
                continue

            # Precise intersection test (only on bbox-filtered features)
            if feat_geom.intersects(filter_geom):
                filtered_features.append(feat)

        # Add filtered features
        filtered_provider.addFeatures(filtered_features)
        filtered_layer.updateExtents()

        return filtered_layer

    def _clip_to_input_extent(self, reference_layer):
        """
        Filter reference layer to an expanded bounding box of input layer.
        This optimizes performance when no regional filter is provided.
        Uses QgsFeatureRequest for efficient spatial filtering.
        """
        self.log(
            "Optimizing: filtering reference to input extent + buffer...", Qgis.Info, 10
        )

        # Get input layer extent
        input_extent = self.input_layer.extent()

        # Expand extent by buffer distance (with some margin)
        margin = self.buffer_distance * 1.5  # 50% extra margin for safety
        expanded_extent = QgsRectangle(
            input_extent.xMinimum() - margin,
            input_extent.yMinimum() - margin,
            input_extent.xMaximum() + margin,
            input_extent.yMaximum() + margin,
        )

        self.log(
            f"Filtering reference to expanded extent: {expanded_extent}", Qgis.Info
        )

        # Create output memory layer with same structure as reference
        filtered_layer = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(reference_layer.wkbType())}?crs={reference_layer.crs().authid()}",
            "filtered_reference",
            "memory",
        )

        filtered_provider = filtered_layer.dataProvider()
        filtered_provider.addAttributes(reference_layer.fields())
        filtered_layer.updateFields()

        # Use QgsFeatureRequest with spatial filter for FAST filtering
        # This uses QGIS's spatial index internally - much faster than manual iteration!
        request = QgsFeatureRequest()
        request.setFilterRect(expanded_extent)
        request.setFlags(QgsFeatureRequest.ExactIntersect)

        # Get filtered features efficiently
        filtered_features = []
        for feat in reference_layer.getFeatures(request):
            if self.isCanceled() or self.feedback.isCanceled():
                break
            filtered_features.append(feat)

        # Add filtered features to output layer
        filtered_provider.addFeatures(filtered_features)
        filtered_layer.updateExtents()

        ref_count = len(filtered_features)
        self.log(
            f"Reference layer filtered to extent: {ref_count} features (fast!)",
            Qgis.Info,
            30,
        )

        return filtered_layer

    def _create_buffer(self, layer):
        """Create dissolved buffer around layer"""
        buffer_params = {
            "INPUT": layer,
            "DISTANCE": self.buffer_distance,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 0,  # Round
            "JOIN_STYLE": 0,  # Round
            "MITER_LIMIT": 2,
            "DISSOLVE": True,  # Dissolve all buffers into one
            "OUTPUT": "memory:",
        }
        buffer_result = processing.run(
            "native:buffer", buffer_params, context=self.context, feedback=self.feedback
        )
        return buffer_result["OUTPUT"]

    def finished(self, result):
        """Called when task completes"""
        if result:
            QgsMessageLog.logMessage(
                "✓ Analysis completed successfully", "GeoLinesQC", Qgis.Success
            )
            self.analysisComplete.emit(self.result_layer)
        else:
            if self.exception:
                import traceback

                tb = traceback.format_exc()
                QgsMessageLog.logMessage(tb, "GeoLinesQC", Qgis.Critical)
                self.analysisError.emit(str(self.exception))
            elif self.isCanceled():
                QgsMessageLog.logMessage(
                    "⚠ Analysis canceled by user", "GeoLinesQC", Qgis.Warning
                )
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
        self.last_buffer_distance = DEFAULT_BUFFER

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
            if hasattr(child, "layer") and child.layer():
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
            elif hasattr(child, "children"):
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

        # Filter layers: only show line layers for input/reference, polygon for region
        line_layers = [
            (name, layer)
            for name, layer in all_layers
            if layer.geometryType() == QgsWkbTypes.LineGeometry
        ]
        polygon_layers = [
            (name, layer)
            for name, layer in all_layers
            if layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]

        # Populate line layer combos
        line_layer_names = [name for name, _ in line_layers]
        self.layer1_combo.clear()
        self.layer1_combo.addItems(line_layer_names)

        self.layer2_combo.clear()
        self.layer2_combo.addItems(line_layer_names)

        # Populate region combo with polygon layers
        polygon_layer_names = [name for name, _ in polygon_layers]
        self.region_combo.clear()
        self.region_combo.addItem("None (use input extent)")
        self.region_combo.addItems(polygon_layer_names)

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

        try:
            buffer_distance = (
                float(self.threshold_input.text())
                if self.threshold_input.text()
                else DEFAULT_BUFFER
            )
        except ValueError:
            QMessageBox.warning(
                self.dialog,
                "Invalid Input",
                "Please enter a valid number for buffer distance.",
            )
            return

        # Get actual layer objects
        input_layer = self.layer_map.get(layer1_name)
        reference_layer = self.layer_map.get(layer2_name)
        region_layer = (
            self.layer_map.get(region_name)
            if region_name and region_name != "None (use input extent)"
            else None
        )

        # Validate inputs
        if not input_layer or not reference_layer:
            QMessageBox.warning(
                self.dialog,
                "Invalid Selection",
                "Please select valid input and reference layers.",
            )
            return

        # Check if layers have the same CRS
        if input_layer.crs() != reference_layer.crs():
            QMessageBox.warning(
                self.dialog,
                "CRS Mismatch",
                f"Input and reference layers have different CRS:\n"
                f"Input: {input_layer.crs().authid()}\n"
                f"Reference: {reference_layer.crs().authid()}\n\n"
                f"Please reproject one of them to match the other.",
            )
            return

        if region_layer and region_layer.crs() != input_layer.crs():
            QMessageBox.warning(
                self.dialog,
                "CRS Mismatch",
                f"Region layer has different CRS than input layer:\n"
                f"Region: {region_layer.crs().authid()}\n"
                f"Input: {input_layer.crs().authid()}\n\n"
                f"Please reproject the region layer to match.",
            )
            return

        # Create output name
        layer1_short = layer1_name.split("/")[-1]
        layer2_short = layer2_name.split("/")[-1]
        output_name = f"{layer1_short} vs {layer2_short} ({buffer_distance}m)"

        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Initializing analysis...", "Cancel", 0, 100, self.iface.mainWindow()
        )
        self.progress_dialog.setWindowTitle("GeoLines QC Analysis")
        self.progress_dialog.setWindowModality(Qt.NonModal)
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
            output_name,
        )

        # Store buffer distance for statistics display
        self.last_buffer_distance = buffer_distance

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
            duration=3,
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
                    "GeoLines QC", message, level=Qgis.Info, duration=2
                )

    def on_cancel_clicked(self):
        """Handle cancel button in progress dialog"""
        if self.current_task:
            self.current_task.cancel()
            self.iface.messageBar().pushMessage(
                "GeoLines QC", "Canceling analysis...", level=Qgis.Warning, duration=3
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
            within_count = sum(1 for f in result_layer.getFeatures() if f["intersects"])
            outside_count = sum(
                1 for f in result_layer.getFeatures() if not f["intersects"]
            )
            total_count = within_count + outside_count

            # Calculate lengths
            within_length = sum(
                f.geometry().length()
                for f in result_layer.getFeatures()
                if f["intersects"]
            )
            outside_length = sum(
                f.geometry().length()
                for f in result_layer.getFeatures()
                if not f["intersects"]
            )
            total_length = within_length + outside_length

            # Calculate quality score
            quality_score = (
                (within_length / total_length * 100) if total_length > 0 else 0
            )

            # Calculate boundary-specific statistics
            has_boundary_field = "is_boundary" in [
                field.name() for field in result_layer.fields()
            ]
            if has_boundary_field:
                boundary_match_count = sum(
                    1
                    for f in result_layer.getFeatures()
                    if f["is_boundary"] and f["intersects"]
                )
                boundary_no_match_count = sum(
                    1
                    for f in result_layer.getFeatures()
                    if f["is_boundary"] and not f["intersects"]
                )
                boundary_total = boundary_match_count + boundary_no_match_count

                regular_within_count = sum(
                    1
                    for f in result_layer.getFeatures()
                    if not f["is_boundary"] and f["intersects"]
                )
                regular_outside_count = sum(
                    1
                    for f in result_layer.getFeatures()
                    if not f["is_boundary"] and not f["intersects"]
                )
            else:
                boundary_total = 0
                boundary_match_count = 0
                boundary_no_match_count = 0
                regular_within_count = within_count
                regular_outside_count = outside_count

            # Show success message in message bar
            if boundary_total > 0:
                self.iface.messageBar().pushMessage(
                    "✓ Analysis Complete",
                    f"Layer '{result_layer.name()}' added | Regular: {regular_within_count}✓/{regular_outside_count}✗ "
                    f"| Boundary: {boundary_match_count}✓/{boundary_no_match_count}✗",
                    level=Qgis.Success,
                    duration=10,
                )
            else:
                self.iface.messageBar().pushMessage(
                    "✓ Analysis Complete",
                    f"Layer '{result_layer.name()}' added | {within_count} within, {outside_count} outside buffer",
                    level=Qgis.Success,
                    duration=10,
                )

            # Build detailed statistics message
            if boundary_total > 0:
                stats_message = f"""<b>GeoLines QC Results</b><br><br>
<b>Overall:</b><br>
• Within tolerance: {within_count} segments ({within_length:.2f} m)<br>
• Outside tolerance: {outside_count} segments ({outside_length:.2f} m)<br>
• Total: {total_count} segments ({total_length:.2f} m)<br>
• Quality Score: <b>{quality_score:.1f}%</b><br><br>

<b>Regular Lines (Buffer: {self.last_buffer_distance:.0f}m):</b><br>
• Within buffer: {regular_within_count} segments<br>
• Outside buffer: {regular_outside_count} segments<br><br>

<b>Boundary Lines (Zero Tolerance):</b><br>
• Exact matches: {boundary_match_count} segments<br>
• No matches: {boundary_no_match_count} segments<br>
• Total boundaries: {boundary_total} segments<br><br>

<i>Green lines = within tolerance / exact match<br>
Red lines = outside tolerance / no match (need review)</i><br><br>

<b>Note:</b> Boundary lines require exact geometry match with reference.
"""
            else:
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
            "✗ Analysis Failed", error_message, level=Qgis.Critical, duration=10
        )

        QMessageBox.critical(
            self.iface.mainWindow(),
            "Analysis Error",
            f"An error occurred during analysis:\n\n{error_message}\n\n"
            f"Check the Log Messages panel (View → Panels → Log Messages) for details.",
        )

        self.current_task = None
