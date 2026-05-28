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


@dataclass(frozen=True)
class SessionRecord:
    subject_id: str
    session_id: str
    image_paths_by_name: Dict[str, str]
    display_image_names: List[str]
    segmentations: List[SessionSegmentation] = field(default_factory=list)

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
            )
        )

    for segmentation_definition in segmentation_definitions:
        if not segmentation_definition.folders_glob:
            raise RuntimeError(
                "Each segmentation entry must define 'segmentation_folders' "
                "or 'folders'."
            )

    return segmentation_definitions


def _normalize_config_values(config_values: dict) -> dict:
    image_section = _normalize_image_section(config_values)
    segmentation_definitions = _normalize_segment_definitions(config_values)
    return {
        "images": image_section,
        "segmentations": segmentation_definitions,
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
                valid_session = False
                break
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

        sessions.append(
            SessionRecord(
                subject_id=session_key[0],
                session_id=session_key[1],
                image_paths_by_name=image_paths_by_name,
                display_image_names=list(displayed_image_names),
                segmentations=segmentation_records,
            )
        )

    return sessions


if default_config_path:
    _load_config_values(default_config_path)

try:
    import ctk
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
        self.loadConfigButton = None
        self.refreshButton = None
        self.previousButton = None
        self.nextButton = None
        self.sessionSelector = None
        self.statusLabel = None
        self.pathsLabel = None

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

        self.layout.addStretch(1)

        self.loadConfigButton.connect("clicked()", self.selectConfigFile)
        self.refreshButton.connect("clicked()", self.refreshSessions)
        self.previousButton.connect("clicked()", self.loadPreviousSession)
        self.nextButton.connect("clicked()", self.loadNextSession)
        self.sessionSelector.connect("currentIndexChanged(int)", self.onSessionSelected)

        self.installVisibilityShortcut()
        self.installSegmentationCyclingShortcuts()
        self.updateConfigDisplay()
        self.refreshSessions()

    def cleanup(self):
        if self.logic:
            self.logic.removeManagedNodesFromScene()
        self.removeVisibilityShortcut()
        self.removeSegmentationCyclingShortcuts()

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
            self.statusLabel.text = (
                f"Loaded {session.display_name} "
                f"({index + 1}/{self.sessionSelector.count}) with "
                f"{len(session.display_image_names)} displayed image(s) and "
                f"{len(session.segmentations)} segmentation(s)."
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

    def refreshSessions(self) -> List[SessionRecord]:
        self.sessions = discover_sessions()
        return self.sessions

    def clearLoadedSession(self):
        self._removePreviouslyLoadedNodes()

    def activeSegmentationName(self):
        if not self.currentSegmentationNodes:
            return None
        if self.currentVisibleSegmentationIndex is None:
            return None
        if not (0 <= self.currentVisibleSegmentationIndex < len(self.currentSegmentationNodes)):
            return None
        return self.currentSegmentationNodes[self.currentVisibleSegmentationIndex].GetName()

    def toggleSegmentationVisibility(self):
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

        for session_segmentation in session.segmentations:
            segmentation_node = self._loadSegmentation(session_segmentation)
            self.currentSegmentationNodes.append(segmentation_node)

        self._initializeVisibleSegmentation(session)
        self._assignVolumesToViews(display_volume_nodes)
        self._activateWindowLevelTool()

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
