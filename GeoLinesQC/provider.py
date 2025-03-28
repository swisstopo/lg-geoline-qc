from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .proximity_analysis import (  # Import your custom algorithm class
    ProximityAnalysisAlgorithm,
)


class CustomProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        # Add your geoprocessing algorithm to the provider
        self.addAlgorithm(ProximityAnalysisAlgorithm())

    def id(self):
        return "swiss_national_survey"

    def name(self):
        return "Swiss National Survey"

    def icon(self):
        # Provide the path to the icon using the resource system
        return QIcon(":/GeoLinesQC/icons8-line-chart-50.png")
