"""Review glioma segmentations on T1pre, T1post, T1sub, and FLAIR.

Cases come from a spreadsheet with ``bids_study_dir`` and
``segmentation_study_dir`` columns. Both folders are BIDS sessions.
T1sub is T1-postcontrast minus T1-precontrast, voxel by voxel.
"""

import csv
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


logger = logging.getLogger(__name__)

DEFAULT_SPREADSHEET = (
    "/Users/brian/repos/glioma-segmentation/glioma-heldout-set/heldout_studies.csv"
)
SETTINGS_SPREADSHEET_KEY = "SegmentationReview/spreadsheet"
SETTINGS_DATASET_ROOT_KEY = "SegmentationReview/datasetRoot"
MANAGED_NODE_ATTRIBUTE = "SegmentationReview.ManagedNode"
CUSTOM_LAYOUT_ID = 1510
PREVIOUS_CASE_SHORTCUT = "["
NEXT_CASE_SHORTCUT = "]"
TOGGLE_SEGMENTS_SHORTCUT = "Shift+V"
PREVIOUS_SHORTCUT_NAME = "SegmentationReviewPreviousCaseShortcut"
NEXT_SHORTCUT_NAME = "SegmentationReviewNextCaseShortcut"
TOGGLE_SEGMENTS_SHORTCUT_NAME = "SegmentationReviewToggleSegmentsShortcut"
OVERLAY_OPACITY = 0.45
ANAT_FOLDER = "anat"

# T1sub = T1post - T1pre.
DISPLAYED_VOLUMES = ("T1pre", "T1post", "T1sub", "FLAIR")

# Ground-truth labels from derivatives/ground-truth-segs/dseg.tsv.
# Colors match the lab's BraTS overlay palette.
SEGMENT_DEFINITIONS = (
    (1, "Non-Enhancing Tumor Core", (1.0, 0.0, 0.0)),
    (2, "Surrounding Non-Enhancing FLAIR Hyperintensity", (0.0, 1.0, 0.0)),
    (3, "Enhancing Tissue", (1.0, 1.0, 0.0)),
    (4, "Resection Cavity", (0.0, 0.0, 1.0)),
)

IMAGE_RULES = (
    ("t1pre", "T1-precontrast", re.compile(r"^sub-[^_]+_ses-[^_]+_T1w\.nii(?:\.gz)?$")),
    (
        "t1post",
        "T1-postcontrast",
        re.compile(r"^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\.nii(?:\.gz)?$"),
    ),
    ("t2", "T2", re.compile(r"^sub-[^_]+_ses-[^_]+_T2w?\.nii(?:\.gz)?$")),
    ("flair", "FLAIR", re.compile(r"^sub-[^_]+_ses-[^_]+_FLAIR\.nii(?:\.gz)?$")),
)
SEGMENTATION_PATTERN = re.compile(
    r"^sub-[^_]+_ses-[^_]+_space-orig_dseg\.nii(?:\.gz)?$"
)
REQUIRED_COLUMNS = ("bids_study_dir", "segmentation_study_dir")

VIEW_SPECS = (
    ("Red", "T1pre", (243 / 255.0, 74 / 255.0, 51 / 255.0)),
    ("Yellow", "T1post", (237 / 255.0, 213 / 255.0, 76 / 255.0)),
    ("Green", "T1sub", (110 / 255.0, 176 / 255.0, 75 / 255.0)),
    ("Compare1", "FLAIR", (76 / 255.0, 125 / 255.0, 255 / 255.0)),
)

FOUR_UP_LAYOUT = """
<layout type="vertical">
  <item>
    <layout type="horizontal">
      <item>
        <view class="vtkMRMLSliceNode" singletontag="Red">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">T1pre</property>
          <property name="viewcolor" action="default">#F34A33</property>
        </view>
      </item>
      <item>
        <view class="vtkMRMLSliceNode" singletontag="Yellow">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">T1post</property>
          <property name="viewcolor" action="default">#EDD54C</property>
        </view>
      </item>
    </layout>
  </item>
  <item>
    <layout type="horizontal">
      <item>
        <view class="vtkMRMLSliceNode" singletontag="Green">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">T1sub</property>
          <property name="viewcolor" action="default">#6EB04B</property>
        </view>
      </item>
      <item>
        <view class="vtkMRMLSliceNode" singletontag="Compare1">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">FLAIR</property>
          <property name="viewcolor" action="default">#4C7DFF</property>
        </view>
      </item>
    </layout>
  </item>
</layout>
"""


class CaseLoadError(Exception):
    """A case or spreadsheet could not be loaded. The scene is left unchanged."""


@dataclass(frozen=True)
class CaseRecord:
    row_number: int
    patient_id: str
    study_id: str
    session_id: str
    operation_status: str
    grade: str
    glioma_type: str
    bids_study_dir: str
    segmentation_study_dir: str

    @property
    def key(self) -> str:
        return f"{self.study_id}|{self.patient_id}|{self.session_id}"

    @property
    def title(self) -> str:
        return self.study_id or f"{self.patient_id}/{self.session_id}"


@dataclass(frozen=True)
class CaseFiles:
    t1pre: str
    t1post: str
    t2: str
    flair: str
    segmentation: str


def case_label(case: CaseRecord) -> str:
    detail = case.grade or case.glioma_type
    parts = [case.title, case.operation_status]
    if detail:
        parts.append(detail)
    if case.patient_id or case.session_id:
        parts.append(f"{case.patient_id}/{case.session_id}")
    return " | ".join(part for part in parts if part)


def read_cases(spreadsheet_path: str) -> List[CaseRecord]:
    if not spreadsheet_path or not os.path.isfile(spreadsheet_path):
        raise CaseLoadError(f"Spreadsheet not found: {spreadsheet_path}")

    try:
        with open(spreadsheet_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
            if missing:
                raise CaseLoadError(
                    f"{spreadsheet_path} is missing column(s): {', '.join(missing)}."
                )
            cases = []
            for row in reader:
                bids_dir = (row.get("bids_study_dir") or "").strip()
                segmentation_dir = (row.get("segmentation_study_dir") or "").strip()
                if not bids_dir and not segmentation_dir:
                    continue
                if not bids_dir or not segmentation_dir:
                    raise CaseLoadError(
                        f"{spreadsheet_path} row {reader.line_num} needs both "
                        "bids_study_dir and segmentation_study_dir."
                    )
                cases.append(
                    CaseRecord(
                        row_number=reader.line_num,
                        patient_id=(row.get("patient_id") or "").strip(),
                        study_id=(row.get("study_id") or "").strip(),
                        session_id=(row.get("session_id") or "").strip(),
                        operation_status=(row.get("operation_status") or "").strip(),
                        grade=(row.get("grade") or "").strip(),
                        glioma_type=(row.get("glioma_type") or "").strip(),
                        bids_study_dir=bids_dir,
                        segmentation_study_dir=segmentation_dir,
                    )
                )
    except CaseLoadError:
        raise
    except OSError as exc:
        raise CaseLoadError(f"Could not read {spreadsheet_path}: {exc}") from exc
    except csv.Error as exc:
        raise CaseLoadError(f"Could not parse {spreadsheet_path}: {exc}") from exc

    if not cases:
        raise CaseLoadError(f"No cases found in {spreadsheet_path}.")
    return cases


def resolve_path(path: str, dataset_root: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)
    if not dataset_root:
        raise CaseLoadError(
            f"Dataset root is not set, so the relative path '{path}' cannot be resolved."
        )
    return os.path.normpath(os.path.join(dataset_root, path))


def infer_dataset_root(spreadsheet_path: str, relative_path: str) -> Optional[str]:
    """Walk up from the spreadsheet until ``relative_path`` exists under a parent."""
    if not relative_path or os.path.isabs(relative_path):
        return None
    directory = os.path.dirname(os.path.abspath(spreadsheet_path))
    for _ in range(10):
        if os.path.isdir(os.path.join(directory, relative_path)):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return None


def format_shape(shape: Sequence[int]) -> str:
    return " x ".join(str(int(value)) for value in shape)


def same_shape_error(pre_shape: Sequence[int], post_shape: Sequence[int], title: str) -> Optional[str]:
    if tuple(pre_shape) == tuple(post_shape):
        return None
    return (
        f"{title}: T1-precontrast is {format_shape(pre_shape)} and "
        f"T1-postcontrast is {format_shape(post_shape)}, so they cannot be "
        "subtracted voxel by voxel."
    )


def _matching_files(directory: str, pattern: re.Pattern) -> List[str]:
    if not os.path.isdir(directory):
        return []
    matches = []
    for name in sorted(os.listdir(directory)):
        if pattern.match(name):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                matches.append(path)
    return matches


def _require_one(directory: str, pattern: re.Pattern, label: str, problems: List[str]) -> Optional[str]:
    matches = _matching_files(directory, pattern)
    if not matches:
        problems.append(
            f"{label} is not present in {directory}."
        )
        return None
    if len(matches) > 1:
        names = ", ".join(os.path.basename(path) for path in matches)
        problems.append(f"Found more than one {label} file in {directory}: {names}.")
        return None
    return matches[0]


def find_case_files(case: CaseRecord, dataset_root: str) -> CaseFiles:
    """Locate the four anatomical images and the segmentation. Does not load them."""
    image_dir = os.path.join(resolve_path(case.bids_study_dir, dataset_root), ANAT_FOLDER)
    segmentation_dir = os.path.join(
        resolve_path(case.segmentation_study_dir, dataset_root),
        ANAT_FOLDER,
    )
    problems: List[str] = []
    found: Dict[str, Optional[str]] = {}

    if not os.path.isdir(image_dir):
        problems.append(f"Image folder does not exist: {image_dir}.")
    else:
        for key, label, pattern in IMAGE_RULES:
            found[key] = _require_one(image_dir, pattern, label, problems)

    if not os.path.isdir(segmentation_dir):
        problems.append(f"Segmentation folder does not exist: {segmentation_dir}.")
        segmentation_path = None
    else:
        segmentation_path = _require_one(
            segmentation_dir,
            SEGMENTATION_PATTERN,
            "segmentation",
            problems,
        )

    if problems:
        details = "\n".join(f"- {problem}" for problem in problems)
        raise CaseLoadError(f"{case.title}:\n{details}")

    return CaseFiles(
        t1pre=found["t1pre"],
        t1post=found["t1post"],
        t2=found["t2"],
        flair=found["flair"],
        segmentation=segmentation_path,
    )


try:
    import ctk
    import numpy as np
    import qt
    import slicer
    import vtk
    from slicer.ScriptedLoadableModule import (
        ScriptedLoadableModule,
        ScriptedLoadableModuleLogic,
        ScriptedLoadableModuleWidget,
    )
    from slicer.util import VTKObservationMixin

    SLICER_AVAILABLE = True
except ImportError:
    ctk = None
    np = None
    qt = None
    slicer = None
    vtk = None
    SLICER_AVAILABLE = False

    class ScriptedLoadableModule:
        def __init__(self, parent=None):
            self.parent = parent

    class ScriptedLoadableModuleWidget:
        def setup(self):
            pass

    class ScriptedLoadableModuleLogic:
        pass

    class VTKObservationMixin:
        pass


class SegmentationReview(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Segmentation Review"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = []
        self.parent.helpText = (
            "Review a segmentation over T1pre, T1post, T1sub (T1post minus T1pre), "
            "and FLAIR. Cases are listed in a spreadsheet."
        )
        self.parent.acknowledgementText = ""


class SegmentationReviewWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.cases: List[CaseRecord] = []
        self.loadedCaseIndex: Optional[int] = None
        self._updatingSelector = False
        self.spreadsheetEdit = None
        self.datasetRootEdit = None
        self.caseSelector = None
        self.previousButton = None
        self.nextButton = None
        self.overlayCheckBox = None
        self.opacitySlider = None
        self.statusLabel = None
        self.previousShortcut = None
        self.nextShortcut = None
        self.toggleSegmentsShortcut = None

    def setup(self):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This module must be run inside 3D Slicer.")

        super().setup()
        SegmentationReviewLogic.remove_managed_nodes()
        self.logic = SegmentationReviewLogic()

        cases_button = ctk.ctkCollapsibleButton()
        cases_button.text = "Cases"
        self.layout.addWidget(cases_button)
        form = qt.QFormLayout(cases_button)

        spreadsheet_row = qt.QHBoxLayout()
        self.spreadsheetEdit = qt.QLineEdit()
        self.spreadsheetEdit.toolTip = (
            "CSV with bids_study_dir and segmentation_study_dir columns."
        )
        browse_spreadsheet = qt.QPushButton("Browse")
        browse_spreadsheet.toolTip = "Choose a case spreadsheet."
        spreadsheet_row.addWidget(self.spreadsheetEdit)
        spreadsheet_row.addWidget(browse_spreadsheet)
        form.addRow("Spreadsheet", spreadsheet_row)

        root_row = qt.QHBoxLayout()
        self.datasetRootEdit = qt.QLineEdit()
        self.datasetRootEdit.toolTip = (
            "Directory that relative bids_study_dir and segmentation_study_dir "
            "paths are resolved from. For the held-out spreadsheet this is the "
            "glioma-segmentation repository root."
        )
        browse_root = qt.QPushButton("Browse")
        browse_root.toolTip = "Choose the dataset root."
        root_row.addWidget(self.datasetRootEdit)
        root_row.addWidget(browse_root)
        form.addRow("Dataset root", root_row)

        load_button = qt.QPushButton("Load spreadsheet")
        load_button.toolTip = "Read the spreadsheet and load the current case."
        form.addRow(load_button)

        self.caseSelector = qt.QComboBox()
        self.caseSelector.toolTip = "Select a case. A failed load stays on the current case."
        self.caseSelector.setSizeAdjustPolicy(
            qt.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.caseSelector.setMinimumContentsLength(24)
        form.addRow("Case", self.caseSelector)

        navigation = qt.QHBoxLayout()
        self.previousButton = qt.QPushButton("Previous")
        self.previousButton.toolTip = f"Load the previous case ({PREVIOUS_CASE_SHORTCUT})."
        self.nextButton = qt.QPushButton("Next")
        self.nextButton.toolTip = f"Load the next case ({NEXT_CASE_SHORTCUT})."
        navigation.addWidget(self.previousButton)
        navigation.addWidget(self.nextButton)
        form.addRow("Navigation", navigation)

        self.overlayCheckBox = qt.QCheckBox("Show segmentation")
        self.overlayCheckBox.checked = True
        self.overlayCheckBox.toolTip = (
            f"Show or hide every segment on all views ({TOGGLE_SEGMENTS_SHORTCUT})."
        )
        form.addRow("Overlay", self.overlayCheckBox)

        self.opacitySlider = ctk.ctkSliderWidget()
        self.opacitySlider.minimum = 0.0
        self.opacitySlider.maximum = 1.0
        self.opacitySlider.value = OVERLAY_OPACITY
        self.opacitySlider.singleStep = 0.05
        self.opacitySlider.decimals = 2
        self.opacitySlider.toolTip = "Opacity of the segmentation fill."
        form.addRow("Opacity", self.opacitySlider)

        legend = qt.QLabel(
            "T1sub = T1post − T1pre. Interpolation is off.\n"
            "1 NETC red   2 SNFH green   3 ET yellow   4 RC blue"
        )
        legend.wordWrap = True
        form.addRow(legend)

        self.statusLabel = qt.QLabel("Choose a spreadsheet and click Load.")
        self.statusLabel.wordWrap = True
        form.addRow("Status", self.statusLabel)

        self.layout.addStretch(1)

        browse_spreadsheet.connect("clicked()", self._browseSpreadsheet)
        browse_root.connect("clicked()", self._browseDatasetRoot)
        load_button.connect("clicked()", self.loadSpreadsheet)
        self.spreadsheetEdit.connect("returnPressed()", self.loadSpreadsheet)
        self.datasetRootEdit.connect("returnPressed()", self.loadSpreadsheet)
        self.caseSelector.connect("currentIndexChanged(int)", self.onCaseSelected)
        self.previousButton.connect("clicked()", self.loadPreviousCase)
        self.nextButton.connect("clicked()", self.loadNextCase)
        self.overlayCheckBox.connect("toggled(bool)", self.onOverlayToggled)
        self.opacitySlider.connect("valueChanged(double)", self.onOpacityChanged)

        self._installShortcuts()
        self._restoreSettings()
        self._updateNavigationButtons()
        if os.path.isfile(self.spreadsheetEdit.text):
            qt.QTimer.singleShot(0, self.loadSpreadsheet)

    def cleanup(self):
        self._removeShortcuts()
        if self.logic:
            self.logic.clear_loaded_case()

    def _settings(self):
        return qt.QSettings()

    def _restoreSettings(self):
        settings = self._settings()
        spreadsheet = settings.value(SETTINGS_SPREADSHEET_KEY)
        dataset_root = settings.value(SETTINGS_DATASET_ROOT_KEY)
        if spreadsheet and os.path.isfile(str(spreadsheet)):
            self.spreadsheetEdit.text = str(spreadsheet)
        else:
            self.spreadsheetEdit.text = DEFAULT_SPREADSHEET
        if dataset_root and os.path.isdir(str(dataset_root)):
            self.datasetRootEdit.text = str(dataset_root)

    def _saveSettings(self):
        settings = self._settings()
        settings.setValue(SETTINGS_SPREADSHEET_KEY, self.spreadsheetEdit.text)
        settings.setValue(SETTINGS_DATASET_ROOT_KEY, self.datasetRootEdit.text)

    def _browseSpreadsheet(self):
        start = self.spreadsheetEdit.text or os.path.dirname(DEFAULT_SPREADSHEET)
        selected = qt.QFileDialog.getOpenFileName(
            slicer.util.mainWindow(),
            "Select case spreadsheet",
            start,
            "CSV files (*.csv)",
        )
        if isinstance(selected, (list, tuple)):
            selected = selected[0]
        if not selected:
            return
        self.spreadsheetEdit.text = selected
        self.loadSpreadsheet()

    def _browseDatasetRoot(self):
        start = self.datasetRootEdit.text or os.path.dirname(DEFAULT_SPREADSHEET)
        selected = qt.QFileDialog.getExistingDirectory(
            slicer.util.mainWindow(),
            "Select dataset root",
            start,
        )
        if isinstance(selected, (list, tuple)):
            selected = selected[0]
        if not selected:
            return
        self.datasetRootEdit.text = selected

    def loadSpreadsheet(self):
        path = self.spreadsheetEdit.text.strip()
        try:
            cases = read_cases(path)
        except CaseLoadError as exc:
            self._showError(str(exc), "Could not load spreadsheet")
            return

        root = self.datasetRootEdit.text.strip()
        if not root:
            inferred = infer_dataset_root(path, cases[0].bids_study_dir)
            if inferred:
                root = inferred
                self.datasetRootEdit.text = inferred
        if not root and not os.path.isabs(cases[0].bids_study_dir):
            self._showError(
                "Set the dataset root to the directory that contains the relative "
                "bids_study_dir and segmentation_study_dir paths.",
                "Could not load spreadsheet",
            )
            return

        previous_key = None
        if self.loadedCaseIndex is not None and self.loadedCaseIndex < len(self.cases):
            previous_key = self.cases[self.loadedCaseIndex].key

        self.cases = cases
        self.logic.dataset_root = root

        previous_index = None
        target = 0
        if previous_key:
            for index, case in enumerate(cases):
                if case.key == previous_key:
                    previous_index = index
                    target = index
                    break
        # A failed load reverts here. The scene is not cleared until a new case
        # actually loads, so the case on screen stays put.
        self.loadedCaseIndex = previous_index

        self._updatingSelector = True
        self.caseSelector.clear()
        for case in cases:
            self.caseSelector.addItem(case_label(case))
        self.caseSelector.setCurrentIndex(target)
        self._updatingSelector = False
        self._saveSettings()
        self.onCaseSelected(target, force=True)

    def loadPreviousCase(self):
        index = self.caseSelector.currentIndex
        if index > 0:
            self.caseSelector.setCurrentIndex(index - 1)

    def loadNextCase(self):
        index = self.caseSelector.currentIndex
        if index < self.caseSelector.count - 1:
            self.caseSelector.setCurrentIndex(index + 1)

    def onCaseSelected(self, index: int, force: bool = False):
        if self._updatingSelector:
            return
        self._updateNavigationButtons()
        if index < 0 or index >= len(self.cases):
            return
        if index == self.loadedCaseIndex and not force:
            return

        self.logic.dataset_root = self.datasetRootEdit.text.strip()
        case = self.cases[index]
        try:
            self.logic.load_case(case)
        except Exception as exc:
            logger.exception("Could not load %s", case.title)
            self._rejectCaseChange(str(exc))
            return

        self.loadedCaseIndex = index
        self.statusLabel.text = (
            f"{index + 1} / {len(self.cases)}   {case_label(case)}\n"
            "T1sub = T1post − T1pre"
        )
        self._updateNavigationButtons()

    def onOverlayToggled(self, checked: bool):
        if self.logic:
            self.logic.set_overlay_visible(bool(checked))

    def onOpacityChanged(self, value: float):
        if self.logic:
            self.logic.set_overlay_opacity(float(value))

    def _rejectCaseChange(self, message: str):
        if self.loadedCaseIndex is not None and self.loadedCaseIndex < len(self.cases):
            current = self.cases[self.loadedCaseIndex]
            message = f"{message}\n\nStaying on {current.title}."
            self._updatingSelector = True
            self.caseSelector.setCurrentIndex(self.loadedCaseIndex)
            self._updatingSelector = False
        elif self.logic and self.logic.current_case is not None:
            message = f"{message}\n\nStaying on {self.logic.current_case.title}."
        self.statusLabel.text = message
        self._updateNavigationButtons()
        slicer.util.errorDisplay(message, windowTitle="Could not load case")

    def _showError(self, message: str, title: str):
        self.statusLabel.text = message
        slicer.util.errorDisplay(message, windowTitle=title)

    def _updateNavigationButtons(self):
        if not self.previousButton:
            return
        index = self.caseSelector.currentIndex
        count = self.caseSelector.count
        self.previousButton.enabled = count > 0 and index > 0
        self.nextButton.enabled = count > 0 and index < count - 1

    def _installShortcuts(self):
        main_window = slicer.util.mainWindow()
        if not main_window:
            return
        self._removeShortcuts()
        self.previousShortcut = self._makeShortcut(
            main_window,
            PREVIOUS_SHORTCUT_NAME,
            PREVIOUS_CASE_SHORTCUT,
            self.loadPreviousCase,
        )
        self.nextShortcut = self._makeShortcut(
            main_window,
            NEXT_SHORTCUT_NAME,
            NEXT_CASE_SHORTCUT,
            self.loadNextCase,
        )
        self.toggleSegmentsShortcut = self._makeShortcut(
            main_window,
            TOGGLE_SEGMENTS_SHORTCUT_NAME,
            TOGGLE_SEGMENTS_SHORTCUT,
            self.toggleSegmentVisibility,
        )

    def _makeShortcut(self, parent, object_name: str, key: str, callback):
        shortcut = qt.QShortcut(parent)
        shortcut.objectName = object_name
        shortcut.setKey(qt.QKeySequence(key))
        shortcut.setContext(qt.Qt.ApplicationShortcut)
        shortcut.connect("activated()", callback)
        return shortcut

    def _removeShortcuts(self):
        main_window = slicer.util.mainWindow() if SLICER_AVAILABLE else None
        names = {
            PREVIOUS_SHORTCUT_NAME,
            NEXT_SHORTCUT_NAME,
            TOGGLE_SEGMENTS_SHORTCUT_NAME,
        }
        if main_window:
            for shortcut in main_window.findChildren(qt.QShortcut):
                if shortcut.objectName in names:
                    shortcut.setParent(None)
                    shortcut.deleteLater()
        self.previousShortcut = None
        self.nextShortcut = None
        self.toggleSegmentsShortcut = None

    def toggleSegmentVisibility(self):
        if not self.overlayCheckBox:
            return
        self.overlayCheckBox.checked = not self.overlayCheckBox.checked


class SegmentationReviewLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        super().__init__()
        self.dataset_root = ""
        self.loaded_node_ids: List[str] = []
        self.displayed_volumes = []
        self.segmentation_node = None
        self.current_case: Optional[CaseRecord] = None
        self.overlay_opacity = OVERLAY_OPACITY
        self.overlay_visible = True
        self._assign_generation = 0

    @staticmethod
    def remove_managed_nodes():
        if not SLICER_AVAILABLE:
            return
        scene = slicer.mrmlScene
        nodes = []
        collection = scene.GetNodes()
        collection.InitTraversal()
        node = collection.GetNextItemAsObject()
        while node:
            if node.GetAttribute(MANAGED_NODE_ATTRIBUTE) == "1":
                nodes.append(node)
            node = collection.GetNextItemAsObject()
        for node in reversed(nodes):
            scene.RemoveNode(node)

    def clear_loaded_case(self):
        if not SLICER_AVAILABLE:
            return
        self._remove_ids(self.loaded_node_ids)
        self.loaded_node_ids = []
        self.displayed_volumes = []
        self.segmentation_node = None
        self.current_case = None

    def set_overlay_visible(self, visible: bool):
        self.overlay_visible = visible
        self._apply_overlay(self.segmentation_node)

    def set_overlay_opacity(self, opacity: float):
        self.overlay_opacity = opacity
        self._apply_overlay(self.segmentation_node)

    def load_case(self, case: CaseRecord):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This module must be run inside 3D Slicer.")

        # Resolve files and build the new volumes before touching the views, so a
        # missing image or a T1 shape mismatch leaves the current case on screen.
        files = find_case_files(case, self.dataset_root)
        pending_ids: List[str] = []
        # Unlink before loading. While views are linked, a volume change — including
        # the one Slicer makes when the previous case's volumes are removed — is
        # copied into every view, so they all show T1pre.
        self._unlink_views()
        try:
            t1pre = self._load_volume(files.t1pre, "T1pre", pending_ids)
            t1post = self._load_volume(files.t1post, "T1post", pending_ids)
            flair = self._load_volume(files.flair, "FLAIR", pending_ids)
            pre_shape = _volume_dimensions(t1pre)
            post_shape = _volume_dimensions(t1post)
            if pre_shape is None or post_shape is None:
                raise CaseLoadError(
                    f"{case.title}: T1-precontrast or T1-postcontrast has no image data."
                )
            shape_error = same_shape_error(pre_shape, post_shape, case.title)
            if shape_error:
                raise CaseLoadError(shape_error)

            t1sub = self._create_subtraction(t1pre, t1post, pending_ids)
            segmentation = self._load_segmentation(files.segmentation, case, pending_ids)
            volumes = [t1pre, t1post, t1sub, flair]
            self._ensure_layout()
            self._assign_volumes(volumes, link=False)
            self._apply_overlay(segmentation)
        except Exception:
            self._remove_ids(pending_ids)
            if self.displayed_volumes:
                try:
                    self._assign_volumes(self.displayed_volumes)
                except Exception:
                    logger.exception("Could not restore the previous case views")
            raise

        old_ids = self.loaded_node_ids
        self.loaded_node_ids = list(pending_ids)
        self.displayed_volumes = volumes
        self.segmentation_node = segmentation
        self.current_case = case
        self._remove_ids(old_ids)
        self._assign_volumes(volumes)
        self._schedule_volume_assignment(volumes)
        try:
            self._activate_window_level()
        except Exception:
            logger.exception("Could not activate window/level")

    def _track(self, node, pending_ids: List[str]):
        if node and node.GetID():
            node.SetAttribute(MANAGED_NODE_ATTRIBUTE, "1")
            pending_ids.append(node.GetID())

    def _remove_ids(self, node_ids: Sequence[str]):
        scene = slicer.mrmlScene
        for node_id in reversed(list(node_ids)):
            node = scene.GetNodeByID(node_id)
            if node:
                scene.RemoveNode(node)

    def _load_volume(self, path: str, name: str, pending_ids: List[str]):
        volume_node = slicer.util.loadVolume(path, {"show": False})
        if not volume_node:
            raise CaseLoadError(f"Could not load {name}: {path}")
        volume_node.SetName(name)
        self._disable_interpolation(volume_node)
        self._track(volume_node, pending_ids)
        return volume_node

    def _disable_interpolation(self, volume_node):
        display_node = volume_node.GetDisplayNode()
        if not display_node:
            volume_node.CreateDefaultDisplayNodes()
            display_node = volume_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)

    def _create_subtraction(self, t1pre_node, t1post_node, pending_ids: List[str]):
        pre = slicer.util.arrayFromVolume(t1pre_node)
        post = slicer.util.arrayFromVolume(t1post_node)
        difference = post.astype(np.float32) - pre.astype(np.float32)
        subtraction = slicer.modules.volumes.logic().CloneVolume(t1pre_node, "T1sub")
        slicer.util.updateVolumeFromArray(subtraction, difference)
        subtraction.SetName("T1sub")
        self._disable_interpolation(subtraction)
        self._set_subtraction_window(subtraction, difference)
        self._track(subtraction, pending_ids)
        return subtraction

    def _set_subtraction_window(self, volume_node, difference):
        display_node = volume_node.GetDisplayNode()
        if not display_node:
            return
        finite = difference[np.isfinite(difference)]
        if finite.size == 0:
            low, high = 0.0, 1.0
        else:
            low = float(np.percentile(finite, 1))
            high = float(np.percentile(finite, 99))
            if high <= low:
                low = float(np.min(finite))
                high = float(np.max(finite))
            if high <= low:
                high = low + 1.0
        display_node.SetAutoWindowLevel(False)
        display_node.SetWindow(high - low)
        display_node.SetLevel((high + low) / 2.0)

    def _load_segmentation(self, path: str, case: CaseRecord, pending_ids: List[str]):
        segmentation = slicer.util.loadSegmentation(path, {"show": False})
        if segmentation:
            segmentation.SetName(f"{case.title} segmentation")
            self._track(segmentation, pending_ids)
            self._configure_segmentation(segmentation, visible=False)
            return segmentation

        labelmap = slicer.util.loadLabelVolume(path, {"show": False})
        if not labelmap:
            raise CaseLoadError(f"{case.title}: could not load segmentation {path}.")
        try:
            segmentation = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode",
                f"{case.title} segmentation",
            )
            segmentation.CreateDefaultDisplayNodes()
            self._track(segmentation, pending_ids)
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmap,
                segmentation,
            )
        finally:
            slicer.mrmlScene.RemoveNode(labelmap)
        self._configure_segmentation(segmentation, visible=False)
        return segmentation

    def _configure_segmentation(self, segmentation_node, visible: bool):
        if not segmentation_node.GetDisplayNode():
            segmentation_node.CreateDefaultDisplayNodes()
        display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            return
        display_node.RemoveAllViewNodeIDs()
        display_node.SetVisibility(visible)
        display_node.SetVisibility2D(visible)
        display_node.SetVisibility3D(False)
        display_node.SetVisibility2DFill(True)
        display_node.SetVisibility2DOutline(True)
        display_node.SetOpacity2DOutline(1.0)

        segments_by_label = {
            label: (name, color) for label, name, color in SEGMENT_DEFINITIONS
        }
        segmentation = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)
        for index in range(segment_ids.GetNumberOfValues()):
            segment_id = segment_ids.GetValue(index)
            segment = segmentation.GetSegment(segment_id)
            if not segment:
                continue
            definition = segments_by_label.get(segment.GetLabelValue())
            if not definition:
                continue
            name, color = definition
            segment.SetName(name)
            segment.SetColor(*color)
            display_node.SetSegmentVisibility(segment_id, True)

    def _apply_overlay(self, segmentation_node):
        if not segmentation_node:
            return
        display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            return
        visible = self.overlay_visible
        display_node.SetVisibility(visible)
        display_node.SetVisibility2D(visible)
        display_node.SetVisibility2DFill(True)
        display_node.SetOpacity2DFill(self.overlay_opacity if visible else 0.0)
        display_node.SetVisibility2DOutline(visible)
        display_node.SetOpacity2DOutline(1.0 if visible else 0.0)

    def _ensure_layout(self):
        layout_manager = slicer.app.layoutManager()
        layout_node = layout_manager.layoutLogic().GetLayoutNode()
        if not layout_node.GetLayoutDescription(CUSTOM_LAYOUT_ID):
            layout_node.AddLayoutDescription(CUSTOM_LAYOUT_ID, FOUR_UP_LAYOUT)
        # Reapplying the current layout recreates the slice viewers and puts the
        # selected volume into every view. Only switch when the layout is different.
        if layout_node.GetViewArrangement() != CUSTOM_LAYOUT_ID:
            layout_manager.setLayout(CUSTOM_LAYOUT_ID)

    def _unlink_views(self):
        layout_manager = slicer.app.layoutManager()
        if not layout_manager:
            return
        for view_name, _, _ in VIEW_SPECS:
            slice_widget = layout_manager.sliceWidget(view_name)
            if not slice_widget:
                continue
            composite = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite.SetInteracting(0)
            composite.SetLinkedControl(False)
            composite.SetHotLinkedControl(False)
            composite.SetDoPropagateVolumeSelection(False)

    def _assign_volumes(self, volume_nodes, link: bool = True):
        layout_manager = slicer.app.layoutManager()
        slice_widgets = []
        for view_name, _, _ in VIEW_SPECS:
            slice_widget = layout_manager.sliceWidget(view_name)
            if not slice_widget:
                raise CaseLoadError(f"Slice view '{view_name}' is not available.")
            slice_widgets.append(slice_widget)

        # Set every background while unlinked. A linked background change is
        # broadcast to the other views.
        for index, slice_widget in enumerate(slice_widgets):
            _, label, color = VIEW_SPECS[index]
            composite = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite.SetInteracting(0)
            composite.SetLinkedControl(False)
            composite.SetHotLinkedControl(False)
            composite.SetDoPropagateVolumeSelection(False)
            volume = volume_nodes[index] if index < len(volume_nodes) else None
            if volume:
                self._disable_interpolation(volume)
            composite.SetBackgroundVolumeID(volume.GetID() if volume else None)
            composite.SetForegroundVolumeID(None)
            composite.SetForegroundOpacity(0.0)
            composite.SetLabelVolumeID(None)

            slice_node = slice_widget.mrmlSliceNode()
            slice_node.SetOrientationToAxial()
            slice_node.SetLayoutLabel(label)
            slice_node.SetLayoutColor(*color)
            slice_widget.sliceLogic().FitSliceToAll()

        if not link:
            return
        for slice_widget in slice_widgets:
            composite = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite.SetDoPropagateVolumeSelection(False)
            composite.SetLinkedControl(True)
            composite.SetHotLinkedControl(False)

    def _schedule_volume_assignment(self, volume_nodes):
        # Node removal notifies the slice controllers on the next event-loop turn
        # and can overwrite the backgrounds. Put the four volumes back after that.
        self._assign_generation += 1
        generation = self._assign_generation
        node_ids = [node.GetID() for node in volume_nodes if node]

        def reapply():
            if generation != self._assign_generation:
                return
            nodes = []
            for node_id in node_ids:
                node = slicer.mrmlScene.GetNodeByID(node_id)
                if not node:
                    return
                nodes.append(node)
            self._assign_volumes(nodes)

        qt.QTimer.singleShot(0, reapply)

    def _activate_window_level(self):
        interaction = slicer.app.applicationLogic().GetInteractionNode()
        interaction.SetCurrentInteractionMode(
            slicer.vtkMRMLInteractionNode.AdjustWindowLevel
        )


def _volume_dimensions(volume_node):
    image_data = volume_node.GetImageData()
    if image_data is None:
        return None
    return tuple(int(value) for value in image_data.GetDimensions())
