YOUR_INITIALS = "BK"

IMAGES_ROOT = (
    "/Users/brian/repos/pediatric-glioma-segmentation/data/datasets/derivatives/"
    "preprocessed/images"
)
SEGMENTATIONS_ROOT = (
    "/Users/brian/repos/pediatric-glioma-segmentation/data/datasets/derivatives/"
    "preprocessed/ground-truth-segs"
)
PARTICIPANTS_CSV_PATH = (
    "/Users/brian/repos/slicer-plugin/pediatric-glioma-participants.csv"
)
SEGMENT_LABEL_NAMES = {
    1: "enhancing tissue",
    2: "non-enhancing tumor core",
    3: "peritumoral edema",
}

SEGMENTATION_DISPLAY_NAME = "glioma segmentation"
SUBTRACTION_DISPLAY_NAME = "T1 subtraction"
CUSTOM_LAYOUT_ID = 1401
FOUR_SLICE_VIEW_NAMES = ["Red", "Yellow", "Green", "Compare1"]
MODALITY_RULES = [
    ("ce-gadolinium_T1w", "T1post"),
    ("_T1w", "T1pre"),
    ("_T2w", "T2"),
    ("_T2", "T2"),
    ("_FLAIR", "FLAIR"),
]

import csv
import os
from dataclasses import dataclass
from typing import List

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


@dataclass(frozen=True)
class SessionRecord:
    subject_id: str
    session_id: str
    image_paths: List[str]
    segmentation_path: str

    @property
    def session_key(self) -> str:
        return f"{self.subject_id}/{self.session_id}"

    @property
    def display_name(self) -> str:
        return f"{self.subject_id} | {self.session_id}"


def _list_subdirectories(path: str, prefix: str) -> List[str]:
    if not os.path.isdir(path):
        return []

    return sorted(
        entry
        for entry in os.listdir(path)
        if entry.startswith(prefix) and os.path.isdir(os.path.join(path, entry))
    )


def _list_nifti_files(path: str) -> List[str]:
    if not os.path.isdir(path):
        return []

    nii_files = []
    for entry in sorted(os.listdir(path)):
        if entry.endswith(".nii") or entry.endswith(".nii.gz"):
            nii_files.append(os.path.join(path, entry))
    return nii_files


def _modality_sort_key(path: str) -> tuple:
    basename = os.path.basename(path)
    for priority, (marker, _) in enumerate(MODALITY_RULES):
        if marker in basename:
            return (priority, basename)
    return (len(MODALITY_RULES), basename)


def _display_name_for_image_path(image_path: str) -> str:
    basename = os.path.basename(image_path)
    for marker, display_name in MODALITY_RULES:
        if marker in basename:
            return display_name
    return os.path.splitext(os.path.splitext(basename)[0])[0]


def _displayed_volume_names(use_subtraction: bool) -> List[str]:
    return [
        "T1post",
        "T1pre",
        "FLAIR",
        SUBTRACTION_DISPLAY_NAME if use_subtraction else "T2",
    ]


def _compact_path(path: str, keep_parts: int = 3) -> str:
    path_parts = [part for part in path.split(os.sep) if part]
    if len(path_parts) <= keep_parts:
        return path
    return os.sep.join(["...", *path_parts[-keep_parts:]])


def _normalize_assignee(value: str) -> str:
    return (value or "").strip().upper()


def _read_assigned_session_keys(
    participants_csv_path: str,
    assignee_initials: str,
) -> List[tuple]:
    if not os.path.isfile(participants_csv_path):
        return []

    assigned_session_keys = []
    seen_session_keys = set()
    target_assignee = _normalize_assignee(assignee_initials)

    with open(participants_csv_path, newline="", encoding="utf-8-sig") as csv_file:
        for row in csv.DictReader(csv_file):
            if _normalize_assignee(row.get("assignee")) != target_assignee:
                continue

            subject_id = (row.get("participant_id") or "").strip()
            session_id = (row.get("session_id") or "").strip()
            if not subject_id or not session_id:
                continue

            session_key = (subject_id, session_id)
            if session_key in seen_session_keys:
                continue

            assigned_session_keys.append(session_key)
            seen_session_keys.add(session_key)

    return assigned_session_keys


def discover_sessions(
    images_root: str,
    segmentations_root: str,
    participants_csv_path: str = PARTICIPANTS_CSV_PATH,
    assignee_initials: str = YOUR_INITIALS,
) -> List[SessionRecord]:
    sessions: List[SessionRecord] = []

    for subject_id, session_id in _read_assigned_session_keys(
        participants_csv_path,
        assignee_initials,
    ):
        image_anat_dir = os.path.join(images_root, subject_id, session_id, "anat")
        image_paths = _list_nifti_files(image_anat_dir)
        if len(image_paths) != 4:
            continue

        segmentation_anat_dir = os.path.join(
            segmentations_root,
            subject_id,
            session_id,
            "anat",
        )
        segmentation_paths = [
            path
            for path in _list_nifti_files(segmentation_anat_dir)
            if "_dseg" in os.path.basename(path)
        ]
        if len(segmentation_paths) != 1:
            continue

        sessions.append(
            SessionRecord(
                subject_id=subject_id,
                session_id=session_id,
                image_paths=sorted(image_paths, key=_modality_sort_key),
                segmentation_path=segmentation_paths[0],
            )
        )

    return sessions

class PediatricGliomaSegmentationBrowser(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Pediatric Glioma Segmentation Browser"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Cursor"]
        self.parent.helpText = (
            "Browse preprocessed pediatric glioma sessions, load four modalities, "
            "and load the corresponding segmentation for rapid review/editing."
        )
        self.parent.acknowledgementText = ""


class PediatricGliomaSegmentationBrowserWidget(
    ScriptedLoadableModuleWidget, VTKObservationMixin
):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.refreshButton = None
        self.sessionSelector = None
        self.statusLabel = None
        self.pathsLabel = None

    def setup(self):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This module must be run inside 3D Slicer.")

        super().setup()
        self.logic = PediatricGliomaSegmentationBrowserLogic()

        collapsibleButton = ctk.ctkCollapsibleButton()
        collapsibleButton.text = "Case Browser"
        self.layout.addWidget(collapsibleButton)

        formLayout = qt.QFormLayout(collapsibleButton)

        self.pathsLabel = qt.QLabel(
            "Images: "
            f"{_compact_path(IMAGES_ROOT)}\n"
            "Segmentations: "
            f"{_compact_path(SEGMENTATIONS_ROOT)}\n"
            "Participants CSV: "
            f"{os.path.basename(PARTICIPANTS_CSV_PATH)}\n"
            f"Assignee initials: {YOUR_INITIALS}"
        )
        self.pathsLabel.wordWrap = True
        self.pathsLabel.maximumWidth = 320
        self.pathsLabel.toolTip = (
            f"Images: {IMAGES_ROOT}\n"
            f"Segmentations: {SEGMENTATIONS_ROOT}\n"
            f"Participants CSV: {PARTICIPANTS_CSV_PATH}\n"
            f"Assignee initials: {YOUR_INITIALS}"
        )
        formLayout.addRow("Dataset roots", self.pathsLabel)

        self.refreshButton = qt.QPushButton("Refresh sessions")
        self.refreshButton.toolTip = (
            "Rescan the hard-coded dataset roots and rebuild the session list."
        )
        formLayout.addRow(self.refreshButton)

        self.sessionSelector = qt.QComboBox()
        self.sessionSelector.toolTip = (
            "Selecting a session unloads the prior case loaded by this module and "
            "loads the new session."
        )
        formLayout.addRow("Session", self.sessionSelector)

        navigationLayout = qt.QHBoxLayout()
        self.previousButton = qt.QPushButton("Previous")
        self.previousButton.toolTip = "Load the previous valid session."
        self.nextButton = qt.QPushButton("Next")
        self.nextButton.toolTip = "Load the next valid session."
        navigationLayout.addWidget(self.previousButton)
        navigationLayout.addWidget(self.nextButton)
        formLayout.addRow("Navigation", navigationLayout)

        self.statusLabel = qt.QLabel("")
        self.statusLabel.wordWrap = True
        formLayout.addRow("Status", self.statusLabel)

        self.layout.addStretch(1)

        self.refreshButton.connect("clicked()", self.refreshSessions)
        self.previousButton.connect("clicked()", self.loadPreviousSession)
        self.nextButton.connect("clicked()", self.loadNextSession)
        self.sessionSelector.connect("currentIndexChanged(int)", self.onSessionSelected)

        self.refreshSessions()

    def refreshSessions(self):
        previous_key = None
        if self.sessionSelector.count:
            previous_session = self.sessionSelector.itemData(
                self.sessionSelector.currentIndex
            )
            previous_key = previous_session.session_key if previous_session else None

        self.sessionSelector.blockSignals(True)
        self.sessionSelector.clear()

        sessions = self.logic.refreshSessions()
        for session in sessions:
            self.sessionSelector.addItem(session.display_name, session)

        self.sessionSelector.blockSignals(False)

        if not sessions:
            self.statusLabel.text = (
                "No valid assigned sessions found for "
                f"`{YOUR_INITIALS}`. A valid session must appear in "
                "`pediatric-glioma-participants.csv` and contain exactly four "
                "NIfTI images plus one `_dseg` segmentation."
            )
            self.updateNavigationButtons()
            return

        restored_index = 0
        if previous_key:
            for index, session in enumerate(sessions):
                if session.session_key == previous_key:
                    restored_index = index
                    break

        self.sessionSelector.setCurrentIndex(restored_index)
        self.statusLabel.text = f"Discovered {len(sessions)} valid sessions."
        self.onSessionSelected(restored_index)

    def loadPreviousSession(self):
        current_index = self.sessionSelector.currentIndex
        if current_index > 0:
            self.sessionSelector.setCurrentIndex(current_index - 1)

    def loadNextSession(self):
        current_index = self.sessionSelector.currentIndex
        if current_index < self.sessionSelector.count - 1:
            self.sessionSelector.setCurrentIndex(current_index + 1)

    def updateNavigationButtons(self):
        current_index = self.sessionSelector.currentIndex
        session_count = self.sessionSelector.count
        has_sessions = session_count > 0
        self.previousButton.enabled = has_sessions and current_index > 0
        self.nextButton.enabled = has_sessions and current_index < session_count - 1

    def onSessionSelected(self, index: int):
        self.updateNavigationButtons()
        if index < 0:
            return

        session = self.sessionSelector.itemData(index)
        if not session:
            return

        try:
            self.logic.loadSession(session)
            self.statusLabel.text = (
                f"Loaded {session.display_name} "
                f"({index + 1}/{self.sessionSelector.count}) with "
                f"{len(session.image_paths)} images and 1 segmentation."
            )
        except Exception as exc:
            self.statusLabel.text = f"Failed to load {session.display_name}: {exc}"
            raise


class PediatricGliomaSegmentationBrowserLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        super().__init__()
        self.sessions: List[SessionRecord] = []
        self.loadedNodeIDs: List[str] = []

    def refreshSessions(self) -> List[SessionRecord]:
        self.sessions = discover_sessions(IMAGES_ROOT, SEGMENTATIONS_ROOT)
        return self.sessions

    def loadSession(self, session: SessionRecord):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This logic must be run inside 3D Slicer.")

        self._removePreviouslyLoadedNodes()
        self._ensureFourSliceLayout()

        volume_nodes = []
        for image_path in session.image_paths:
            volume_node = self._loadVolume(image_path)
            volume_nodes.append(volume_node)

        segmentation_node = self._loadSegmentation(session.segmentation_path)
        self._trackNode(segmentation_node)
        self._configureSegmentationDisplay(segmentation_node)
        self._selectSegmentationForEditing(segmentation_node, volume_nodes)
        display_volume_nodes = self._buildDisplayVolumeNodes(volume_nodes, session)
        self._assignVolumesToViews(display_volume_nodes)
        self._activateWindowLevelTool()

    def _trackNode(self, node):
        if node and node.GetID():
            self.loadedNodeIDs.append(node.GetID())

    def _removePreviouslyLoadedNodes(self):
        scene = slicer.mrmlScene
        for node_id in reversed(self.loadedNodeIDs):
            node = scene.GetNodeByID(node_id)
            if node:
                scene.RemoveNode(node)
        self.loadedNodeIDs = []

    def _loadVolume(self, image_path: str):
        volume_node = slicer.util.loadVolume(image_path, {"show": False})
        if not volume_node:
            raise RuntimeError(f"Could not load image: {image_path}")
        volume_node.SetName(_display_name_for_image_path(image_path))
        display_node = volume_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        self._trackNode(volume_node)
        return volume_node

    def _loadSegmentation(self, segmentation_path: str):
        segmentation_node = slicer.util.loadSegmentation(
            segmentation_path,
            {"show": False},
        )
        if segmentation_node:
            segmentation_node.SetName(SEGMENTATION_DISPLAY_NAME)
            self._renameSegmentsFromLabelMap(segmentation_node)
            return segmentation_node

        labelmap_node = slicer.util.loadLabelVolume(segmentation_path, {"show": False})
        if not labelmap_node:
            raise RuntimeError(f"Could not load segmentation: {segmentation_path}")

        self._trackNode(labelmap_node)
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode",
            SEGMENTATION_DISPLAY_NAME,
        )
        segmentation_node.CreateDefaultDisplayNodes()
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelmap_node,
            segmentation_node,
        )
        slicer.mrmlScene.RemoveNode(labelmap_node)
        self.loadedNodeIDs = [
            node_id for node_id in self.loadedNodeIDs if node_id != labelmap_node.GetID()
        ]
        self._renameSegmentsFromLabelMap(segmentation_node)
        return segmentation_node

    def _renameSegmentsFromLabelMap(self, segmentation_node):
        segmentation = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)
        for segment_index in range(segment_ids.GetNumberOfValues()):
            segment = segmentation.GetSegment(segment_ids.GetValue(segment_index))
            if not segment:
                continue
            label_value = segment.GetLabelValue()
            if label_value in SEGMENT_LABEL_NAMES:
                segment.SetName(SEGMENT_LABEL_NAMES[label_value])

    def _configureSegmentationDisplay(self, segmentation_node):
        display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            segmentation_node.CreateDefaultDisplayNodes()
            display_node = segmentation_node.GetDisplayNode()

        display_node.SetVisibility2D(True)
        display_node.SetVisibility3D(True)
        display_node.SetOpacity2DFill(0.35)
        display_node.SetOpacity2DOutline(1.0)

    def _buildDisplayVolumeNodes(self, volume_nodes, session: SessionRecord):
        volume_nodes_by_name = {volume_node.GetName(): volume_node for volume_node in volume_nodes}

        t1post_node = volume_nodes_by_name.get("T1post")
        t1pre_node = volume_nodes_by_name.get("T1pre")
        flair_node = volume_nodes_by_name.get("FLAIR")
        t2_node = volume_nodes_by_name.get("T2")

        missing_modalities = [
            modality_name
            for modality_name, volume_node in (
                ("T1post", t1post_node),
                ("T1pre", t1pre_node),
                ("FLAIR", flair_node),
                ("T2", t2_node),
            )
            if volume_node is None
        ]
        if missing_modalities:
            raise RuntimeError(
                "Missing expected modality volumes: " + ", ".join(missing_modalities)
            )

        subtraction_node = self._createSubtractionVolumeNode(
            t1post_node,
            t1pre_node,
            session,
        )
        display_nodes_by_name = {
            "T1post": t1post_node,
            "T1pre": t1pre_node,
            "FLAIR": flair_node,
            SUBTRACTION_DISPLAY_NAME if subtraction_node else "T2": subtraction_node or t2_node,
        }

        return [
            display_nodes_by_name[display_name]
            for display_name in _displayed_volume_names(bool(subtraction_node))
        ]

    def _createSubtractionVolumeNode(self, t1post_node, t1pre_node, session: SessionRecord):
        mismatch_reason = self._volumeGeometryMismatchReason(t1post_node, t1pre_node)
        if mismatch_reason:
            slicer.util.warningDisplay(
                "Could not create the subtraction image for "
                f"{session.display_name}: {mismatch_reason}. "
                "Displaying T2 instead.",
                windowTitle="Subtraction image unavailable",
            )
            return None

        subtraction_array = (
            slicer.util.arrayFromVolume(t1post_node).astype(np.float32)
            - slicer.util.arrayFromVolume(t1pre_node).astype(np.float32)
        )
        subtraction_node = slicer.modules.volumes.logic().CloneVolume(
            t1post_node,
            SUBTRACTION_DISPLAY_NAME,
        )
        slicer.util.updateVolumeFromArray(subtraction_node, subtraction_array)
        subtraction_node.SetName(SUBTRACTION_DISPLAY_NAME)
        subtraction_display_node = subtraction_node.GetDisplayNode()
        if subtraction_display_node:
            subtraction_display_node.SetInterpolate(False)
        self._trackNode(subtraction_node)
        return subtraction_node

    def _volumeGeometryMismatchReason(self, volume_node_a, volume_node_b):
        image_data_a = volume_node_a.GetImageData()
        image_data_b = volume_node_b.GetImageData()
        if image_data_a is None or image_data_b is None:
            return "one or both source volumes are missing image data"

        if image_data_a.GetDimensions() != image_data_b.GetDimensions():
            return (
                f"shape mismatch ({image_data_a.GetDimensions()} vs "
                f"{image_data_b.GetDimensions()})"
            )

        if not np.allclose(volume_node_a.GetSpacing(), volume_node_b.GetSpacing()):
            return (
                f"spacing mismatch ({volume_node_a.GetSpacing()} vs "
                f"{volume_node_b.GetSpacing()})"
            )

        if not np.allclose(volume_node_a.GetOrigin(), volume_node_b.GetOrigin()):
            return (
                f"origin mismatch ({volume_node_a.GetOrigin()} vs "
                f"{volume_node_b.GetOrigin()})"
            )

        ijk_to_ras_matrix_a = vtk.vtkMatrix4x4()
        ijk_to_ras_matrix_b = vtk.vtkMatrix4x4()
        volume_node_a.GetIJKToRASMatrix(ijk_to_ras_matrix_a)
        volume_node_b.GetIJKToRASMatrix(ijk_to_ras_matrix_b)
        matrix_elements_a = [
            ijk_to_ras_matrix_a.GetElement(row, column)
            for row in range(4)
            for column in range(4)
        ]
        matrix_elements_b = [
            ijk_to_ras_matrix_b.GetElement(row, column)
            for row in range(4)
            for column in range(4)
        ]
        if not np.allclose(matrix_elements_a, matrix_elements_b):
            return "IJK-to-RAS geometry mismatch"

        return None

    def _ensureFourSliceLayout(self):
        layout_node = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        if layout_node.GetLayoutDescription(CUSTOM_LAYOUT_ID):
            slicer.app.layoutManager().setLayout(CUSTOM_LAYOUT_ID)
            return

        layout_description = """
<layout type="vertical">
  <item splitSize="500">
    <layout type="horizontal">
      <item splitSize="500">
        <view class="vtkMRMLSliceNode" singletontag="Red">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">A</property>
          <property name="viewcolor" action="default">#F34A33</property>
        </view>
      </item>
      <item splitSize="500">
        <view class="vtkMRMLSliceNode" singletontag="Yellow">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">B</property>
          <property name="viewcolor" action="default">#EDD54C</property>
        </view>
      </item>
    </layout>
  </item>
  <item splitSize="500">
    <layout type="horizontal">
      <item splitSize="500">
        <view class="vtkMRMLSliceNode" singletontag="Green">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">C</property>
          <property name="viewcolor" action="default">#6EB04B</property>
        </view>
      </item>
      <item splitSize="500">
        <view class="vtkMRMLSliceNode" singletontag="Compare1">
          <property name="orientation" action="default">Axial</property>
          <property name="viewlabel" action="default">Blue</property>
          <property name="viewcolor" action="default">#4C7DFF</property>
        </view>
      </item>
    </layout>
  </item>
</layout>
"""
        layout_node.AddLayoutDescription(CUSTOM_LAYOUT_ID, layout_description)
        slicer.app.layoutManager().setLayout(CUSTOM_LAYOUT_ID)

    def _assignVolumesToViews(self, volume_nodes):
        layout_manager = slicer.app.layoutManager()
        for view_name, volume_node in zip(FOUR_SLICE_VIEW_NAMES, volume_nodes):
            slice_widget = layout_manager.sliceWidget(view_name)
            if not slice_widget:
                continue

            composite_node = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite_node.SetDoPropagateVolumeSelection(False)
            composite_node.SetLinkedControl(True)
            composite_node.SetHotLinkedControl(True)
            composite_node.SetBackgroundVolumeID(volume_node.GetID())
            composite_node.SetForegroundVolumeID(None)
            composite_node.SetLabelVolumeID(None)

            slice_node = slice_widget.mrmlSliceNode()
            slice_node.SetOrientationToAxial()
            slice_widget.sliceLogic().FitSliceToAll()

    def _activateWindowLevelTool(self):
        interaction_node = slicer.app.applicationLogic().GetInteractionNode()
        interaction_node.SetCurrentInteractionMode(
            slicer.vtkMRMLInteractionNode.AdjustWindowLevel
        )

    def _selectSegmentationForEditing(self, segmentation_node, volume_nodes):
        if not hasattr(slicer.modules, "segmenteditor"):
            return

        segment_editor_module = slicer.modules.segmenteditor
        widget_representation = segment_editor_module.widgetRepresentation()
        if not widget_representation:
            return

        editor_widget = widget_representation.self().editor
        if hasattr(editor_widget, "setAutoShowSourceVolumeNode"):
            editor_widget.setAutoShowSourceVolumeNode(False)
        elif hasattr(editor_widget, "setAutoShowMasterVolumeNode"):
            editor_widget.setAutoShowMasterVolumeNode(False)
        editor_widget.setSegmentationNode(segmentation_node)
        if volume_nodes:
            editor_widget.setSourceVolumeNode(
                volume_nodes[_preferred_edit_volume_index(volume_nodes)]
            )


def _preferred_edit_volume_index(volume_nodes) -> int:
    for preferred_modality in ("T1post", "T1pre"):
        for index, volume_node in enumerate(volume_nodes):
            if preferred_modality in volume_node.GetName():
                return index
    return 0
