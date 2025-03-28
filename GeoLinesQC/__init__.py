from .main import BasicProcessingTool

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .main import BasicProcessingTool

from .resources import *


def classFactory(iface):
    return GeoProcessingPlugin(iface)


from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import QAction, QToolBar
from qgis.core import QgsApplication


from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar
from .provider import CustomProcessingProvider  # Import the provider class


def classFactory(iface):
    return GeoProcessingPlugin(iface)


class GeoProcessingPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None  # To store the processing provider
        self.toolbar = None  # Custom toolbar
        self.action = None  # Action for the toolbar

    def initGui(self):
        # Create a custom toolbar
        self.toolbar = QToolBar("Geoprocessing Tools", self.iface.mainWindow())
        self.iface.addToolBar(self.toolbar)

        # Create an action for your tool
        self.action = QAction(
            QIcon(":/GeoLinesQC/icons8-line-chart-50.png"),
            "Basic Processing Tool",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)

        # Add the action to the custom toolbar
        self.toolbar.addAction(self.action)

        # Register the processing provider
        self.provider = CustomProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        # Remove the custom toolbar and action
        if self.action:
            self.toolbar.removeAction(self.action)
        if self.toolbar:
            self.iface.mainWindow().removeToolBar(self.toolbar)

        # Unregister the processing provider
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        # Open the processing tool dialog
        from .proximity_analysis import (
            ProximityAnalysisAlgorithm,
        )  # Import your algorithm class

        tool = ProximityAnalysisAlgorithm()
        self.iface.openProcessingToolDialog(tool.createInstance().id())
