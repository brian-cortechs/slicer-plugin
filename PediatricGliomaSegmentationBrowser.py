import fnmatch
import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


default_config_path = os.path.join(
    os.path.dirname(__file__),
    "peds-glioma-segs.json",
)
if not os.path.isfile(default_config_path):
    default_config_path = None

loaded_config_path = default_config_path or ""
loaded_config = None
managed_node_attribute = "PediatricGliomaSegmentationBrowser.ManagedNode"
custom_layout_id = 1401
four_slice_view_names = ["Red", "Yellow", "Green", "Compare1"]
toggle_segmentation_visibility_shortcut = "Shift+V"
previous_segmentation_shortcut = "["
next_segmentation_shortcut = "]"
undo_shortcut_object_name = "PediatricGliomaSegmentationBrowserUndoShortcut"
redo_shortcut_object_name = "PediatricGliomaSegmentationBrowserRedoShortcut"
subtraction_default_display_name = "T1 subtraction"
config_file_filter = "JSON files (*.json)"
bids_subject_session_pattern = re.compile(r"(sub-[^_]+)_(ses-[^_]+)")


@dataclass(frozen=True)
class ImageDefinition:
    display_name: str
    pattern: str
    pattern_type: str
    display: bool = True


@dataclass(frozen=True)
class SegmentDefinition:
    label: int
    name: str
    color: Optional[List[float]] = None
    visible: bool = True


@dataclass(frozen=True)
class SessionSegmentation:
    display_name: str
    path: str
    visible: bool
    display_type: str
    segments: List[SegmentDefinition] = field(default_factory=list)


@dataclass(frozen=True)
class SegmentationDefinition:
    folders_glob: str
    subfolder_glob: str
    display_name: str
    pattern: str
    pattern_type: str
    visible: bool
    display_type: str
    segments: List[SegmentDefinition] = field(default_factory=list)
    required: bool = True


@dataclass(frozen=True)
class SubtractionDefinition:
    display_name: str
    minuend: str       # display_name of the image to subtract from (e.g. T1post)
    subtrahend: str    # display_name of the image to subtract (e.g. T1pre)


@dataclass(frozen=True)
class EditingDefinition:
    folders_glob: str
    subfolder_glob: str
    pattern: str
    pattern_type: str
    output_folder: str
    display_name: str
    display_type: str
    segments: List[SegmentDefinition] = field(default_factory=list)
    editing_sources: List[str] = field(default_factory=list)
    subtraction: Optional[SubtractionDefinition] = None


@dataclass(frozen=True)
class SessionRecord:
    subject_id: str
    session_id: str
    image_paths_by_name: Dict[str, str]
    display_image_names: List[str]
    segmentations: List[SessionSegmentation] = field(default_factory=list)
    editable_path: Optional[str] = None

    @property
    def session_key(self) -> str:
        return f"{self.subject_id}/{self.session_id}"

    @property
    def display_name(self) -> str:
        return f"{self.subject_id} | {self.session_id}"


def _normalize_color(color_value):
    if color_value is None:
        return None
    if not isinstance(color_value, list) or len(color_value) != 3:
        raise RuntimeError("Segment colors must be RGB lists with 3 values.")
    if any(component > 1.0 for component in color_value):
        return [float(component) / 255.0 for component in color_value]
    return [float(component) for component in color_value]


def _normalize_pattern(config_entry: dict, context: str) -> tuple:
    regex_pattern = config_entry.get("filename_regex")
    glob_pattern = config_entry.get("filename")
    if regex_pattern and glob_pattern:
        raise RuntimeError(
            f"{context} should define only one of 'filename_regex' or 'filename'."
        )
    if regex_pattern:
        re.compile(regex_pattern)
        return regex_pattern, "regex"
    if glob_pattern:
        return glob_pattern, "glob"
    raise RuntimeError(
        f"{context} is missing a filename rule. Use 'filename_regex' or 'filename'."
    )


def _normalize_image_section(config_values: dict) -> dict:
    if isinstance(config_values.get("images"), dict):
        image_section = config_values["images"]
        image_folders = image_section.get("folders")
        image_subfolder = image_section.get("subfolder", "")
        image_items = image_section.get("items", [])
    else:
        image_folders = config_values.get("image_folders")
        image_subfolder = config_values.get("image_subfolder", "")
        image_items = config_values.get("images", [])

    if not image_folders:
        raise RuntimeError("Config is missing image folder settings.")
    if not image_items:
        raise RuntimeError("Config must define at least one image rule.")

    image_definitions = []
    for index, image_item in enumerate(image_items):
        pattern, pattern_type = _normalize_pattern(image_item, f"images[{index}]")
        image_definitions.append(
            ImageDefinition(
                display_name=image_item["display_name"],
                pattern=pattern,
                pattern_type=pattern_type,
                display=bool(image_item.get("display", True)),
            )
        )

    displayed_image_names = [
        image_definition.display_name
        for image_definition in image_definitions
        if image_definition.display
    ]
    if not displayed_image_names:
        raise RuntimeError("At least one image must have display=true.")
    if len(displayed_image_names) > len(four_slice_view_names):
        raise RuntimeError(
            "This browser layout supports at most "
            f"{len(four_slice_view_names)} displayed images."
        )

    return {
        "folders_glob": image_folders,
        "subfolder_glob": image_subfolder,
        "definitions": image_definitions,
        "displayed_names": displayed_image_names,
    }


def _normalize_segment_definitions(config_values: dict) -> List[SegmentationDefinition]:
    segmentations_config = config_values.get("segmentations", [])
    if isinstance(segmentations_config, dict):
        segmentations_config = [segmentations_config]

    segmentation_definitions = []
    for index, segmentation_item in enumerate(segmentations_config):
        pattern, pattern_type = _normalize_pattern(
            segmentation_item,
            f"segmentations[{index}]",
        )
        segment_definitions = []
        for segment_index, segment_item in enumerate(
            segmentation_item.get("segments", [])
        ):
            try:
                label_value = int(segment_item["label"])
            except Exception as exc:
                raise RuntimeError(
                    f"segmentations[{index}].segments[{segment_index}].label "
                    "must be an integer."
                ) from exc
            segment_definitions.append(
                SegmentDefinition(
                    label=label_value,
                    name=segment_item["name"],
                    color=_normalize_color(segment_item.get("color")),
                    visible=bool(segment_item.get("visible", True)),
                )
            )

        segmentation_definitions.append(
            SegmentationDefinition(
                folders_glob=(
                    segmentation_item.get("segmentation_folders")
                    or segmentation_item.get("folders")
                ),
                subfolder_glob=(
                    segmentation_item.get("segmentation_subfolder")
                    or segmentation_item.get("subfolder", "")
                ),
                display_name=segmentation_item["display_name"],
                pattern=pattern,
                pattern_type=pattern_type,
                visible=bool(segmentation_item.get("visible", True)),
                display_type=(segmentation_item.get("display_type") or "fill").lower(),
                segments=segment_definitions,
                required=bool(segmentation_item.get("required", True)),
            )
        )

    for segmentation_definition in segmentation_definitions:
        if not segmentation_definition.folders_glob:
            raise RuntimeError(
                "Each segmentation entry must define 'segmentation_folders' "
                "or 'folders'."
            )

    return segmentation_definitions


def _normalize_segments(segment_items, context: str) -> List[SegmentDefinition]:
    segment_definitions = []
    for segment_index, segment_item in enumerate(segment_items or []):
        try:
            label_value = int(segment_item["label"])
        except Exception as exc:
            raise RuntimeError(
                f"{context}.segments[{segment_index}].label must be an integer."
            ) from exc
        segment_definitions.append(
            SegmentDefinition(
                label=label_value,
                name=segment_item["name"],
                color=_normalize_color(segment_item.get("color")),
                visible=bool(segment_item.get("visible", True)),
            )
        )
    return segment_definitions


def _normalize_subtraction(subtraction_values) -> Optional[SubtractionDefinition]:
    if not subtraction_values:
        return None
    minuend = subtraction_values.get("minuend")
    subtrahend = subtraction_values.get("subtrahend")
    if not minuend or not subtrahend:
        raise RuntimeError(
            "editing.subtraction requires both 'minuend' and 'subtrahend' image names."
        )
    return SubtractionDefinition(
        display_name=subtraction_values.get(
            "display_name", subtraction_default_display_name
        ),
        minuend=minuend,
        subtrahend=subtrahend,
    )


def _normalize_editing_section(config_values: dict) -> Optional[EditingDefinition]:
    editing_values = config_values.get("editing")
    if not editing_values:
        return None

    pattern, pattern_type = _normalize_pattern(editing_values, "editing")
    folders_glob = editing_values.get("segmentation_folders") or editing_values.get(
        "folders"
    )
    if not folders_glob:
        raise RuntimeError(
            "editing must define 'segmentation_folders' (the segmentation to edit)."
        )
    output_folder = editing_values.get("output_folder")
    if not output_folder:
        raise RuntimeError(
            "editing must define 'output_folder' for exported segmentations."
        )
    if not editing_values.get("segments"):
        raise RuntimeError(
            "editing must define 'segments' (the canonical label/name/color scheme)."
        )

    return EditingDefinition(
        folders_glob=folders_glob,
        subfolder_glob=(
            editing_values.get("segmentation_subfolder")
            or editing_values.get("subfolder", "")
        ),
        pattern=pattern,
        pattern_type=pattern_type,
        output_folder=output_folder,
        display_name=editing_values.get("display_name", "editing"),
        display_type=(editing_values.get("display_type") or "fill").lower(),
        segments=_normalize_segments(editing_values.get("segments", []), "editing"),
        editing_sources=list(editing_values.get("editing_sources", [])),
        subtraction=_normalize_subtraction(editing_values.get("subtraction")),
    )


def _normalize_config_values(config_values: dict) -> dict:
    image_section = _normalize_image_section(config_values)
    segmentation_definitions = _normalize_segment_definitions(config_values)
    editing_definition = _normalize_editing_section(config_values)
    return {
        "images": image_section,
        "segmentations": segmentation_definitions,
        "editing": editing_definition,
    }


def _load_config_values(config_path: str):
    global loaded_config
    global loaded_config_path

    with open(config_path, encoding="utf-8") as config_file:
        config_values = json.load(config_file)

    loaded_config = _normalize_config_values(config_values)
    loaded_config_path = config_path
    return loaded_config


def _match_filename_rule(basename: str, pattern: str, pattern_type: str) -> bool:
    if pattern_type == "regex":
        return re.fullmatch(pattern, basename) is not None
    return fnmatch.fnmatch(basename, pattern)


def _bids_subject_session_from_path(file_path: str):
    match = bids_subject_session_pattern.search(os.path.basename(file_path))
    if not match:
        return None
    return match.group(1), match.group(2)


def _compact_path(path: str, keep_parts: int = 3) -> str:
    if not path:
        return "(not configured)"
    path_parts = [part for part in path.split(os.sep) if part]
    if len(path_parts) <= keep_parts:
        return path
    return os.sep.join(["...", *path_parts[-keep_parts:]])


def _iter_search_directories(folders_glob: str, subfolder_glob: str = "") -> List[str]:
    search_directories = []
    for matched_root in sorted(glob.glob(folders_glob)):
        if not os.path.isdir(matched_root):
            continue
        if subfolder_glob:
            for matched_directory in sorted(
                glob.glob(os.path.join(matched_root, subfolder_glob))
            ):
                if os.path.isdir(matched_directory):
                    search_directories.append(matched_directory)
        else:
            search_directories.append(matched_root)
    return search_directories


def _list_nifti_files(folders_glob: str, subfolder_glob: str = "") -> List[str]:
    nifti_files = []
    for search_directory in _iter_search_directories(folders_glob, subfolder_glob):
        for root, _, files in os.walk(search_directory):
            for filename in sorted(files):
                if filename.endswith(".nii") or filename.endswith(".nii.gz"):
                    nifti_files.append(os.path.join(root, filename))
    return nifti_files


def _collect_image_matches(config: dict) -> Dict[tuple, Dict[str, List[str]]]:
    matches_by_session = {}
    image_files = _list_nifti_files(
        config["images"]["folders_glob"],
        config["images"]["subfolder_glob"],
    )
    for image_file in image_files:
        session_key = _bids_subject_session_from_path(image_file)
        if not session_key:
            continue
        basename = os.path.basename(image_file)
        for image_definition in config["images"]["definitions"]:
            if _match_filename_rule(
                basename,
                image_definition.pattern,
                image_definition.pattern_type,
            ):
                matches_by_session.setdefault(session_key, {}).setdefault(
                    image_definition.display_name,
                    [],
                ).append(image_file)
    return matches_by_session


def _collect_segmentation_matches(
    segmentation_definitions: List[SegmentationDefinition],
) -> List[Dict[tuple, List[str]]]:
    all_matches = []
    for segmentation_definition in segmentation_definitions:
        definition_matches = {}
        for segmentation_path in _list_nifti_files(
            segmentation_definition.folders_glob,
            segmentation_definition.subfolder_glob,
        ):
            session_key = _bids_subject_session_from_path(segmentation_path)
            if not session_key:
                continue
            if _match_filename_rule(
                os.path.basename(segmentation_path),
                segmentation_definition.pattern,
                segmentation_definition.pattern_type,
            ):
                definition_matches.setdefault(session_key, []).append(segmentation_path)
        all_matches.append(definition_matches)
    return all_matches


def discover_sessions(config=None) -> List[SessionRecord]:
    active_config = config or loaded_config
    if not active_config:
        return []

    image_definitions = active_config["images"]["definitions"]
    displayed_image_names = active_config["images"]["displayed_names"]
    image_matches = _collect_image_matches(active_config)
    segmentation_matches = _collect_segmentation_matches(
        active_config["segmentations"]
    )

    editing_definition = active_config.get("editing")
    editable_matches = {}
    if editing_definition:
        editable_matches = _collect_segmentation_matches([editing_definition])[0]

    sessions = []
    for session_key in sorted(image_matches.keys()):
        session_image_matches = image_matches[session_key]
        image_paths_by_name = {}
        valid_session = True

        for image_definition in image_definitions:
            matches = session_image_matches.get(image_definition.display_name, [])
            if len(matches) != 1:
                valid_session = False
                break
            image_paths_by_name[image_definition.display_name] = matches[0]

        if not valid_session:
            continue

        segmentation_records = []
        for segmentation_definition, definition_matches in zip(
            active_config["segmentations"],
            segmentation_matches,
        ):
            matches = definition_matches.get(session_key, [])
            if len(matches) != 1:
                # Required layer missing -> case is invalid. Optional layer missing
                # (e.g. an export not produced yet) -> just skip that layer.
                if segmentation_definition.required:
                    valid_session = False
                    break
                continue
            segmentation_records.append(
                SessionSegmentation(
                    display_name=segmentation_definition.display_name,
                    path=matches[0],
                    visible=segmentation_definition.visible,
                    display_type=segmentation_definition.display_type,
                    segments=segmentation_definition.segments,
                )
            )

        if not valid_session:
            continue

        editable_candidates = editable_matches.get(session_key, [])
        editable_path = editable_candidates[0] if len(editable_candidates) == 1 else None

        sessions.append(
            SessionRecord(
                subject_id=session_key[0],
                session_id=session_key[1],
                image_paths_by_name=image_paths_by_name,
                display_image_names=list(displayed_image_names),
                segmentations=segmentation_records,
                editable_path=editable_path,
            )
        )

    return sessions


if default_config_path:
    _load_config_values(default_config_path)

try:
    import ctk
    import numpy as np
    import qSlicerSegmentationsModuleWidgetsPythonQt
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
    qSlicerSegmentationsModuleWidgetsPythonQt = None
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
class PediatricGliomaSegmentationBrowser(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Segmentation Browser"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Cursor"]
        self.parent.helpText = (
            "Browse preprocessed pediatric glioma sessions, load the configured "
            "image set, and overlay the matching segmentation for review."
        )
        self.parent.acknowledgementText = ""


class PediatricGliomaSegmentationBrowserWidget(
    ScriptedLoadableModuleWidget, VTKObservationMixin
):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.visibilityShortcut = None
        self.previousSegmentationShortcut = None
        self.nextSegmentationShortcut = None
        self.undoShortcut = None
        self.redoShortcut = None
        self.loadConfigButton = None
        self.refreshButton = None
        self.previousButton = None
        self.nextButton = None
        self.sessionSelector = None
        self.statusLabel = None
        self.pathsLabel = None
        self.editingAvailable = False
        self.mode = "review"
        self.modeSelector = None
        self.segmentModePanel = None
        self.exportButton = None
        self.editingSourceSelector = None
        self.foregroundOpacitySlider = None
        self.segmentEditorWidget = None
        self.segmentEditorNode = None

    def setup(self):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This module must be run inside 3D Slicer.")

        super().setup()
        PediatricGliomaSegmentationBrowserLogic.removeManagedNodesFromScene()
        self.logic = PediatricGliomaSegmentationBrowserLogic()

        collapsibleButton = ctk.ctkCollapsibleButton()
        collapsibleButton.text = "Case Browser"
        self.layout.addWidget(collapsibleButton)

        formLayout = qt.QFormLayout(collapsibleButton)

        self.pathsLabel = qt.QLabel("")
        self.pathsLabel.wordWrap = True
        self.pathsLabel.maximumWidth = 320
        formLayout.addRow("Dataset roots", self.pathsLabel)

        self.loadConfigButton = qt.QPushButton("Load config JSON")
        self.loadConfigButton.toolTip = (
            "Select a JSON configuration file and reload this module's paths "
            "and settings from it."
        )
        formLayout.addRow(self.loadConfigButton)

        self.refreshButton = qt.QPushButton("Refresh sessions")
        self.refreshButton.toolTip = (
            "Rescan the configured image and segmentation sources."
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

        self.editingAvailable = bool(loaded_config and loaded_config.get("editing"))
        if self.editingAvailable:
            self.modeSelector = qt.QComboBox()
            self.modeSelector.addItem("Review", "review")
            self.modeSelector.addItem("Segment", "segment")
            self.modeSelector.toolTip = (
                "Review: compare read-only segmentations (switch with [ / ]).\n"
                "Segment: edit one segmentation and export. Only one mode is active "
                "at a time."
            )
            formLayout.addRow("Mode", self.modeSelector)
            self._buildEditingControls()

        self.layout.addStretch(1)

        self.loadConfigButton.connect("clicked()", self.selectConfigFile)
        self.refreshButton.connect("clicked()", self.refreshSessions)
        self.previousButton.connect("clicked()", self.loadPreviousSession)
        self.nextButton.connect("clicked()", self.loadNextSession)
        self.sessionSelector.connect("currentIndexChanged(int)", self.onSessionSelected)
        if self.editingAvailable:
            self.modeSelector.connect("currentIndexChanged(int)", self.onModeChanged)

        self.logic.setMode(self.mode)
        self.installVisibilityShortcut()
        self.installSegmentationCyclingShortcuts()
        self.updateConfigDisplay()
        self.refreshSessions()

    def _buildEditingControls(self):
        self.segmentModePanel = ctk.ctkCollapsibleButton()
        self.segmentModePanel.text = "Segmentation"
        self.layout.addWidget(self.segmentModePanel)
        panelLayout = qt.QVBoxLayout(self.segmentModePanel)

        controlsForm = qt.QFormLayout()
        panelLayout.addLayout(controlsForm)

        self.exportButton = qt.QPushButton("Export segmentation")
        self.exportButton.toolTip = (
            "Write the edited segmentation to the configured output_folder, "
            "preserving each segment's label value."
        )
        controlsForm.addRow(self.exportButton)

        self.editingSourceSelector = qt.QComboBox()
        self.editingSourceSelector.toolTip = (
            "Volume used for Segment Editor tools (e.g. Threshold) and shown as a "
            "foreground overlay in all four views."
        )
        controlsForm.addRow("Editing source", self.editingSourceSelector)

        self.foregroundOpacitySlider = ctk.ctkSliderWidget()
        self.foregroundOpacitySlider.minimum = 0.0
        self.foregroundOpacitySlider.maximum = 1.0
        self.foregroundOpacitySlider.singleStep = 0.05
        self.foregroundOpacitySlider.value = 0
        self.foregroundOpacitySlider.decimals = 2
        self.foregroundOpacitySlider.toolTip = (
            "Opacity of the editing-source foreground overlay shown in all views."
        )
        controlsForm.addRow("Edit overlay", self.foregroundOpacitySlider)

        self.segmentEditorWidget = (
            qSlicerSegmentationsModuleWidgetsPythonQt.qMRMLSegmentEditorWidget()
        )
        self.segmentEditorWidget.setMaximumNumberOfUndoStates(10)
        self.segmentEditorWidget.setSegmentationNodeSelectorVisible(False)
        self.segmentEditorWidget.setSourceVolumeNodeSelectorVisible(False)
        self.segmentEditorWidget.setSwitchToSegmentationsButtonVisible(False)
        self.segmentEditorWidget.setMRMLSegmentEditorNode(
            self.segmentEditorParameterNode()
        )
        self.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        panelLayout.addWidget(self.segmentEditorWidget)
        self.logic.setSegmentEditorWidget(
            self.segmentEditorWidget, self.segmentEditorNode
        )

        self.exportButton.connect("clicked()", self.onExportClicked)
        self.editingSourceSelector.connect(
            "currentIndexChanged(int)", self.onEditingSourceChanged
        )
        self.foregroundOpacitySlider.connect(
            "valueChanged(double)", self.onForegroundOpacityChanged
        )
        self.installUndoRedoShortcuts()

        # Visible only in Segment mode (default Review keeps it hidden).
        self.segmentModePanel.visible = self.mode == "segment"

    def segmentEditorParameterNode(self):
        if self.segmentEditorNode:
            return self.segmentEditorNode
        self.segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentEditorNode",
            "PediatricGliomaSegmentationBrowserEditor",
        )
        self.segmentEditorNode.SetAttribute(managed_node_attribute, "1")
        return self.segmentEditorNode

    def onModeChanged(self, index: int):
        if index < 0:
            return
        self.mode = self.modeSelector.itemData(index) or "review"
        self.logic.setMode(self.mode)
        if self.segmentModePanel:
            self.segmentModePanel.visible = self.mode == "segment"
        current_index = self.sessionSelector.currentIndex
        if current_index >= 0:
            self.onSessionSelected(current_index)
        else:
            self.statusLabel.text = f"Switched to {self.mode} mode."

    def cleanup(self):
        if self.segmentEditorWidget:
            self.segmentEditorWidget.setMRMLScene(None)
            self.segmentEditorWidget = None
        self.segmentEditorNode = None
        if self.logic:
            self.logic.removeManagedNodesFromScene()
        self.removeVisibilityShortcut()
        self.removeSegmentationCyclingShortcuts()
        self.removeUndoRedoShortcuts()

    def updateConfigDisplay(self):
        loaded_config_name = (
            os.path.basename(loaded_config_path) if loaded_config_path else "(none loaded)"
        )
        loaded_config_tooltip = loaded_config_path or (
            "No config loaded. Use 'Load config JSON' to select one."
        )
        if loaded_config:
            image_section = loaded_config["images"]
            displayed_images = ", ".join(image_section["displayed_names"])
            segmentation_names = ", ".join(
                segmentation.display_name
                for segmentation in loaded_config["segmentations"]
            ) or "(none)"
            images_root = image_section["folders_glob"]
            images_subfolder = image_section["subfolder_glob"] or "(recursive)"
        else:
            displayed_images = "(none)"
            segmentation_names = "(none)"
            images_root = ""
            images_subfolder = ""

        self.pathsLabel.text = (
            "Config: "
            f"{loaded_config_name}\n"
            "Images: "
            f"{_compact_path(images_root)}\n"
            "Image subfolder: "
            f"{images_subfolder}\n"
            "Displayed images: "
            f"{displayed_images}\n"
            "Segmentation sets: "
            f"{segmentation_names}"
        )
        self.pathsLabel.toolTip = (
            f"Config: {loaded_config_tooltip}\n"
            f"Images: {images_root}\n"
            f"Image subfolder: {images_subfolder}\n"
            f"Displayed images: {displayed_images}\n"
            f"Segmentation sets: {segmentation_names}"
        )

    def selectConfigFile(self):
        start_directory = (
            os.path.dirname(loaded_config_path)
            if loaded_config_path
            else os.path.dirname(__file__)
        )
        selected_path = qt.QFileDialog.getOpenFileName(
            slicer.util.mainWindow(),
            "Select plugin config JSON",
            start_directory,
            config_file_filter,
        )
        if isinstance(selected_path, (list, tuple)):
            selected_path = selected_path[0]
        if not selected_path:
            return

        try:
            _load_config_values(selected_path)
            self.logic.clearLoadedSession()
            self.removeVisibilityShortcut()
            self.removeSegmentationCyclingShortcuts()
            self.installVisibilityShortcut()
            self.installSegmentationCyclingShortcuts()
            self.updateConfigDisplay()
            self.refreshSessions()
            self.statusLabel.text = (
                f"Loaded config {os.path.basename(selected_path)}."
            )
        except Exception as exc:
            self.statusLabel.text = f"Failed to load config: {exc}"
            raise

    def installVisibilityShortcut(self):
        main_window = slicer.util.mainWindow()
        if not main_window:
            return

        for shortcut in main_window.findChildren(qt.QShortcut):
            if shortcut.objectName == (
                "PediatricGliomaSegmentationBrowserToggleSegmentsShortcut"
            ):
                shortcut.setParent(None)
                shortcut.deleteLater()

        self.visibilityShortcut = qt.QShortcut(main_window)
        self.visibilityShortcut.objectName = (
            "PediatricGliomaSegmentationBrowserToggleSegmentsShortcut"
        )
        self.visibilityShortcut.setKey(qt.QKeySequence(
            toggle_segmentation_visibility_shortcut
        ))
        self.visibilityShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.visibilityShortcut.connect("activated()", self.toggleSegmentationVisibility)

    def removeVisibilityShortcut(self):
        if self.visibilityShortcut:
            self.visibilityShortcut.setParent(None)
            self.visibilityShortcut.deleteLater()
            self.visibilityShortcut = None

    def installSegmentationCyclingShortcuts(self):
        main_window = slicer.util.mainWindow()
        if not main_window:
            return

        for shortcut in main_window.findChildren(qt.QShortcut):
            if shortcut.objectName in (
                "SegmentationBrowserPreviousSegmentationShortcut",
                "SegmentationBrowserNextSegmentationShortcut",
            ):
                shortcut.setParent(None)
                shortcut.deleteLater()

        self.previousSegmentationShortcut = qt.QShortcut(main_window)
        self.previousSegmentationShortcut.objectName = (
            "SegmentationBrowserPreviousSegmentationShortcut"
        )
        self.previousSegmentationShortcut.setKey(
            qt.QKeySequence(previous_segmentation_shortcut)
        )
        self.previousSegmentationShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.previousSegmentationShortcut.connect(
            "activated()",
            self.showPreviousSegmentation,
        )

        self.nextSegmentationShortcut = qt.QShortcut(main_window)
        self.nextSegmentationShortcut.objectName = (
            "SegmentationBrowserNextSegmentationShortcut"
        )
        self.nextSegmentationShortcut.setKey(
            qt.QKeySequence(next_segmentation_shortcut)
        )
        self.nextSegmentationShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.nextSegmentationShortcut.connect(
            "activated()",
            self.showNextSegmentation,
        )

    def removeSegmentationCyclingShortcuts(self):
        if self.previousSegmentationShortcut:
            self.previousSegmentationShortcut.setParent(None)
            self.previousSegmentationShortcut.deleteLater()
            self.previousSegmentationShortcut = None
        if self.nextSegmentationShortcut:
            self.nextSegmentationShortcut.setParent(None)
            self.nextSegmentationShortcut.deleteLater()
            self.nextSegmentationShortcut = None

    def installUndoRedoShortcuts(self):
        main_window = slicer.util.mainWindow()
        if not main_window:
            return
        for shortcut in main_window.findChildren(qt.QShortcut):
            if shortcut.objectName in (
                undo_shortcut_object_name,
                redo_shortcut_object_name,
            ):
                shortcut.setParent(None)
                shortcut.deleteLater()

        self.undoShortcut = qt.QShortcut(main_window)
        self.undoShortcut.objectName = undo_shortcut_object_name
        self.undoShortcut.setKey(qt.QKeySequence(qt.QKeySequence.Undo))
        self.undoShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.undoShortcut.connect("activated()", self.undoSegmentationEdit)

        self.redoShortcut = qt.QShortcut(main_window)
        self.redoShortcut.objectName = redo_shortcut_object_name
        self.redoShortcut.setKey(qt.QKeySequence(qt.QKeySequence.Redo))
        self.redoShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.redoShortcut.connect("activated()", self.redoSegmentationEdit)

    def removeUndoRedoShortcuts(self):
        if self.undoShortcut:
            self.undoShortcut.setParent(None)
            self.undoShortcut.deleteLater()
            self.undoShortcut = None
        if self.redoShortcut:
            self.redoShortcut.setParent(None)
            self.redoShortcut.deleteLater()
            self.redoShortcut = None

    def undoSegmentationEdit(self):
        if self.segmentEditorWidget:
            self.segmentEditorWidget.undo()
            self.statusLabel.text = "Undid segmentation edit."

    def redoSegmentationEdit(self):
        if self.segmentEditorWidget:
            self.segmentEditorWidget.redo()
            self.statusLabel.text = "Redid segmentation edit."

    def updateEditingControls(self):
        if not self.editingAvailable:
            return
        available_source_names = self.logic.availableEditingSourceNames()
        current_source_name = self.logic.currentEditingSourceName

        self.editingSourceSelector.blockSignals(True)
        self.editingSourceSelector.clear()
        for source_name in available_source_names:
            self.editingSourceSelector.addItem(source_name)
        if current_source_name:
            selected_index = self.editingSourceSelector.findText(current_source_name)
            if selected_index >= 0:
                self.editingSourceSelector.setCurrentIndex(selected_index)
        self.editingSourceSelector.blockSignals(False)
        self.editingSourceSelector.enabled = bool(available_source_names)

        self.foregroundOpacitySlider.blockSignals(True)
        self.foregroundOpacitySlider.value = self.logic.foregroundOpacity
        self.foregroundOpacitySlider.blockSignals(False)
        self.foregroundOpacitySlider.enabled = bool(available_source_names)
        self.exportButton.enabled = self.logic.currentSession is not None

    def onEditingSourceChanged(self, index: int):
        if index < 0:
            return
        source_name = self.editingSourceSelector.itemText(index)
        self.logic.setEditingSource(source_name, self.foregroundOpacitySlider.value)

    def onForegroundOpacityChanged(self, value: float):
        self.logic.setForegroundOpacity(value)

    def onExportClicked(self):
        try:
            output_path = self.logic.exportEditableSegmentation()
            self.statusLabel.text = f"Exported segmentation to {output_path}"
        except Exception as exc:
            self.statusLabel.text = f"Failed to export segmentation: {exc}"
            raise

    def toggleSegmentationVisibility(self):
        visible = self.logic.toggleSegmentationVisibility()
        if visible is None:
            return
        segmentation_name = self.logic.activeSegmentationName() or "segmentation"
        self.statusLabel.text = (
            f"{segmentation_name} visibility {'on' if visible else 'off'} "
            f"({toggle_segmentation_visibility_shortcut})."
        )

    def showPreviousSegmentation(self):
        segmentation_name = self.logic.cycleVisibleSegmentation(-1)
        if not segmentation_name:
            return
        self.statusLabel.text = (
            f"Showing {segmentation_name} "
            f"({previous_segmentation_shortcut}/{next_segmentation_shortcut})."
        )

    def showNextSegmentation(self):
        segmentation_name = self.logic.cycleVisibleSegmentation(1)
        if not segmentation_name:
            return
        self.statusLabel.text = (
            f"Showing {segmentation_name} "
            f"({previous_segmentation_shortcut}/{next_segmentation_shortcut})."
        )

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
            self.logic.clearLoadedSession()
            self.statusLabel.text = (
                "No valid sessions found. A valid session must match all configured "
                "image rules and all configured segmentation rules for the same "
                "BIDS subject/session pair."
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
            self.logic.clearLoadedSession()
            return

        session = self.sessionSelector.itemData(index)
        if not session:
            return

        try:
            self.logic.loadSession(session)
            self.updateEditingControls()
            position = f"({index + 1}/{self.sessionSelector.count})"
            if self.mode == "segment":
                source_note = (
                    "editing source seg"
                    if session.editable_path
                    else "empty (new annotation)"
                )
                self.statusLabel.text = (
                    f"[Segment] {session.display_name} {position} — {source_note}. "
                    "Export saves to the configured output_folder."
                )
            else:
                self.statusLabel.text = (
                    f"[Review] {session.display_name} {position} with "
                    f"{len(session.display_image_names)} image(s) and "
                    f"{len(session.segmentations)} comparison seg(s) ([ / ] to switch)."
                )
        except Exception as exc:
            self.statusLabel.text = f"Failed to load {session.display_name}: {exc}"
            raise


class PediatricGliomaSegmentationBrowserLogic(ScriptedLoadableModuleLogic):
    @staticmethod
    def removeManagedNodesFromScene():
        if not SLICER_AVAILABLE:
            return

        scene = slicer.mrmlScene
        nodes_to_remove = []
        scene_nodes = scene.GetNodes()
        scene_nodes.InitTraversal()
        node = scene_nodes.GetNextItemAsObject()
        while node:
            if node.GetAttribute(managed_node_attribute) == "1":
                nodes_to_remove.append(node)
            node = scene_nodes.GetNextItemAsObject()

        for node in reversed(nodes_to_remove):
            scene.RemoveNode(node)

    def __init__(self):
        super().__init__()
        self.sessions: List[SessionRecord] = []
        self.loadedNodeIDs: List[str] = []
        self.currentSession = None
        self.currentSegmentationNodes = []
        self.currentVisibleSegmentationIndex = None
        self.currentVolumeNodesByName = {}
        self.currentEditableNode = None
        self.currentEditingSourceName = None
        self.foregroundOpacity = 0
        self.segmentEditorWidget = None
        self.segmentEditorNode = None
        self.mode = "review"

    def refreshSessions(self) -> List[SessionRecord]:
        self.sessions = discover_sessions()
        return self.sessions

    def setMode(self, mode: str):
        self.mode = "segment" if mode == "segment" else "review"

    def setSegmentEditorWidget(self, segment_editor_widget, segment_editor_node):
        self.segmentEditorWidget = segment_editor_widget
        self.segmentEditorNode = segment_editor_node

    def clearLoadedSession(self):
        self._removePreviouslyLoadedNodes()

    def activeSegmentationName(self):
        if self.mode == "segment":
            return self.currentEditableNode.GetName() if self.currentEditableNode else None
        if not self.currentSegmentationNodes:
            return None
        if self.currentVisibleSegmentationIndex is None:
            return None
        if not (0 <= self.currentVisibleSegmentationIndex < len(self.currentSegmentationNodes)):
            return None
        return self.currentSegmentationNodes[self.currentVisibleSegmentationIndex].GetName()

    def toggleSegmentationVisibility(self):
        if self.mode == "segment":
            if not self.currentEditableNode:
                return None
            display_node = self.currentEditableNode.GetDisplayNode()
            if not display_node:
                return None
            visible = not bool(display_node.GetVisibility())
            display_node.SetVisibility(visible)
            return visible

        if not self.currentSegmentationNodes:
            return None

        active_index = self._normalizedVisibleSegmentationIndex()
        if active_index is None:
            return None
        display_node = self.currentSegmentationNodes[active_index].GetDisplayNode()
        if not display_node:
            return None

        visible = not bool(display_node.GetVisibility())
        self._setExclusiveSegmentationVisibility(active_index, visible)
        return visible

    def cycleVisibleSegmentation(self, step: int):
        if not self.currentSegmentationNodes:
            return None

        active_index = self._normalizedVisibleSegmentationIndex()
        if active_index is None:
            active_index = 0
        target_index = (active_index + step) % len(self.currentSegmentationNodes)
        self._setExclusiveSegmentationVisibility(target_index, True)
        return self.currentSegmentationNodes[target_index].GetName()

    def loadSession(self, session: SessionRecord):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This logic must be run inside 3D Slicer.")

        self._removePreviouslyLoadedNodes()
        self._ensureFourSliceLayout()
        self.currentSession = session
        self.currentSegmentationNodes = []
        self.currentVolumeNodesByName = {}

        display_volume_nodes = []
        for image_name in session.display_image_names:
            volume_node = self._loadVolume(
                session.image_paths_by_name[image_name],
                image_name,
            )
            self.currentVolumeNodesByName[image_name] = volume_node
            display_volume_nodes.append(volume_node)

        editing = loaded_config.get("editing") if loaded_config else None
        segment_mode = bool(editing) and self.mode == "segment"

        if segment_mode:
            # Segment mode: just the editable seg + editor. No comparison layers.
            self._maybeCreateSubtractionVolume(editing, session)
            self.currentEditableNode = self._loadEditableSegmentation(session, editing)
        else:
            # Review mode: read-only comparison layers, no editor.
            for session_segmentation in session.segmentations:
                segmentation_node = self._loadSegmentation(session_segmentation)
                self.currentSegmentationNodes.append(segmentation_node)
            self._initializeVisibleSegmentation(session)

        self._assignVolumesToViews(display_volume_nodes)
        self._activateWindowLevelTool()

        if segment_mode:
            self._restoreEditingSource()

    def _trackNode(self, node):
        if node and node.GetID():
            node.SetAttribute(managed_node_attribute, "1")
            self.loadedNodeIDs.append(node.GetID())

    def _removePreviouslyLoadedNodes(self):
        scene = slicer.mrmlScene
        for node_id in reversed(self.loadedNodeIDs):
            node = scene.GetNodeByID(node_id)
            if node:
                scene.RemoveNode(node)
        self.loadedNodeIDs = []
        self.currentSession = None
        self.currentSegmentationNodes = []
        self.currentVisibleSegmentationIndex = None
        self.currentVolumeNodesByName = {}
        self.currentEditableNode = None
        self.currentEditingSourceName = None

    def _loadVolume(self, image_path: str, image_name: str):
        volume_node = slicer.util.loadVolume(image_path, {"show": False})
        if not volume_node:
            raise RuntimeError(f"Could not load image: {image_path}")
        volume_node.SetName(image_name)
        display_node = volume_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        self._trackNode(volume_node)
        return volume_node

    def _loadSegmentation(self, session_segmentation: SessionSegmentation):
        segmentation_node = slicer.util.loadSegmentation(
            session_segmentation.path,
            {"show": False},
        )
        if segmentation_node:
            self._trackNode(segmentation_node)
            self._configureSegmentationNode(segmentation_node, session_segmentation)
            return segmentation_node

        labelmap_node = slicer.util.loadLabelVolume(
            session_segmentation.path,
            {"show": False},
        )
        if not labelmap_node:
            raise RuntimeError(
                f"Could not load segmentation: {session_segmentation.path}"
            )

        self._trackNode(labelmap_node)
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode",
            session_segmentation.display_name,
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
        self._configureSegmentationNode(segmentation_node, session_segmentation)
        return segmentation_node

    def _configureSegmentationNode(
        self,
        segmentation_node,
        session_segmentation: SessionSegmentation,
    ):
        segmentation_node.SetName(session_segmentation.display_name)
        display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            segmentation_node.CreateDefaultDisplayNodes()
            display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            return

        display_node.SetVisibility(session_segmentation.visible)
        display_node.SetVisibility2D(True)
        display_node.SetVisibility3D(True)
        if session_segmentation.display_type == "outline":
            display_node.SetVisibility2DFill(False)
            display_node.SetOpacity2DFill(0.0)
            display_node.SetVisibility2DOutline(True)
            display_node.SetOpacity2DOutline(1.0)
        else:
            display_node.SetVisibility2DFill(True)
            display_node.SetOpacity2DFill(0.35)
            display_node.SetVisibility2DOutline(True)
            display_node.SetOpacity2DOutline(1.0)

        segments_by_label = {
            segment_definition.label: segment_definition
            for segment_definition in session_segmentation.segments
        }
        segmentation = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)
        for segment_index in range(segment_ids.GetNumberOfValues()):
            segment_id = segment_ids.GetValue(segment_index)
            segment = segmentation.GetSegment(segment_id)
            if not segment:
                continue
            segment_definition = segments_by_label.get(segment.GetLabelValue())
            if not segment_definition:
                continue
            segment.SetName(segment_definition.name)
            if segment_definition.color:
                segment.SetColor(*segment_definition.color)
            display_node.SetSegmentVisibility(segment_id, segment_definition.visible)

    def _normalizedVisibleSegmentationIndex(self):
        if not self.currentSegmentationNodes:
            return None
        if self.currentVisibleSegmentationIndex is None:
            return 0
        if self.currentVisibleSegmentationIndex < 0:
            return 0
        if self.currentVisibleSegmentationIndex >= len(self.currentSegmentationNodes):
            return len(self.currentSegmentationNodes) - 1
        return self.currentVisibleSegmentationIndex

    def _setExclusiveSegmentationVisibility(self, visible_index: int, visible: bool):
        self.currentVisibleSegmentationIndex = visible_index
        for index, segmentation_node in enumerate(self.currentSegmentationNodes):
            display_node = segmentation_node.GetDisplayNode()
            if not display_node:
                continue
            display_node.SetVisibility(visible and index == visible_index)

    def _initializeVisibleSegmentation(self, session: SessionRecord):
        if not self.currentSegmentationNodes:
            self.currentVisibleSegmentationIndex = None
            return

        visible_indices = [
            index
            for index, segmentation in enumerate(session.segmentations)
            if segmentation.visible
        ]
        initial_index = visible_indices[0] if visible_indices else 0
        self._setExclusiveSegmentationVisibility(
            initial_index,
            bool(visible_indices),
        )

    def _ensureFourSliceLayout(self):
        layout_node = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        if layout_node.GetLayoutDescription(custom_layout_id):
            slicer.app.layoutManager().setLayout(custom_layout_id)
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
        layout_node.AddLayoutDescription(custom_layout_id, layout_description)
        slicer.app.layoutManager().setLayout(custom_layout_id)

    def _assignVolumesToViews(self, volume_nodes):
        layout_manager = slicer.app.layoutManager()
        for index, view_name in enumerate(four_slice_view_names):
            slice_widget = layout_manager.sliceWidget(view_name)
            if not slice_widget:
                continue

            composite_node = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite_node.SetDoPropagateVolumeSelection(False)
            composite_node.SetLinkedControl(True)
            composite_node.SetHotLinkedControl(True)
            background_volume_id = None
            if index < len(volume_nodes):
                background_volume_id = volume_nodes[index].GetID()
            composite_node.SetBackgroundVolumeID(background_volume_id)
            composite_node.SetForegroundVolumeID(None)
            composite_node.SetForegroundOpacity(0.0)
            composite_node.SetLabelVolumeID(None)

            slice_node = slice_widget.mrmlSliceNode()
            slice_node.SetOrientationToAxial()
            slice_widget.sliceLogic().FitSliceToAll()

    def _activateWindowLevelTool(self):
        interaction_node = slicer.app.applicationLogic().GetInteractionNode()
        interaction_node.SetCurrentInteractionMode(
            slicer.vtkMRMLInteractionNode.AdjustWindowLevel
        )

    # ------------------------------------------------------------------ editing

    def _maybeCreateSubtractionVolume(self, editing, session: SessionRecord):
        subtraction = editing.subtraction
        if not subtraction:
            return
        minuend_node = self.currentVolumeNodesByName.get(subtraction.minuend)
        subtrahend_node = self.currentVolumeNodesByName.get(subtraction.subtrahend)
        if not minuend_node or not subtrahend_node:
            return

        mismatch_reason = self._volumeGeometryMismatchReason(
            minuend_node, subtrahend_node
        )
        if mismatch_reason:
            slicer.util.warningDisplay(
                f"Could not create '{subtraction.display_name}' for "
                f"{session.display_name}: {mismatch_reason}.",
                windowTitle="Subtraction image unavailable",
            )
            return

        subtraction_array = (
            slicer.util.arrayFromVolume(minuend_node).astype(np.float32)
            - slicer.util.arrayFromVolume(subtrahend_node).astype(np.float32)
        )
        subtraction_node = slicer.modules.volumes.logic().CloneVolume(
            minuend_node, subtraction.display_name
        )
        slicer.util.updateVolumeFromArray(subtraction_node, subtraction_array)
        subtraction_node.SetName(subtraction.display_name)
        display_node = subtraction_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        self._trackNode(subtraction_node)
        self.currentVolumeNodesByName[subtraction.display_name] = subtraction_node

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
            return "spacing mismatch"
        if not np.allclose(volume_node_a.GetOrigin(), volume_node_b.GetOrigin()):
            return "origin mismatch"
        matrix_a = vtk.vtkMatrix4x4()
        matrix_b = vtk.vtkMatrix4x4()
        volume_node_a.GetIJKToRASMatrix(matrix_a)
        volume_node_b.GetIJKToRASMatrix(matrix_b)
        elements_a = [matrix_a.GetElement(r, c) for r in range(4) for c in range(4)]
        elements_b = [matrix_b.GetElement(r, c) for r in range(4) for c in range(4)]
        if not np.allclose(elements_a, elements_b):
            return "IJK-to-RAS geometry mismatch"
        return None

    def _editableOutputPath(self, session: SessionRecord, editing) -> str:
        if session.editable_path:
            filename = os.path.basename(session.editable_path)
        else:
            filename = f"{session.subject_id}_{session.session_id}_dseg.nii.gz"
        return os.path.join(
            editing.output_folder,
            session.subject_id,
            session.session_id,
            "anat",
            filename,
        )

    def _loadEditableSegmentation(self, session: SessionRecord, editing):
        output_path = self._editableOutputPath(session, editing)
        # Resume from a prior export if one exists, else load the source seg to correct.
        if os.path.isfile(output_path):
            source_path = output_path
        else:
            source_path = session.editable_path

        if source_path and os.path.isfile(source_path):
            segmentation_node = self._importSegmentationNodeFromFile(
                source_path, editing.display_name
            )
        else:
            segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", editing.display_name
            )
            segmentation_node.CreateDefaultDisplayNodes()
            self._trackNode(segmentation_node)

        self._applyCanonicalSegments(segmentation_node, editing)
        self._configureEditableDisplay(segmentation_node, editing)
        return segmentation_node

    def _importSegmentationNodeFromFile(self, segmentation_path: str, name: str):
        segmentation_node = slicer.util.loadSegmentation(
            segmentation_path, {"show": False}
        )
        if segmentation_node:
            segmentation_node.SetName(name)
            self._trackNode(segmentation_node)
            return segmentation_node

        labelmap_node = slicer.util.loadLabelVolume(segmentation_path, {"show": False})
        if not labelmap_node:
            raise RuntimeError(f"Could not load segmentation: {segmentation_path}")
        self._trackNode(labelmap_node)
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", name
        )
        segmentation_node.CreateDefaultDisplayNodes()
        self._trackNode(segmentation_node)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            labelmap_node, segmentation_node
        )
        slicer.mrmlScene.RemoveNode(labelmap_node)
        self.loadedNodeIDs = [
            node_id
            for node_id in self.loadedNodeIDs
            if node_id != labelmap_node.GetID()
        ]
        return segmentation_node

    def _applyCanonicalSegments(self, segmentation_node, editing):
        segments_by_label = {
            segment_definition.label: segment_definition
            for segment_definition in editing.segments
        }
        segmentation = segmentation_node.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)

        existing_label_values = set()
        for segment_index in range(segment_ids.GetNumberOfValues()):
            segment = segmentation.GetSegment(segment_ids.GetValue(segment_index))
            if not segment:
                continue
            label_value = segment.GetLabelValue()
            existing_label_values.add(label_value)
            segment_definition = segments_by_label.get(label_value)
            if segment_definition:
                segment.SetName(segment_definition.name)
                if segment_definition.color:
                    segment.SetColor(*segment_definition.color)

        # Add any missing canonical segments, in label order, with correct LabelValue.
        for segment_definition in editing.segments:
            if segment_definition.label in existing_label_values:
                continue
            segment_id = segmentation.AddEmptySegment("", segment_definition.name)
            segment = segmentation.GetSegment(segment_id)
            if segment:
                segment.SetLabelValue(segment_definition.label)
                if segment_definition.color:
                    segment.SetColor(*segment_definition.color)

    def _configureEditableDisplay(self, segmentation_node, editing):
        display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            segmentation_node.CreateDefaultDisplayNodes()
            display_node = segmentation_node.GetDisplayNode()
        if not display_node:
            return
        display_node.SetVisibility(True)
        display_node.SetVisibility2D(True)
        display_node.SetVisibility3D(True)
        if editing.display_type == "outline":
            display_node.SetVisibility2DFill(False)
            display_node.SetOpacity2DFill(0.0)
            display_node.SetVisibility2DOutline(True)
            display_node.SetOpacity2DOutline(1.0)
        else:
            display_node.SetVisibility2DFill(True)
            display_node.SetOpacity2DFill(0.35)
            display_node.SetVisibility2DOutline(True)
            display_node.SetOpacity2DOutline(1.0)

    def availableEditingSourceNames(self) -> List[str]:
        editing = loaded_config.get("editing") if loaded_config else None
        if not editing:
            return []
        return [
            source_name
            for source_name in editing.editing_sources
            if source_name in self.currentVolumeNodesByName
        ]

    def setEditingSource(self, source_name: str, foreground_opacity: float = None):
        if foreground_opacity is not None:
            self.foregroundOpacity = foreground_opacity
        if (
            not source_name
            or source_name not in self.currentVolumeNodesByName
            or not self.currentEditableNode
        ):
            return
        self.currentEditingSourceName = source_name
        source_volume_node = self.currentVolumeNodesByName[source_name]
        self._setSegmentEditorSourceVolume(self.currentEditableNode, source_volume_node)
        self._assignForegroundVolumeToViews(
            source_volume_node, self.foregroundOpacity
        )

    def setForegroundOpacity(self, foreground_opacity: float):
        self.foregroundOpacity = foreground_opacity
        if self.currentEditingSourceName:
            self.setEditingSource(self.currentEditingSourceName)

    def _restoreEditingSource(self):
        available_source_names = self.availableEditingSourceNames()
        if not available_source_names:
            self.currentEditingSourceName = None
            return
        if self.currentEditingSourceName not in self.currentVolumeNodesByName:
            self.currentEditingSourceName = next(
                (
                    source_name
                    for source_name in ("T1post", "T1pre")
                    if source_name in self.currentVolumeNodesByName
                ),
                available_source_names[0],
            )
        self.setEditingSource(self.currentEditingSourceName)

    def _setSegmentEditorSourceVolume(self, segmentation_node, source_volume_node):
        editor_widget = self.segmentEditorWidget
        if not editor_widget:
            return
        if hasattr(editor_widget, "setAutoShowSourceVolumeNode"):
            editor_widget.setAutoShowSourceVolumeNode(False)
        elif hasattr(editor_widget, "setAutoShowMasterVolumeNode"):
            editor_widget.setAutoShowMasterVolumeNode(False)
        if self.segmentEditorNode:
            editor_widget.setMRMLSegmentEditorNode(self.segmentEditorNode)
        editor_widget.setSegmentationNode(segmentation_node)
        editor_widget.setSourceVolumeNode(source_volume_node)

    def _assignForegroundVolumeToViews(self, volume_node, foreground_opacity: float):
        layout_manager = slicer.app.layoutManager()
        for view_name in four_slice_view_names:
            slice_widget = layout_manager.sliceWidget(view_name)
            if not slice_widget:
                continue
            composite_node = slice_widget.sliceLogic().GetSliceCompositeNode()
            composite_node.SetDoPropagateVolumeSelection(False)
            composite_node.SetForegroundVolumeID(volume_node.GetID())
            composite_node.SetForegroundOpacity(foreground_opacity)

    def exportEditableSegmentation(self) -> str:
        if not self.currentSession or not self.currentEditableNode:
            raise RuntimeError("No editable session is currently loaded.")
        editing = loaded_config.get("editing") if loaded_config else None
        if not editing:
            raise RuntimeError("No editing configuration is loaded.")

        output_path = self._editableOutputPath(self.currentSession, editing)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        reference_volume_node = self.currentVolumeNodesByName.get("T1post")
        if not reference_volume_node and self.currentSession.display_image_names:
            reference_volume_node = self.currentVolumeNodesByName.get(
                self.currentSession.display_image_names[0]
            )
        if not reference_volume_node:
            raise RuntimeError("No reference image volume is available for export.")

        # FIX: map each segment to its canonical label by NAME (exactly what is shown
        # and selected in the Segment Editor), falling back to the segment's own
        # LabelValue only if the name is not in the config. Then composite each
        # segment's mask at that label -- order/empties cannot permute the output.
        editing_label_by_name = {
            segment_definition.name: segment_definition.label
            for segment_definition in editing.segments
        }
        reference_array = slicer.util.arrayFromVolume(reference_volume_node)
        output_array = np.zeros(reference_array.shape, dtype=np.int16)

        diagnostics = []
        segmentation = self.currentEditableNode.GetSegmentation()
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)
        for segment_index in range(segment_ids.GetNumberOfValues()):
            segment_id = segment_ids.GetValue(segment_index)
            segment = segmentation.GetSegment(segment_id)
            if not segment:
                continue
            segment_name = segment.GetName()
            label_value = editing_label_by_name.get(segment_name)
            label_source = "name"
            if label_value is None:
                label_value = int(segment.GetLabelValue())
                label_source = "GetLabelValue"
            try:
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                    self.currentEditableNode, segment_id, reference_volume_node
                )
            except TypeError:
                # Older Slicer without the referenceVolumeNode argument.
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                    self.currentEditableNode, segment_id
                )
            voxel_count = int((mask > 0).sum()) if mask is not None else 0
            diagnostics.append(
                f"  '{segment_name}' -> writes label {label_value} (via {label_source}; "
                f"GetLabelValue={segment.GetLabelValue()}, voxels={voxel_count})"
            )
            if mask is None:
                continue
            if mask.shape != output_array.shape:
                raise RuntimeError(
                    "Segment mask geometry does not match the reference volume; "
                    "refusing to export to avoid mislabeling."
                )
            output_array[mask > 0] = label_value

        print(
            "[PediatricGliomaSegmentationBrowser] Export label mapping for "
            f"{self.currentSession.display_name}:\n" + "\n".join(diagnostics)
        )

        labelmap_node = slicer.modules.volumes.logic().CloneVolume(
            reference_volume_node, "PediatricGliomaSegmentationBrowserExport"
        )
        try:
            slicer.util.updateVolumeFromArray(labelmap_node, output_array)
            if not slicer.util.saveNode(labelmap_node, output_path):
                raise RuntimeError(f"Slicer failed to save {output_path}")
        finally:
            slicer.mrmlScene.RemoveNode(labelmap_node)

        return output_path
