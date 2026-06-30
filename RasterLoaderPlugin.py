# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Plugin do wczytywania zestawów rastrów, zarządzania nimi oraz kopiowania plików.
 Funkcje:
 1. Wczytywanie rastrów pokrywających kliknięty punkt lub zaznaczony obszar (prostokąt).
 2. Ustawianie przezroczystości: biały (255,255,255) domyślnie, opcjonalnie czarny (0,0,0).
 3. Zestawy danych zapisywane w osobnych plikach .txt w folderze C:\\Users\\<użytkownik>\\Documents\\qzsit.
 4. Kopiowanie wszystkich plików o tej samej nazwie bazowej, bez nadpisywania istniejących.
 5. Usuwanie rastrów: pojedynczo (kliknięcie) lub wielu (zaznaczenie powierzchniowe).
 6. Interfejs ograniczony do paska narzędzi (bez panelu dokowanego).
 7. Aktywacja wczytywania rastrów po kliknięciu akcji „Aktywuj Wczytywanie” na pasku narzędzi.
***************************************************************************/
"""
import os
import shutil
import re
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import Qt, QCoreApplication, QLocale, QTranslator
from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtWidgets import QAction, QComboBox, QFileDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QCheckBox, QToolBar, QLabel
from qgis.core import QgsProject, QgsRasterLayer, QgsRectangle, QgsPointXY, QgsWkbTypes, QgsRasterRange, QgsMultiBandColorRenderer, QgsSingleBandGrayRenderer, QgsContrastEnhancement
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.utils import iface
from osgeo import gdal

# ==================== DWUJĘZYCZNOŚĆ ====================
def bilingual(pl, en):
    """Polski na górze, angielski na dole (dla większości elementów)"""
    return f"{pl}\n{en}"

def bilingual_one_line(pl, en):
    """Tylko dla combo boxa wyboru zestawu - jedna linia"""
    return f"{pl} / {en}"

def bilingual_msg(title_pl, title_en, msg_pl, msg_en):
    """Dwujęzyczny komunikat QMessageBox"""
    title = bilingual(title_pl, title_en)
    text = f"{msg_pl}\n\n{msg_en}"
    return title, text
# ======================================================

# Globalne zmienne
DATASETS = {} 
LOADED_RASTER_LAYERS = [] 
CONFIG_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "qzsit")
if not os.path.exists(CONFIG_FOLDER):
    os.makedirs(CONFIG_FOLDER)

# Słownik tłumaczeń
TRANSLATIONS = {
    "Raster Loader": "Ładowarka Rastrów",
    "Create Datasets": "Tworzenie Zestawów Danych",
    "Dataset Name": "Nazwa Zestawu Danych",
    "Path to data folder": "Ścieżka do folderu z danymi",
    "Browse": "Przeglądaj",
    "Black Transparency": "Przezroczystość Czarna",
    "Add Dataset": "Dodaj Zestaw Danych",
    "Delete": "Usuń",
    "Error": "Błąd",
    "Please provide a valid name and path.": "Podaj prawidłową nazwę i ścieżkę.",
    "A dataset with this name already exists.": "Zestaw danych o tej nazwie już istnieje.",
    "Info": "Informacja",
    "Dataset name changed to: {sanitized_name}": "Nazwa zestawu danych zmieniona na: {sanitized_name}",
    "Failed to save dataset: {error}": "Nie udało się zapisać zestawu danych: {error}",
    "Copy Files": "Kopiowanie Plików",
    "Select Destination Directory": "Wybierz Folder Docelowy",
    "Destination directory not selected": "Nie wybrano folderu docelowego",
    "Copy All": "Kopiuj Wszystko",
    "Copy Selected": "Kopiuj Wybrane",
    "No destination directory selected.": "Nie wybrano folderu docelowego.",
    "Failed to copy {src_file}: {error}": "Nie udało się skopiować {src_file}: {error}",
    "Copying": "Kopiowanie",
    "Copied {copied_count} files": "Skopiowano {copied_count} plików",
    "Select dataset:": "Wybierz zestaw danych:",
    "Select": "Wybierz",
    "Remove Rasters": "Usuń Rastry",
    "Activate Loading": "Aktywuj Wczytywanie",
    "Dataset '{dataset_name}' no longer exists.": "Zestaw danych '{dataset_name}' już nie istnieje.",
    "No valid dataset selected.": "Nie wybrano prawidłowego zestawu danych.",
    "Removed {removed_count} raster(s).": "Usunięto {removed_count} rastr(ów).",
    "No rasters found in the selected area.": "Nie znaleziono rastrów w wybranym obszarze.",
    "No TIFF files in the dataset.": "Brak plików TIFF w zestawie danych.",
    "No rasters cover the selected area.": "Żadne rastry nie pokrywają wybranego obszaru.",
    "Loaded {count} rasters.": "Wczytano {count} rastrów.",
    "No valid rasters to load.": "Brak prawidłowych rastrów do wczytania.",
    "Loading Data": "Wczytywanie Danych",
}

def tr(message):
    return TRANSLATIONS.get(message, message)

def sanitize_filename(name):
    """Usuwa lub zastępuje niedozwolone znaki w nazwie pliku."""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', name)
    sanitized = sanitized.strip().replace('__', '_')
    return sanitized if sanitized else "dataset"

def get_supported_raster_extensions():
    """
    Statyczna lista rozszerzeń plików rastrowych obsługiwanych przez QGIS 3.34
    (poprzez GDAL): GeoTIFF/TIFF, JPEG, JPEG2000, PNG, BMP, IMG (ERDAS),
    ECW, MrSID, NITF, HDF, NetCDF, GRIB, ASCII Grid, DEM, VRT, MapInfo TAB.
    Lista jest jawna i statyczna (nie odpytuje sterowników GDAL w czasie
    działania), aby nie wpływać na działanie reszty wtyczki.
    """
    return (
        '.tif', '.tiff', '.gtif', '.gtiff',
        '.jpg', '.jpeg', '.jp2', '.j2k',
        '.png', '.bmp', '.gif',
        '.img', '.ecw', '.sid',
        '.ntf', '.nitf',
        '.hdf', '.hdf5', '.he5',
        '.nc',
        '.grb', '.grb2', '.grib', '.grib2',
        '.asc', '.dem',
        '.vrt',
        '.tab',
        '.pix', '.rst', '.mpr', '.mpl',
        '.dt0', '.dt1', '.dt2',
    )

# Statyczna lista rozszerzeń obrazów rastrowych wczytywanych jako warstwy.
# Pliki georeferencji ("world files": tfw, jgw, pgw, bpw, j2w, wld, prj, aux.xml)
# NIE są tu dodawane jako osobne wpisy - GDAL odczytuje je automatycznie po
# nazwie bazowej obok właściwego obrazu, dokładnie tak jak w oryginalnym skrypcie
# dla plików .tif/.tfw.
RASTER_IMAGE_EXTENSIONS = get_supported_raster_extensions()

def get_raster_extent(file_path):
    """Pobiera zasięg przestrzenny pliku rastrowego za pomocą GDAL."""
    ds = gdal.Open(file_path)
    if ds is None:
        return None
    geo_transform = ds.GetGeoTransform()
    cols, rows = ds.RasterXSize, ds.RasterYSize
    min_x = geo_transform[0]
    max_y = geo_transform[3]
    max_x = min_x + cols * geo_transform[1]
    min_y = max_y + rows * geo_transform[5]
    return QgsRectangle(min_x, min_y, max_x, max_y)

def normalize_path(path):
    """Normalizuje ścieżkę do porównywania."""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except:
        return os.path.normcase(os.path.abspath(path))

def load_datasets_from_file():
    global DATASETS
    DATASETS = {}
    for dataset_file in os.listdir(CONFIG_FOLDER):
        if dataset_file.endswith(".txt"):
            dataset_name = os.path.splitext(dataset_file)[0]
            file_path = os.path.join(CONFIG_FOLDER, dataset_file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    line = f.read().strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 2:
                        continue
                    path = parts[0]
                    transparency_black = parts[1] == "True" if len(parts) > 1 else False
                    files_dict = {}
                    if len(parts) > 2:
                        for file_entry in parts[2:]:
                            if ":" in file_entry:
                                try:
                                    file_name, extent = file_entry.split(":", 1)
                                    coords = list(map(float, extent.split(",")))
                                    if len(coords) == 4:
                                        files_dict[file_name] = QgsRectangle(coords[0], coords[1], coords[2], coords[3])
                                except:
                                    continue
                    DATASETS[dataset_name] = {"path": path, "transparency_black": transparency_black, "files": files_dict}
            except Exception as e:
                print(f"Failed to load dataset {dataset_name}: {str(e)}")
    return DATASETS

def save_dataset_to_file(name, path, transparency_black):
    files_dict = {}
    for f in os.listdir(path):
        if f.lower().endswith(RASTER_IMAGE_EXTENSIONS):
            full_path = os.path.join(path, f)
            extent = get_raster_extent(full_path)
            if extent:
                files_dict[f] = extent
 
    sanitized_name = sanitize_filename(name)
    dataset_file = os.path.join(CONFIG_FOLDER, f"{sanitized_name}.txt")
    os.makedirs(CONFIG_FOLDER, exist_ok=True)
 
    with open(dataset_file, "w", encoding="utf-8") as f:
        files_str = "|".join([f"{fname}:{ext.xMinimum()},{ext.yMinimum()},{ext.xMaximum()},{ext.yMaximum()}"
                              for fname, ext in files_dict.items()])
        f.write(f"{path}|{transparency_black}|{files_str}\n")
 
    return sanitized_name

def load_single_raster(args):
    full_path, renderer, white_nodata, black_nodata = args
    raster = QgsRasterLayer(full_path, os.path.basename(full_path))
    if not raster.isValid():
        return None
 
    provider = raster.dataProvider()
    band_count = raster.bandCount()
 
    if band_count == 1:
        renderer = QgsSingleBandGrayRenderer(provider, 1)
        raster.setRenderer(renderer)
    elif band_count >= 3:
        renderer = QgsMultiBandColorRenderer(provider, 1, 2, 3)
        for band in [1, 2, 3]:
            enhancement = QgsContrastEnhancement(provider.dataType(band))
            enhancement.setMinimumValue(0)
            enhancement.setMaximumValue(255)
            enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
            if band == 1:
                renderer.setRedContrastEnhancement(enhancement)
            elif band == 2:
                renderer.setGreenContrastEnhancement(enhancement)
            elif band == 3:
                renderer.setBlueContrastEnhancement(enhancement)
        raster.setRenderer(renderer)
 
    for band in range(1, band_count + 1):
        combined_nodata = []
        if white_nodata:
            combined_nodata.extend(white_nodata)
        if black_nodata:
            combined_nodata.extend(black_nodata)
        if combined_nodata:
            # setUseSourceNoDataValue(False) gwarantuje, że nasza wartość nodata
            # (biały/czarny) zostanie honorowana przy renderowaniu niezależnie od
            # formatu pliku (tif, jpg, png, ecw, img itd.) - niektóre formaty inne
            # niż TIFF mogą zgłaszać własną (lub żadną) wartość source nodata,
            # która inaczej mogłaby przesłonić ustawienie użytkownika i pozostawić
            # widoczną białą/czarną "zasłonę" na stykach sąsiadujących arkuszy.
            provider.setUseSourceNoDataValue(band, False)
            provider.setUserNoDataValue(band, combined_nodata)
 
    try:
        raster.renderer().setOpacity(1.0)
    except AttributeError:
        pass
 
    return raster

# Narzędzia mapowe (bez zmian)
class RasterLoadMapTool(QgsMapTool):
    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self.canvas = canvas
        self.callback = callback
        self.start_point = None
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(self.start_point, False)

    def canvasMoveEvent(self, event):
        if self.start_point:
            current_point = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(self.start_point, current_point)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            end_point = self.toMapCoordinates(event.pos())
            if self.start_point and (self.start_point != end_point):
                rect = QgsRectangle(self.start_point, end_point)
            else:
                tolerance = self.canvas.mapUnitsPerPixel() * 10
                rect = QgsRectangle(end_point.x() - tolerance, end_point.y() - tolerance,
                                    end_point.x() + tolerance, end_point.y() + tolerance)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.start_point = None
            self.callback(rect)

class RemoveRasterMapTool(QgsMapTool):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.start_point = None
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(self.start_point, False)

    def canvasMoveEvent(self, event):
        if self.start_point:
            current_point = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(self.start_point, current_point)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            end_point = self.toMapCoordinates(event.pos())
            removed_count = 0
         
            if self.start_point and (self.start_point != end_point):
                rect = QgsRectangle(self.start_point, end_point)
                for layer in LOADED_RASTER_LAYERS[:]:
                    if isinstance(layer, QgsRasterLayer) and layer.extent().intersects(rect):
                        try:
                            QgsProject.instance().removeMapLayer(layer.id())
                            LOADED_RASTER_LAYERS.remove(layer)
                            removed_count += 1
                        except:
                            pass
            else:
                tolerance = self.canvas.mapUnitsPerPixel() * 10
                rect = QgsRectangle(end_point.x() - tolerance, end_point.y() - tolerance,
                                    end_point.x() + tolerance, end_point.y() + tolerance)
                for layer in LOADED_RASTER_LAYERS[:]:
                    if isinstance(layer, QgsRasterLayer) and layer.extent().intersects(rect):
                        try:
                            QgsProject.instance().removeMapLayer(layer.id())
                            LOADED_RASTER_LAYERS.remove(layer)
                            removed_count += 1
                            break
                        except:
                            pass
         
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.start_point = None
            self.canvas.refresh()
            if removed_count > 0:
                title, text = bilingual_msg("Usuń Rastry", "Remove Rasters", 
                                          f"Usunięto {removed_count} rastr(ów).", 
                                          f"Removed {removed_count} raster(s).")
                QMessageBox.information(self.canvas.parent(), title, text)
            else:
                title, text = bilingual_msg("Usuń Rastry", "Remove Rasters", 
                                          "Nie znaleziono rastrów w wybranym obszarze.", 
                                          "No rasters found in the selected area.")
                QMessageBox.information(self.canvas.parent(), title, text)

# Dialog Tworzenia Zestawów
class CreateDatasetDialog(QDialog):
    def __init__(self, parent=None, plugin=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle(bilingual("Tworzenie Zestawów Danych", "Create Datasets"))
        self.layout = QVBoxLayout(self)
     
        # Nazwa zestawu
        name_layout = QHBoxLayout()
        name_label = QLabel(bilingual("Nazwa Zestawu Danych:", "Dataset Name:"))
        self.leDatasetName = QLineEdit()
        self.leDatasetName.setPlaceholderText(bilingual("Wpisz nazwę zestawu", "Enter dataset name"))
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.leDatasetName)
        self.layout.addLayout(name_layout)
     
        # Ścieżka
        path_layout = QHBoxLayout()
        path_label = QLabel(bilingual("Ścieżka do folderu z danymi:", "Path to data folder:"))
        self.leDatasetPath = QLineEdit()
        self.leDatasetPath.setPlaceholderText(bilingual("Wybierz lub wpisz ścieżkę", "Select or enter path"))
        btnBrowse = QPushButton(bilingual("Przeglądaj", "Browse"))
        btnBrowse.clicked.connect(self.select_dataset_folder)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.leDatasetPath)
        path_layout.addWidget(btnBrowse)
        self.layout.addLayout(path_layout)
     
        self.chkBlackTransparency = QCheckBox(bilingual("Przezroczystość Czarna", "Black Transparency"))
        self.chkBlackTransparency.setChecked(False)
        self.layout.addWidget(self.chkBlackTransparency)
     
        btnAdd = QPushButton(bilingual("Dodaj Zestaw Danych", "Add Dataset"))
        btnAdd.clicked.connect(self.add_dataset)
        self.layout.addWidget(btnAdd)
     
        self.listDatasets = QListWidget()
        self.layout.addWidget(self.listDatasets)
     
        btnRemove = QPushButton(bilingual("Usuń", "Delete"))
        btnRemove.clicked.connect(self.remove_dataset)
        self.layout.addWidget(btnRemove)
     
        self.update_dataset_list()

    def select_dataset_folder(self):
        folder = QFileDialog.getExistingDirectory(self, bilingual("Wybierz Katalog Danych", "Select Data Directory"))
        if folder:
            self.leDatasetPath.setText(folder)

    def add_dataset(self):
        name = self.leDatasetName.text().strip()
        folder = self.leDatasetPath.text().strip()
        transparency_black = self.chkBlackTransparency.isChecked()
        if not name or not folder or not os.path.isdir(folder):
            title, text = bilingual_msg("Błąd", "Error", "Podaj prawidłową nazwę i ścieżkę.", "Please provide a valid name and path.")
            QMessageBox.warning(self, title, text)
            return
        if name in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", "Zestaw danych o tej nazwie już istnieje.", "A dataset with this name already exists.")
            QMessageBox.warning(self, title, text)
            return
        try:
            sanitized_name = save_dataset_to_file(name, folder, transparency_black)
            load_datasets_from_file()
            self.update_dataset_list()
            if self.plugin:
                self.plugin.update_dataset_combo()
            if sanitized_name != name:
                title, text = bilingual_msg("Informacja", "Info", 
                                          f"Nazwa zestawu danych zmieniona na: {sanitized_name}", 
                                          f"Dataset name changed to: {sanitized_name}")
                QMessageBox.information(self, title, text)
        except Exception as e:
            title, text = bilingual_msg("Błąd", "Error", 
                                      f"Nie udało się zapisać zestawu danych: {str(e)}", 
                                      f"Failed to save dataset: {str(e)}")
            QMessageBox.critical(self, title, text)

    def remove_dataset(self):
        selected = self.listDatasets.currentItem()
        if selected:
            name = selected.text()
            dataset_file = os.path.join(CONFIG_FOLDER, f"{sanitize_filename(name)}.txt")
            if os.path.exists(dataset_file):
                os.remove(dataset_file)
            load_datasets_from_file()
            self.update_dataset_list()
            if self.plugin:
                self.plugin.update_dataset_combo()
                if self.plugin.active_dataset == name:
                    self.plugin.active_dataset = None
                    if self.plugin.map_tool:
                        self.plugin.canvas.unsetMapTool(self.plugin.map_tool)
                        self.plugin.map_tool = None

    def update_dataset_list(self):
        self.listDatasets.clear()
        for name in sorted(DATASETS.keys()):
            self.listDatasets.addItem(name)

# Dialog Kopiowania
class CopyFilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(bilingual("Kopiowanie Plików", "Copy Files"))
        self.layout = QVBoxLayout(self)
     
        self.btnSelectDest = QPushButton(bilingual("Wybierz Folder Docelowy", "Select Destination Directory"))
        self.btnSelectDest.clicked.connect(self.select_dest_folder)
        self.layout.addWidget(self.btnSelectDest)
     
        self.lblDestFolder = QLabel(bilingual("Folder docelowy: nie wybrano", "Destination directory: not selected"))
        self.layout.addWidget(self.lblDestFolder)
     
        self.btnCopyAll = QPushButton(bilingual("Kopiuj Wszystko", "Copy All"))
        self.btnCopyAll.clicked.connect(lambda: self.copy_files(selected_only=False))
        self.layout.addWidget(self.btnCopyAll)
     
        self.btnCopySelected = QPushButton(bilingual("Kopiuj Wybrane", "Copy Selected"))
        self.btnCopySelected.clicked.connect(lambda: self.copy_files(selected_only=True))
        self.layout.addWidget(self.btnCopySelected)
     
        self.dest_folder = None

    def select_dest_folder(self):
        folder = QFileDialog.getExistingDirectory(self, bilingual("Wybierz Folder Docelowy", "Select Destination Directory"))
        if folder:
            self.dest_folder = folder
            self.lblDestFolder.setText(bilingual(f"Folder docelowy: {folder}", f"Destination directory: {folder}"))

    def copy_files(self, selected_only=False):
        if not self.dest_folder:
            title, text = bilingual_msg("Błąd", "Error", "Nie wybrano folderu docelowego.", "No destination directory selected.")
            QMessageBox.warning(self, title, text)
            return
        if selected_only:
            layers = iface.layerTreeView().selectedLayers()
            layers_to_copy = [lyr for lyr in layers if isinstance(lyr, QgsRasterLayer)]
        else:
            layers_to_copy = [lyr for lyr in QgsProject.instance().mapLayers().values() if isinstance(lyr, QgsRasterLayer)]
        
        copied_count = 0
        for layer in layers_to_copy:
            source_path = layer.source()
            if os.path.isfile(source_path):
                folder_src = os.path.dirname(source_path)
                base = os.path.splitext(os.path.basename(source_path))[0]
                for file in os.listdir(folder_src):
                    if file.startswith(base + "."):
                        src_file = os.path.join(folder_src, file)
                        dst_file = os.path.join(self.dest_folder, file)
                        if not os.path.exists(dst_file):
                            try:
                                shutil.copy2(src_file, dst_file)
                                copied_count += 1
                            except Exception as e:
                                title, text = bilingual_msg("Błąd", "Error", 
                                                          f"Nie udało się skopiować {src_file}: {str(e)}", 
                                                          f"Failed to copy {src_file}: {str(e)}")
                                QMessageBox.warning(self, title, text)
        title, text = bilingual_msg("Kopiowanie", "Copying", 
                                  f"Skopiowano {copied_count} plików", 
                                  f"Copied {copied_count} files")
        QMessageBox.information(self, title, text)

# Główna klasa wtyczki
class RasterLoaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = None
        self.dataset_dialog = None
        self.copy_dialog = None
        self.map_tool = None
        self.remove_tool = None
        self.combo_datasets = None
        self.actions = []
        self.active_dataset = None
        self.is_initialized = False

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons")
     
        self.toolbar = self.iface.addToolBar(bilingual("Ładowarka Rastrów", "Raster Loader"))
        self.toolbar.setObjectName("RasterLoaderToolbar")
     
        # Create Datasets
        create_action = QAction(QIcon(os.path.join(icon_path, "tworzenie.png")), 
                              bilingual("Tworzenie Zestawów Danych", "Create Datasets"), 
                              self.iface.mainWindow())
        create_action.triggered.connect(self.show_create_dialog)
        self.toolbar.addAction(create_action)
        self.actions.append(create_action)
     
        # Combo box - jedna linia
        self.combo_datasets = QComboBox()
        self.combo_datasets.addItem(bilingual_one_line("Wybierz zestaw", "Select dataset"))
        self.combo_datasets.setMinimumWidth(340)
        self.combo_datasets.currentTextChanged.connect(self.on_dataset_selected)
        self.toolbar.addWidget(self.combo_datasets)
     
        # Activate Loading
        activate_action = QAction(QIcon(os.path.join(icon_path, "activate.png")), 
                                bilingual("Aktywuj Wczytywanie", "Activate Loading"), 
                                self.iface.mainWindow())
        activate_action.triggered.connect(self.activate_load_tool)
        self.toolbar.addAction(activate_action)
        self.actions.append(activate_action)
     
        # Copy Files
        copy_action = QAction(QIcon(os.path.join(icon_path, "kopiowanie.png")), 
                            bilingual("Kopiowanie Plików", "Copy Files"), 
                            self.iface.mainWindow())
        copy_action.triggered.connect(self.show_copy_dialog)
        self.toolbar.addAction(copy_action)
        self.actions.append(copy_action)
     
        # Remove Rasters
        remove_action = QAction(QIcon(os.path.join(icon_path, "usun.png")), 
                              bilingual("Usuń Rastry", "Remove Rasters"), 
                              self.iface.mainWindow())
        remove_action.triggered.connect(self.activate_remove_tool)
        self.toolbar.addAction(remove_action)
        self.actions.append(remove_action)
     
        load_datasets_from_file()
        self.update_dataset_combo()
        self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
        self.is_initialized = True

    def unload(self):
        if self.toolbar:
            self.toolbar.clear()
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None
        if self.map_tool:
            self.canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
        if self.remove_tool:
            self.canvas.unsetMapTool(self.remove_tool)
            self.remove_tool = None
        self.actions.clear()
        self.combo_datasets = None

    def show_create_dialog(self):
        if not self.dataset_dialog:
            self.dataset_dialog = CreateDatasetDialog(self.iface.mainWindow(), plugin=self)
        self.dataset_dialog.show()

    def show_copy_dialog(self):
        if not self.copy_dialog:
            self.copy_dialog = CopyFilesDialog(self.iface.mainWindow())
        self.copy_dialog.show()

    def on_dataset_selected(self, dataset_name):
        select_text = bilingual_one_line("Wybierz zestaw", "Select dataset")
        if not self.is_initialized and dataset_name != select_text:
            self.combo_datasets.blockSignals(True)
            self.combo_datasets.setCurrentText(select_text)
            self.combo_datasets.blockSignals(False)
            return
        if dataset_name == select_text or dataset_name not in DATASETS:
            self.active_dataset = None
            if self.map_tool:
                self.canvas.unsetMapTool(self.map_tool)
                self.map_tool = None
            if dataset_name != select_text and dataset_name not in DATASETS:
                title, text = bilingual_msg("Błąd", "Error", 
                                          f"Zestaw danych '{dataset_name}' już nie istnieje.", 
                                          f"Dataset '{dataset_name}' no longer exists.")
                QMessageBox.warning(self.iface.mainWindow(), title, text)
                self.combo_datasets.blockSignals(True)
                self.combo_datasets.setCurrentText(select_text)
                self.combo_datasets.blockSignals(False)
            return
        self.active_dataset = dataset_name

    def activate_load_tool(self):
        if not self.active_dataset or self.active_dataset not in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", 
                                      "Nie wybrano prawidłowego zestawu danych.", 
                                      "No valid dataset selected.")
            QMessageBox.warning(self.iface.mainWindow(), title, text)
            return
        if self.map_tool:
            self.canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
        self.map_tool = RasterLoadMapTool(self.canvas, self.load_rasters_callback)
        self.canvas.setMapTool(self.map_tool)

    def update_dataset_combo(self):
        if self.combo_datasets:
            self.combo_datasets.blockSignals(True)
            current = self.combo_datasets.currentText()
            self.combo_datasets.clear()
            self.combo_datasets.addItem(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            for name in sorted(DATASETS.keys()):
                self.combo_datasets.addItem(name)
            if current in DATASETS:
                self.combo_datasets.setCurrentText(current)
            else:
                self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            self.combo_datasets.setMinimumWidth(340)
            self.combo_datasets.blockSignals(False)

    def load_rasters_callback(self, geometry):
        dataset_name = self.active_dataset
        if not dataset_name or dataset_name not in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", 
                                      "Nie wybrano prawidłowego zestawu danych.", 
                                      "No valid dataset selected.")
            QMessageBox.warning(self.iface.mainWindow(), title, text)
            self.combo_datasets.blockSignals(True)
            self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            self.combo_datasets.blockSignals(False)
            if self.map_tool:
                self.canvas.unsetMapTool(self.map_tool)
                self.map_tool = None
            return

        config = DATASETS[dataset_name]
        folder = config["path"]
        transparency_black = config["transparency_black"]
        files_dict = config["files"]
    
        if not files_dict:
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      "Brak plików TIFF w zestawie danych.", 
                                      "No TIFF files in the dataset.")
            QMessageBox.information(self.iface.mainWindow(), title, text)
            return

        # --- reszta kodu load_rasters_callback (oryginalna) ---
        first_file = list(files_dict.keys())[0]
        sample_raster = QgsRasterLayer(os.path.join(folder, first_file), "sample")
        band_count = sample_raster.bandCount()
        provider = sample_raster.dataProvider()
    
        if band_count == 1:
            renderer = QgsSingleBandGrayRenderer(provider, 1)
        else:
            renderer = QgsMultiBandColorRenderer(provider, 1, 2, 3)
            for band in [1, 2, 3]:
                enhancement = QgsContrastEnhancement(provider.dataType(band))
                enhancement.setMinimumValue(0)
                enhancement.setMaximumValue(255)
                enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
                if band == 1:
                    renderer.setRedContrastEnhancement(enhancement)
                elif band == 2:
                    renderer.setGreenContrastEnhancement(enhancement)
                elif band == 3:
                    renderer.setBlueContrastEnhancement(enhancement)
    
        white_nodata = [QgsRasterRange(255, 255)]
        black_nodata = [QgsRasterRange(0, 0)] if transparency_black else None
     
        already_loaded = {normalize_path(layer.source()) for layer in LOADED_RASTER_LAYERS}
       
        tasks = []
        for f, extent in files_dict.items():
            if extent.intersects(geometry):
                full_path = os.path.join(folder, f)
                norm_path = normalize_path(full_path)
                if norm_path not in already_loaded:
                    tasks.append((full_path, renderer, white_nodata, black_nodata))
       
        if not tasks:
            return
    
        loaded_rasters = []
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            results = executor.map(load_single_raster, tasks)
            loaded_rasters = [r for r in results if r is not None]
        finally:
            executor.shutdown(wait=True)
    
        if loaded_rasters:
            QgsProject.instance().addMapLayers(loaded_rasters)
            LOADED_RASTER_LAYERS.extend(loaded_rasters)
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      f"Wczytano {len(loaded_rasters)} rastrów.", 
                                      f"Loaded {len(loaded_rasters)} rasters.")
            QMessageBox.information(self.iface.mainWindow(), title, text)
        else:
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      "Brak prawidłowych rastrów do wczytania.", 
                                      "No valid rasters to load.")
            QMessageBox.information(self.iface.mainWindow(), title, text)

    def activate_remove_tool(self):
        self.remove_tool = RemoveRasterMapTool(self.canvas)
        self.canvas.setMapTool(self.remove_tool)

def classFactory(iface):
    return RasterLoaderPlugin(iface)
# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Plugin do wczytywania zestawów rastrów, zarządzania nimi oraz kopiowania plików.
 Funkcje:
 1. Wczytywanie rastrów pokrywających kliknięty punkt lub zaznaczony obszar (prostokąt).
 2. Ustawianie przezroczystości: biały (255,255,255) domyślnie, opcjonalnie czarny (0,0,0).
 3. Zestawy danych zapisywane w osobnych plikach .txt w folderze C:\\Users\\<użytkownik>\\Documents\\qzsit.
 4. Kopiowanie wszystkich plików o tej samej nazwie bazowej, bez nadpisywania istniejących.
 5. Usuwanie rastrów: pojedynczo (kliknięcie) lub wielu (zaznaczenie powierzchniowe).
 6. Interfejs ograniczony do paska narzędzi (bez panelu dokowanego).
 7. Aktywacja wczytywania rastrów po kliknięciu akcji „Aktywuj Wczytywanie” na pasku narzędzi.
***************************************************************************/
"""
import os
import shutil
import re
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import Qt, QCoreApplication, QLocale, QTranslator
from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtWidgets import QAction, QComboBox, QFileDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QCheckBox, QToolBar, QLabel
from qgis.core import QgsProject, QgsRasterLayer, QgsRectangle, QgsPointXY, QgsWkbTypes, QgsRasterRange, QgsMultiBandColorRenderer, QgsSingleBandGrayRenderer, QgsContrastEnhancement
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.utils import iface
from osgeo import gdal

# ==================== DWUJĘZYCZNOŚĆ ====================
def bilingual(pl, en):
    """Polski na górze, angielski na dole (dla większości elementów)"""
    return f"{pl}\n{en}"

def bilingual_one_line(pl, en):
    """Tylko dla combo boxa wyboru zestawu - jedna linia"""
    return f"{pl} / {en}"

def bilingual_msg(title_pl, title_en, msg_pl, msg_en):
    """Dwujęzyczny komunikat QMessageBox"""
    title = bilingual(title_pl, title_en)
    text = f"{msg_pl}\n\n{msg_en}"
    return title, text
# ======================================================

# Globalne zmienne
DATASETS = {} 
LOADED_RASTER_LAYERS = [] 
CONFIG_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "qzsit")
if not os.path.exists(CONFIG_FOLDER):
    os.makedirs(CONFIG_FOLDER)

# Słownik tłumaczeń
TRANSLATIONS = {
    "Raster Loader": "Ładowarka Rastrów",
    "Create Datasets": "Tworzenie Zestawów Danych",
    "Dataset Name": "Nazwa Zestawu Danych",
    "Path to data folder": "Ścieżka do folderu z danymi",
    "Browse": "Przeglądaj",
    "Black Transparency": "Przezroczystość Czarna",
    "Add Dataset": "Dodaj Zestaw Danych",
    "Delete": "Usuń",
    "Error": "Błąd",
    "Please provide a valid name and path.": "Podaj prawidłową nazwę i ścieżkę.",
    "A dataset with this name already exists.": "Zestaw danych o tej nazwie już istnieje.",
    "Info": "Informacja",
    "Dataset name changed to: {sanitized_name}": "Nazwa zestawu danych zmieniona na: {sanitized_name}",
    "Failed to save dataset: {error}": "Nie udało się zapisać zestawu danych: {error}",
    "Copy Files": "Kopiowanie Plików",
    "Select Destination Directory": "Wybierz Folder Docelowy",
    "Destination directory not selected": "Nie wybrano folderu docelowego",
    "Copy All": "Kopiuj Wszystko",
    "Copy Selected": "Kopiuj Wybrane",
    "No destination directory selected.": "Nie wybrano folderu docelowego.",
    "Failed to copy {src_file}: {error}": "Nie udało się skopiować {src_file}: {error}",
    "Copying": "Kopiowanie",
    "Copied {copied_count} files": "Skopiowano {copied_count} plików",
    "Select dataset:": "Wybierz zestaw danych:",
    "Select": "Wybierz",
    "Remove Rasters": "Usuń Rastry",
    "Activate Loading": "Aktywuj Wczytywanie",
    "Dataset '{dataset_name}' no longer exists.": "Zestaw danych '{dataset_name}' już nie istnieje.",
    "No valid dataset selected.": "Nie wybrano prawidłowego zestawu danych.",
    "Removed {removed_count} raster(s).": "Usunięto {removed_count} rastr(ów).",
    "No rasters found in the selected area.": "Nie znaleziono rastrów w wybranym obszarze.",
    "No TIFF files in the dataset.": "Brak plików TIFF w zestawie danych.",
    "No rasters cover the selected area.": "Żadne rastry nie pokrywają wybranego obszaru.",
    "Loaded {count} rasters.": "Wczytano {count} rastrów.",
    "No valid rasters to load.": "Brak prawidłowych rastrów do wczytania.",
    "Loading Data": "Wczytywanie Danych",
}

def tr(message):
    return TRANSLATIONS.get(message, message)

def sanitize_filename(name):
    """Usuwa lub zastępuje niedozwolone znaki w nazwie pliku."""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', name)
    sanitized = sanitized.strip().replace('__', '_')
    return sanitized if sanitized else "dataset"

def get_raster_extent(file_path):
    """Pobiera zasięg przestrzenny pliku rastrowego za pomocą GDAL."""
    ds = gdal.Open(file_path)
    if ds is None:
        return None
    geo_transform = ds.GetGeoTransform()
    cols, rows = ds.RasterXSize, ds.RasterYSize
    min_x = geo_transform[0]
    max_y = geo_transform[3]
    max_x = min_x + cols * geo_transform[1]
    min_y = max_y + rows * geo_transform[5]
    return QgsRectangle(min_x, min_y, max_x, max_y)

def normalize_path(path):
    """Normalizuje ścieżkę do porównywania."""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except:
        return os.path.normcase(os.path.abspath(path))

def load_datasets_from_file():
    global DATASETS
    DATASETS = {}
    for dataset_file in os.listdir(CONFIG_FOLDER):
        if dataset_file.endswith(".txt"):
            dataset_name = os.path.splitext(dataset_file)[0]
            file_path = os.path.join(CONFIG_FOLDER, dataset_file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    line = f.read().strip()
                    if not line:
                        continue
                    parts = line.split("|")
                    if len(parts) < 2:
                        continue
                    path = parts[0]
                    transparency_black = parts[1] == "True" if len(parts) > 1 else False
                    files_dict = {}
                    if len(parts) > 2:
                        for file_entry in parts[2:]:
                            if ":" in file_entry:
                                try:
                                    file_name, extent = file_entry.split(":", 1)
                                    coords = list(map(float, extent.split(",")))
                                    if len(coords) == 4:
                                        files_dict[file_name] = QgsRectangle(coords[0], coords[1], coords[2], coords[3])
                                except:
                                    continue
                    DATASETS[dataset_name] = {"path": path, "transparency_black": transparency_black, "files": files_dict}
            except Exception as e:
                print(f"Failed to load dataset {dataset_name}: {str(e)}")
    return DATASETS

def save_dataset_to_file(name, path, transparency_black):
    files_dict = {}
    for f in os.listdir(path):
        if f.lower().endswith(('.tif', '.tiff')):
            full_path = os.path.join(path, f)
            extent = get_raster_extent(full_path)
            if extent:
                files_dict[f] = extent
 
    sanitized_name = sanitize_filename(name)
    dataset_file = os.path.join(CONFIG_FOLDER, f"{sanitized_name}.txt")
    os.makedirs(CONFIG_FOLDER, exist_ok=True)
 
    with open(dataset_file, "w", encoding="utf-8") as f:
        files_str = "|".join([f"{fname}:{ext.xMinimum()},{ext.yMinimum()},{ext.xMaximum()},{ext.yMaximum()}"
                              for fname, ext in files_dict.items()])
        f.write(f"{path}|{transparency_black}|{files_str}\n")
 
    return sanitized_name

def load_single_raster(args):
    full_path, renderer, white_nodata, black_nodata = args
    raster = QgsRasterLayer(full_path, os.path.basename(full_path))
    if not raster.isValid():
        return None
 
    provider = raster.dataProvider()
    band_count = raster.bandCount()
 
    if band_count == 1:
        renderer = QgsSingleBandGrayRenderer(provider, 1)
        raster.setRenderer(renderer)
    elif band_count >= 3:
        renderer = QgsMultiBandColorRenderer(provider, 1, 2, 3)
        for band in [1, 2, 3]:
            enhancement = QgsContrastEnhancement(provider.dataType(band))
            enhancement.setMinimumValue(0)
            enhancement.setMaximumValue(255)
            enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
            if band == 1:
                renderer.setRedContrastEnhancement(enhancement)
            elif band == 2:
                renderer.setGreenContrastEnhancement(enhancement)
            elif band == 3:
                renderer.setBlueContrastEnhancement(enhancement)
        raster.setRenderer(renderer)
 
    for band in range(1, band_count + 1):
        if white_nodata:
            provider.setUserNoDataValue(band, white_nodata)
        if black_nodata:
            provider.setUserNoDataValue(band, black_nodata)
 
    try:
        raster.renderer().setOpacity(1.0)
    except AttributeError:
        pass
 
    return raster

# Narzędzia mapowe (bez zmian)
class RasterLoadMapTool(QgsMapTool):
    def __init__(self, canvas, callback):
        super().__init__(canvas)
        self.canvas = canvas
        self.callback = callback
        self.start_point = None
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(self.start_point, False)

    def canvasMoveEvent(self, event):
        if self.start_point:
            current_point = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(self.start_point, current_point)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            end_point = self.toMapCoordinates(event.pos())
            if self.start_point and (self.start_point != end_point):
                rect = QgsRectangle(self.start_point, end_point)
            else:
                tolerance = self.canvas.mapUnitsPerPixel() * 10
                rect = QgsRectangle(end_point.x() - tolerance, end_point.y() - tolerance,
                                    end_point.x() + tolerance, end_point.y() + tolerance)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.start_point = None
            self.callback(rect)

class RemoveRasterMapTool(QgsMapTool):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.start_point = None
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_point = self.toMapCoordinates(event.pos())
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(self.start_point, False)

    def canvasMoveEvent(self, event):
        if self.start_point:
            current_point = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(self.start_point, current_point)
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()), False)
            self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            end_point = self.toMapCoordinates(event.pos())
            removed_count = 0
         
            if self.start_point and (self.start_point != end_point):
                rect = QgsRectangle(self.start_point, end_point)
                for layer in LOADED_RASTER_LAYERS[:]:
                    if isinstance(layer, QgsRasterLayer) and layer.extent().intersects(rect):
                        try:
                            QgsProject.instance().removeMapLayer(layer.id())
                            LOADED_RASTER_LAYERS.remove(layer)
                            removed_count += 1
                        except:
                            pass
            else:
                tolerance = self.canvas.mapUnitsPerPixel() * 10
                rect = QgsRectangle(end_point.x() - tolerance, end_point.y() - tolerance,
                                    end_point.x() + tolerance, end_point.y() + tolerance)
                for layer in LOADED_RASTER_LAYERS[:]:
                    if isinstance(layer, QgsRasterLayer) and layer.extent().intersects(rect):
                        try:
                            QgsProject.instance().removeMapLayer(layer.id())
                            LOADED_RASTER_LAYERS.remove(layer)
                            removed_count += 1
                            break
                        except:
                            pass
         
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, 'PolygonGeometry') else False)
            self.start_point = None
            self.canvas.refresh()
            if removed_count > 0:
                title, text = bilingual_msg("Usuń Rastry", "Remove Rasters", 
                                          f"Usunięto {removed_count} rastr(ów).", 
                                          f"Removed {removed_count} raster(s).")
                QMessageBox.information(self.canvas.parent(), title, text)
            else:
                title, text = bilingual_msg("Usuń Rastry", "Remove Rasters", 
                                          "Nie znaleziono rastrów w wybranym obszarze.", 
                                          "No rasters found in the selected area.")
                QMessageBox.information(self.canvas.parent(), title, text)

# Dialog Tworzenia Zestawów
class CreateDatasetDialog(QDialog):
    def __init__(self, parent=None, plugin=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle(bilingual("Tworzenie Zestawów Danych", "Create Datasets"))
        self.layout = QVBoxLayout(self)
     
        # Nazwa zestawu
        name_layout = QHBoxLayout()
        name_label = QLabel(bilingual("Nazwa Zestawu Danych:", "Dataset Name:"))
        self.leDatasetName = QLineEdit()
        self.leDatasetName.setPlaceholderText(bilingual("Wpisz nazwę zestawu", "Enter dataset name"))
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.leDatasetName)
        self.layout.addLayout(name_layout)
     
        # Ścieżka
        path_layout = QHBoxLayout()
        path_label = QLabel(bilingual("Ścieżka do folderu z danymi:", "Path to data folder:"))
        self.leDatasetPath = QLineEdit()
        self.leDatasetPath.setPlaceholderText(bilingual("Wybierz lub wpisz ścieżkę", "Select or enter path"))
        btnBrowse = QPushButton(bilingual("Przeglądaj", "Browse"))
        btnBrowse.clicked.connect(self.select_dataset_folder)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.leDatasetPath)
        path_layout.addWidget(btnBrowse)
        self.layout.addLayout(path_layout)
     
        self.chkBlackTransparency = QCheckBox(bilingual("Przezroczystość Czarna", "Black Transparency"))
        self.chkBlackTransparency.setChecked(False)
        self.layout.addWidget(self.chkBlackTransparency)
     
        btnAdd = QPushButton(bilingual("Dodaj Zestaw Danych", "Add Dataset"))
        btnAdd.clicked.connect(self.add_dataset)
        self.layout.addWidget(btnAdd)
     
        self.listDatasets = QListWidget()
        self.layout.addWidget(self.listDatasets)
     
        btnRemove = QPushButton(bilingual("Usuń", "Delete"))
        btnRemove.clicked.connect(self.remove_dataset)
        self.layout.addWidget(btnRemove)
     
        self.update_dataset_list()

    def select_dataset_folder(self):
        folder = QFileDialog.getExistingDirectory(self, bilingual("Wybierz Katalog Danych", "Select Data Directory"))
        if folder:
            self.leDatasetPath.setText(folder)

    def add_dataset(self):
        name = self.leDatasetName.text().strip()
        folder = self.leDatasetPath.text().strip()
        transparency_black = self.chkBlackTransparency.isChecked()
        if not name or not folder or not os.path.isdir(folder):
            title, text = bilingual_msg("Błąd", "Error", "Podaj prawidłową nazwę i ścieżkę.", "Please provide a valid name and path.")
            QMessageBox.warning(self, title, text)
            return
        if name in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", "Zestaw danych o tej nazwie już istnieje.", "A dataset with this name already exists.")
            QMessageBox.warning(self, title, text)
            return
        try:
            sanitized_name = save_dataset_to_file(name, folder, transparency_black)
            load_datasets_from_file()
            self.update_dataset_list()
            if self.plugin:
                self.plugin.update_dataset_combo()
            if sanitized_name != name:
                title, text = bilingual_msg("Informacja", "Info", 
                                          f"Nazwa zestawu danych zmieniona na: {sanitized_name}", 
                                          f"Dataset name changed to: {sanitized_name}")
                QMessageBox.information(self, title, text)
        except Exception as e:
            title, text = bilingual_msg("Błąd", "Error", 
                                      f"Nie udało się zapisać zestawu danych: {str(e)}", 
                                      f"Failed to save dataset: {str(e)}")
            QMessageBox.critical(self, title, text)

    def remove_dataset(self):
        selected = self.listDatasets.currentItem()
        if selected:
            name = selected.text()
            dataset_file = os.path.join(CONFIG_FOLDER, f"{sanitize_filename(name)}.txt")
            if os.path.exists(dataset_file):
                os.remove(dataset_file)
            load_datasets_from_file()
            self.update_dataset_list()
            if self.plugin:
                self.plugin.update_dataset_combo()
                if self.plugin.active_dataset == name:
                    self.plugin.active_dataset = None
                    if self.plugin.map_tool:
                        self.plugin.canvas.unsetMapTool(self.plugin.map_tool)
                        self.plugin.map_tool = None

    def update_dataset_list(self):
        self.listDatasets.clear()
        for name in sorted(DATASETS.keys()):
            self.listDatasets.addItem(name)

# Dialog Kopiowania
class CopyFilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(bilingual("Kopiowanie Plików", "Copy Files"))
        self.layout = QVBoxLayout(self)
     
        self.btnSelectDest = QPushButton(bilingual("Wybierz Folder Docelowy", "Select Destination Directory"))
        self.btnSelectDest.clicked.connect(self.select_dest_folder)
        self.layout.addWidget(self.btnSelectDest)
     
        self.lblDestFolder = QLabel(bilingual("Folder docelowy: nie wybrano", "Destination directory: not selected"))
        self.layout.addWidget(self.lblDestFolder)
     
        self.btnCopyAll = QPushButton(bilingual("Kopiuj Wszystko", "Copy All"))
        self.btnCopyAll.clicked.connect(lambda: self.copy_files(selected_only=False))
        self.layout.addWidget(self.btnCopyAll)
     
        self.btnCopySelected = QPushButton(bilingual("Kopiuj Wybrane", "Copy Selected"))
        self.btnCopySelected.clicked.connect(lambda: self.copy_files(selected_only=True))
        self.layout.addWidget(self.btnCopySelected)
     
        self.dest_folder = None

    def select_dest_folder(self):
        folder = QFileDialog.getExistingDirectory(self, bilingual("Wybierz Folder Docelowy", "Select Destination Directory"))
        if folder:
            self.dest_folder = folder
            self.lblDestFolder.setText(bilingual(f"Folder docelowy: {folder}", f"Destination directory: {folder}"))

    def copy_files(self, selected_only=False):
        if not self.dest_folder:
            title, text = bilingual_msg("Błąd", "Error", "Nie wybrano folderu docelowego.", "No destination directory selected.")
            QMessageBox.warning(self, title, text)
            return
        if selected_only:
            layers = iface.layerTreeView().selectedLayers()
            layers_to_copy = [lyr for lyr in layers if isinstance(lyr, QgsRasterLayer)]
        else:
            layers_to_copy = [lyr for lyr in QgsProject.instance().mapLayers().values() if isinstance(lyr, QgsRasterLayer)]
        
        copied_count = 0
        for layer in layers_to_copy:
            source_path = layer.source()
            if os.path.isfile(source_path):
                folder_src = os.path.dirname(source_path)
                base = os.path.splitext(os.path.basename(source_path))[0]
                for file in os.listdir(folder_src):
                    if file.startswith(base + "."):
                        src_file = os.path.join(folder_src, file)
                        dst_file = os.path.join(self.dest_folder, file)
                        if not os.path.exists(dst_file):
                            try:
                                shutil.copy2(src_file, dst_file)
                                copied_count += 1
                            except Exception as e:
                                title, text = bilingual_msg("Błąd", "Error", 
                                                          f"Nie udało się skopiować {src_file}: {str(e)}", 
                                                          f"Failed to copy {src_file}: {str(e)}")
                                QMessageBox.warning(self, title, text)
        title, text = bilingual_msg("Kopiowanie", "Copying", 
                                  f"Skopiowano {copied_count} plików", 
                                  f"Copied {copied_count} files")
        QMessageBox.information(self, title, text)

# Główna klasa wtyczki
class RasterLoaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = None
        self.dataset_dialog = None
        self.copy_dialog = None
        self.map_tool = None
        self.remove_tool = None
        self.combo_datasets = None
        self.actions = []
        self.active_dataset = None
        self.is_initialized = False

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons")
     
        self.toolbar = self.iface.addToolBar(bilingual("Ładowarka Rastrów", "Raster Loader"))
        self.toolbar.setObjectName("RasterLoaderToolbar")
     
        # Create Datasets
        create_action = QAction(QIcon(os.path.join(icon_path, "tworzenie.png")), 
                              bilingual("Tworzenie Zestawów Danych", "Create Datasets"), 
                              self.iface.mainWindow())
        create_action.triggered.connect(self.show_create_dialog)
        self.toolbar.addAction(create_action)
        self.actions.append(create_action)
     
        # Combo box - jedna linia
        self.combo_datasets = QComboBox()
        self.combo_datasets.addItem(bilingual_one_line("Wybierz zestaw", "Select dataset"))
        self.combo_datasets.setMinimumWidth(340)
        self.combo_datasets.currentTextChanged.connect(self.on_dataset_selected)
        self.toolbar.addWidget(self.combo_datasets)
     
        # Activate Loading
        activate_action = QAction(QIcon(os.path.join(icon_path, "activate.png")), 
                                bilingual("Aktywuj Wczytywanie", "Activate Loading"), 
                                self.iface.mainWindow())
        activate_action.triggered.connect(self.activate_load_tool)
        self.toolbar.addAction(activate_action)
        self.actions.append(activate_action)
     
        # Copy Files
        copy_action = QAction(QIcon(os.path.join(icon_path, "kopiowanie.png")), 
                            bilingual("Kopiowanie Plików", "Copy Files"), 
                            self.iface.mainWindow())
        copy_action.triggered.connect(self.show_copy_dialog)
        self.toolbar.addAction(copy_action)
        self.actions.append(copy_action)
     
        # Remove Rasters
        remove_action = QAction(QIcon(os.path.join(icon_path, "usun.png")), 
                              bilingual("Usuń Rastry", "Remove Rasters"), 
                              self.iface.mainWindow())
        remove_action.triggered.connect(self.activate_remove_tool)
        self.toolbar.addAction(remove_action)
        self.actions.append(remove_action)
     
        load_datasets_from_file()
        self.update_dataset_combo()
        self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
        self.is_initialized = True

    def unload(self):
        if self.toolbar:
            self.toolbar.clear()
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None
        if self.map_tool:
            self.canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
        if self.remove_tool:
            self.canvas.unsetMapTool(self.remove_tool)
            self.remove_tool = None
        self.actions.clear()
        self.combo_datasets = None

    def show_create_dialog(self):
        if not self.dataset_dialog:
            self.dataset_dialog = CreateDatasetDialog(self.iface.mainWindow(), plugin=self)
        self.dataset_dialog.show()

    def show_copy_dialog(self):
        if not self.copy_dialog:
            self.copy_dialog = CopyFilesDialog(self.iface.mainWindow())
        self.copy_dialog.show()

    def on_dataset_selected(self, dataset_name):
        select_text = bilingual_one_line("Wybierz zestaw", "Select dataset")
        if not self.is_initialized and dataset_name != select_text:
            self.combo_datasets.blockSignals(True)
            self.combo_datasets.setCurrentText(select_text)
            self.combo_datasets.blockSignals(False)
            return
        if dataset_name == select_text or dataset_name not in DATASETS:
            self.active_dataset = None
            if self.map_tool:
                self.canvas.unsetMapTool(self.map_tool)
                self.map_tool = None
            if dataset_name != select_text and dataset_name not in DATASETS:
                title, text = bilingual_msg("Błąd", "Error", 
                                          f"Zestaw danych '{dataset_name}' już nie istnieje.", 
                                          f"Dataset '{dataset_name}' no longer exists.")
                QMessageBox.warning(self.iface.mainWindow(), title, text)
                self.combo_datasets.blockSignals(True)
                self.combo_datasets.setCurrentText(select_text)
                self.combo_datasets.blockSignals(False)
            return
        self.active_dataset = dataset_name

    def activate_load_tool(self):
        if not self.active_dataset or self.active_dataset not in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", 
                                      "Nie wybrano prawidłowego zestawu danych.", 
                                      "No valid dataset selected.")
            QMessageBox.warning(self.iface.mainWindow(), title, text)
            return
        if self.map_tool:
            self.canvas.unsetMapTool(self.map_tool)
            self.map_tool = None
        self.map_tool = RasterLoadMapTool(self.canvas, self.load_rasters_callback)
        self.canvas.setMapTool(self.map_tool)

    def update_dataset_combo(self):
        if self.combo_datasets:
            self.combo_datasets.blockSignals(True)
            current = self.combo_datasets.currentText()
            self.combo_datasets.clear()
            self.combo_datasets.addItem(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            for name in sorted(DATASETS.keys()):
                self.combo_datasets.addItem(name)
            if current in DATASETS:
                self.combo_datasets.setCurrentText(current)
            else:
                self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            self.combo_datasets.setMinimumWidth(340)
            self.combo_datasets.blockSignals(False)

    def load_rasters_callback(self, geometry):
        dataset_name = self.active_dataset
        if not dataset_name or dataset_name not in DATASETS:
            title, text = bilingual_msg("Błąd", "Error", 
                                      "Nie wybrano prawidłowego zestawu danych.", 
                                      "No valid dataset selected.")
            QMessageBox.warning(self.iface.mainWindow(), title, text)
            self.combo_datasets.blockSignals(True)
            self.combo_datasets.setCurrentText(bilingual_one_line("Wybierz zestaw", "Select dataset"))
            self.combo_datasets.blockSignals(False)
            if self.map_tool:
                self.canvas.unsetMapTool(self.map_tool)
                self.map_tool = None
            return

        config = DATASETS[dataset_name]
        folder = config["path"]
        transparency_black = config["transparency_black"]
        files_dict = config["files"]
    
        if not files_dict:
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      "Brak plików TIFF w zestawie danych.", 
                                      "No TIFF files in the dataset.")
            QMessageBox.information(self.iface.mainWindow(), title, text)
            return

        # --- reszta kodu load_rasters_callback (oryginalna) ---
        first_file = list(files_dict.keys())[0]
        sample_raster = QgsRasterLayer(os.path.join(folder, first_file), "sample")
        band_count = sample_raster.bandCount()
        provider = sample_raster.dataProvider()
    
        if band_count == 1:
            renderer = QgsSingleBandGrayRenderer(provider, 1)
        else:
            renderer = QgsMultiBandColorRenderer(provider, 1, 2, 3)
            for band in [1, 2, 3]:
                enhancement = QgsContrastEnhancement(provider.dataType(band))
                enhancement.setMinimumValue(0)
                enhancement.setMaximumValue(255)
                enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
                if band == 1:
                    renderer.setRedContrastEnhancement(enhancement)
                elif band == 2:
                    renderer.setGreenContrastEnhancement(enhancement)
                elif band == 3:
                    renderer.setBlueContrastEnhancement(enhancement)
    
        white_nodata = [QgsRasterRange(255, 255)]
        black_nodata = [QgsRasterRange(0, 0)] if transparency_black else None
     
        already_loaded = {normalize_path(layer.source()) for layer in LOADED_RASTER_LAYERS}
       
        tasks = []
        for f, extent in files_dict.items():
            if extent.intersects(geometry):
                full_path = os.path.join(folder, f)
                norm_path = normalize_path(full_path)
                if norm_path not in already_loaded:
                    tasks.append((full_path, renderer, white_nodata, black_nodata))
       
        if not tasks:
            return
    
        loaded_rasters = []
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            results = executor.map(load_single_raster, tasks)
            loaded_rasters = [r for r in results if r is not None]
        finally:
            executor.shutdown(wait=True)
    
        if loaded_rasters:
            QgsProject.instance().addMapLayers(loaded_rasters)
            LOADED_RASTER_LAYERS.extend(loaded_rasters)
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      f"Wczytano {len(loaded_rasters)} rastrów.", 
                                      f"Loaded {len(loaded_rasters)} rasters.")
            QMessageBox.information(self.iface.mainWindow(), title, text)
        else:
            title, text = bilingual_msg("Wczytywanie Danych", "Loading Data", 
                                      "Brak prawidłowych rastrów do wczytania.", 
                                      "No valid rasters to load.")
            QMessageBox.information(self.iface.mainWindow(), title, text)

    def activate_remove_tool(self):
        self.remove_tool = RemoveRasterMapTool(self.canvas)
        self.canvas.setMapTool(self.remove_tool)

def classFactory(iface):
    return RasterLoaderPlugin(iface)
