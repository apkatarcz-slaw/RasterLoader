import os
import shutil
from PyQt5.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QTabWidget,
                             QPushButton, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QFileDialog, QMessageBox, QComboBox, QCheckBox)
from qgis.core import QgsProject, QgsRasterLayer
from qgis.utils import iface
from RasterLoadMapTool import RasterLoadMapTool

# Folder do zapisu konfiguracji zestawów
CONFIG_FOLDER = os.path.join(os.path.expanduser("~"), "Documents", "qzsit")
if not os.path.exists(CONFIG_FOLDER):
    os.makedirs(CONFIG_FOLDER)
DATASETS_FILE = os.path.join(CONFIG_FOLDER, "datasets.txt")

# Globalny słownik zestawów: key: nazwa, value: dict { 'path': <ścieżka>, 'transparency_black': <bool> }
DATASETS = {}

def load_datasets_from_file():
    global DATASETS
    DATASETS = {}
    if os.path.exists(DATASETS_FILE):
        with open(DATASETS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 2:
                    name = parts[0]
                    path = parts[1]
                    transparency_black = parts[2] == "True" if len(parts) > 2 else False
                    DATASETS[name] = {"path": path, "transparency_black": transparency_black}
    return DATASETS

def save_dataset_to_file(name, path, transparency_black):
    with open(DATASETS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{name}|{path}|{transparency_black}\n")

class RasterLoaderDockWidget(QDockWidget):
    """Główny panel wtyczki, dokowany do interfejsu QGIS."""
    def __init__(self, parent=None):
        super().__init__("Wtyczka do wczytywania rastrów", parent)
        self.setObjectName("RasterLoaderDockWidget")
        self.destFolder = None
        self.mapTool = None  # Inicjalizacja zmiennej narzędzia mapowego
        self.initUI()
        load_datasets_from_file()
        self.update_dataset_list()

    def initUI(self):
        main_widget = QWidget(self)
        main_layout = QVBoxLayout(main_widget)
        self.tabs = QTabWidget()
        self.tab_dataset = QWidget()
        self.tab_loading = QWidget()
        self.tab_copy = QWidget()
        self.tabs.addTab(self.tab_dataset, "Tworzenie/Usuwanie zestawów")
        self.tabs.addTab(self.tab_loading, "Wczytywanie zestawu")
        self.tabs.addTab(self.tab_copy, "Kopiowanie danych")
        main_layout.addWidget(self.tabs)
        self.setWidget(main_widget)
        self.init_dataset_tab()
        self.init_loading_tab()
        self.init_copy_tab()

    def init_dataset_tab(self):
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        self.leDatasetName = QLineEdit()
        self.leDatasetName.setPlaceholderText("Nazwa zestawu")
        self.leDatasetPath = QLineEdit()
        self.leDatasetPath.setPlaceholderText("Ścieżka do katalogu z danymi")
        btnBrowse = QPushButton("Wybierz katalog")
        btnBrowse.clicked.connect(self.select_dataset_folder)
        hlayout.addWidget(self.leDatasetName)
        hlayout.addWidget(self.leDatasetPath)
        hlayout.addWidget(btnBrowse)
        layout.addLayout(hlayout)
        self.chkBlackTransparency = QCheckBox("Przezroczystość czarnego")
        self.chkBlackTransparency.setChecked(False)
        layout.addWidget(self.chkBlackTransparency)
        btnAdd = QPushButton("Dodaj zestaw")
        btnAdd.clicked.connect(self.add_dataset)
        layout.addWidget(btnAdd)
        self.listDatasets = QListWidget()
        layout.addWidget(self.listDatasets)
        btnRemove = QPushButton("Usuń zaznaczony zestaw")
        btnRemove.clicked.connect(self.remove_dataset)
        layout.addWidget(btnRemove)
        self.tab_dataset.setLayout(layout)

    def init_loading_tab(self):
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        lbl = QLabel("Wybierz zestaw:")
        self.comboDatasets = QComboBox()
        hlayout.addWidget(lbl)
        hlayout.addWidget(self.comboDatasets)
        layout.addLayout(hlayout)
        btnLoad = QPushButton("Wczytaj dane")
        btnLoad.clicked.connect(self.load_data)
        layout.addWidget(btnLoad)
        infoLabel = QLabel("Po wyborze zestawu aktywny jest domyślny tryb zaznaczenia prostokątnego.\nPrzeciągnij myszą, aby określić obszar ładowania arkuszy.\n(Pojedyncze kliknięcie – ładowanie pojedynczego arkusza.)")
        layout.addWidget(infoLabel)
        self.tab_loading.setLayout(layout)

    def init_copy_tab(self):
        layout = QVBoxLayout()
        self.btnSelectDest = QPushButton("Wybierz katalog docelowy")
        self.btnSelectDest.clicked.connect(self.select_dest_folder)
        layout.addWidget(self.btnSelectDest)
        self.lblDestFolder = QLabel("Katalog docelowy: nie wybrano")
        layout.addWidget(self.lblDestFolder)
        self.btnCopyAll = QPushButton("Kopiuj wszystkie wczytane pliki")
        self.btnCopyAll.clicked.connect(lambda: self.copy_files(selected_only=False))
        layout.addWidget(self.btnCopyAll)
        self.btnCopySelected = QPushButton("Kopiuj tylko zaznaczone (CTRL+klik)")
        self.btnCopySelected.clicked.connect(lambda: self.copy_files(selected_only=True))
        layout.addWidget(self.btnCopySelected)
        self.tab_copy.setLayout(layout)

    def select_dataset_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Wybierz katalog z danymi")
        if folder:
            self.leDatasetPath.setText(folder)

    def add_dataset(self):
        name = self.leDatasetName.text().strip()
        path = self.leDatasetPath.text().strip()
        transparency_black = self.chkBlackTransparency.isChecked()
        if not name or not path or not os.path.isdir(path):
            QMessageBox.warning(self, "Błąd", "Podaj poprawną nazwę i ścieżkę.")
            return
        if name in DATASETS:
            QMessageBox.warning(self, "Błąd", "Zestaw o takiej nazwie już istnieje.")
            return
        save_dataset_to_file(name, path, transparency_black)
        load_datasets_from_file()
        self.update_dataset_list()

    def remove_dataset(self):
        selected = self.listDatasets.currentItem()
        if selected:
            name = selected.text()
            if os.path.exists(DATASETS_FILE):
                with open(DATASETS_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(DATASETS_FILE, "w", encoding="utf-8") as f:
                    for line in lines:
                        if not line.startswith(name + "|"):
                            f.write(line)
            load_datasets_from_file()
            self.update_dataset_list()

    def update_dataset_list(self):
        self.listDatasets.clear()
        self.comboDatasets.clear()
        for name in DATASETS.keys():
            self.listDatasets.addItem(name)
            self.comboDatasets.addItem(name)

    def load_data(self):
        selected = self.comboDatasets.currentText()
        if not selected or selected not in DATASETS:
            QMessageBox.warning(self, "Błąd", "Nie wybrano zestawu.")
            return
        # Inicjalizacja narzędzia mapowego
        self.mapTool = RasterLoadMapTool(iface.mapCanvas(), self.load_rasters_callback)
        iface.mapCanvas().setMapTool(self.mapTool)

    def load_rasters_callback(self, geometry):
        """Wczytuje rastrowe pliki, których zasięg przecina wybrany obszar."""
        selected = self.comboDatasets.currentText()
        if not selected or selected not in DATASETS:
            QMessageBox.warning(self, "Błąd", "Nie wybrano zestawu.")
            return
        config = DATASETS[selected]
        folder = config["path"]
        transparency_black = config["transparency_black"]
        files = [f for f in os.listdir(folder) if f.lower().endswith(('.tif', '.tiff', '.png', '.gif', '.jpg', '.jpeg'))]
        count = 0
        for f in files:
            full_path = os.path.join(folder, f)
            raster = QgsRasterLayer(full_path, f)
            if raster.isValid() and raster.extent().intersects(geometry):
                if any(ext in f.lower() for ext in [".tif", ".tiff", ".png", ".gif"]):
                    # Ustawienie białego koloru jako przezroczystego (domyślnie)
                    raster.renderer().setNodataColor(255, 255, 255)
                    # Ustawienie czarnego koloru jako przezroczystego, jeśli opcja jest włączona
                    if transparency_black:
                        raster.renderer().setNodataColor(0, 0, 0)
                    raster.triggerRepaint()
                QgsProject.instance().addMapLayer(raster)
                count += 1
        if count == 0:
            QMessageBox.information(self, "Wczytywanie danych", "Brak rastrów pokrywających wybrany obszar.")
        if self.mapTool:
            iface.mapCanvas().unsetMapTool(self.mapTool)
            self.mapTool = None

    def select_dest_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Wybierz katalog docelowy")
        if folder:
            self.destFolder = folder
            self.lblDestFolder.setText(f"Katalog docelowy: {folder}")

    def copy_files(self, selected_only=False):
        """Kopiuje pliki z wczytanych warstw do wybranego katalogu."""
        if not self.destFolder:
            QMessageBox.warning(self, "Błąd", "Nie wybrano katalogu docelowego.")
            return
        layers_to_copy = []
        if selected_only:
            layers = iface.layerTreeView().selectedLayers()
            layers_to_copy = [lyr for lyr in layers if lyr in QgsProject.instance().mapLayers().values() and isinstance(lyr, QgsRasterLayer)]
        else:
            layers_to_copy = [lyr for lyr in QgsProject.instance().mapLayers().values() if isinstance(lyr, QgsRasterLayer)]
        copied_count = 0
        for lyr in layers_to_copy:
            source_path = lyr.source()
            if os.path.isfile(source_path):
                folder_src = os.path.dirname(source_path)
                base = os.path.splitext(os.path.basename(source_path))[0]
                for file in os.listdir(folder_src):
                    if file.startswith(base + "."):
                        src_file = os.path.join(folder_src, file)
                        dest_file = os.path.join(self.destFolder, file)
                        if not os.path.exists(dest_file):
                            try:
                                shutil.copy2(src_file, dest_file)
                                copied_count += 1
                            except Exception as e:
                                QMessageBox.warning(self, "Błąd kopiowania", f"Nie udało się skopiować {src_file}: {e}")
        QMessageBox.information(self, "Kopiowanie", f"Skopiowano {copied_count} plików.")