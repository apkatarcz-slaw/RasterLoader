from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import QgsRectangle, QgsPointXY, QgsWkbTypes
from PyQt5.QtCore import Qt

class RasterLoadMapTool(QgsMapTool):
    def __init__(self, canvas, callback):
        """
        :param canvas: Referencja do mapCanvas QGIS.
        :param callback: Funkcja, która otrzyma jako argument QgsRectangle określający wybrany obszar.
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.callback = callback
        self.start_point = None
        # Używamy QgsWkbTypes.PolygonGeometry zamiast True
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)
    
    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self.rubber_band.addPoint(self.start_point, False)
    
    def canvasMoveEvent(self, event):
        if self.start_point:
            current_point = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(self.start_point, current_point)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)
    
    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            end_point = self.toMapCoordinates(event.pos())
            if self.start_point and (self.start_point != end_point):
                # Tryb prostokątny – przeciągnięcie myszy
                rect = QgsRectangle(self.start_point, end_point)
                self.callback(rect)
            else:
                # Pojedyncze kliknięcie – tworzymy mały obszar tolerancji
                tolerance = self.canvas.mapUnitsPerPixel() * 5
                rect = QgsRectangle(end_point.x() - tolerance, end_point.y() - tolerance,
                                    end_point.x() + tolerance, end_point.y() + tolerance)
                self.callback(rect)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self.start_point = None
