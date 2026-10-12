"""BIDS case browser with nnInteractive for interactive segmentation.

Requires an input folder (BIDS images) and an output folder (destination for
segmentations) before case browsing is enabled. Opening a case loads available
MRI modalities, optionally computes T1sub = T1post - T1pre, shows one axial
volume without interpolation, and creates (or resumes) a segmentation. Switching
cases auto-saves the current segmentation in BIDS layout under the output folder.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


managed_node_attribute = "BidsSegmentationBrowser.ManagedNode"
bids_subject_session_pattern = re.compile(r"(sub-[^_]+)_(ses-[^_]+)")
subject_dir_pattern = re.compile(r"^sub-")
session_dir_pattern = re.compile(r"^ses-")

# Filename suffix → modality name. Longer / more-specific suffixes first.
# Supports both short CTX names (T1pre/T1post) and canonical BIDS (T1w / ce-gadolinium_T1w).
MODALITY_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("ce-gadolinium_T1w", "T1post"),
    ("T1post", "T1post"),
    ("T1pre", "T1pre"),
    ("T1w", "T1pre"),
    ("FLAIR", "FLAIR"),
    ("T2w", "T2"),
    ("T2", "T2"),
)

DISPLAY_PREFERENCE = ("T1post", "T1pre")
T1SUB_NAME = "T1sub"
SEG_FILENAME_TEMPLATE = "{subject}_{session}_space-orig_dseg.nii.gz"
# Object name of the root widget loaded from SlicerNNInteractive.ui
NNINTERACTIVE_UI_OBJECT_NAME = "nnInteractive"
# Segment names encode the integer label written on save (Segment_2 → label 2).
# Do not trust Slicer's GetLabelValue() / segment order after editing.
_SEGMENT_LABEL_NAME_RE = re.compile(
    r"^(?:segment|label)[_\s-]*(\d+)$",
    re.IGNORECASE,
)

# TEMPORARY: hard-coded default folders for local development. Remove this block
# (and `_apply_temporary_default_folders` below) when folder persistence lands.
TEMPORARY_DEFAULT_INPUT_FOLDER = os.path.expanduser(
    "~/repos/meningioma-segmentation/data/datasets/sourcedata/"
    "ctx-customers/preprocessed-niftis"
)
TEMPORARY_DEFAULT_OUTPUT_FOLDER = os.path.expanduser(
    "~/repos/meningioma-segmentation/data/datasets/sourcedata/"
    "ctx-customers/ground-truth-segmentations"
)


@dataclass(frozen=True)
class CaseRecord:
    subject_id: str
    session_id: str
    image_paths_by_modality: Dict[str, str] = field(default_factory=dict)

    @property
    def case_key(self) -> str:
        return f"{self.subject_id}/{self.session_id}"

    @property
    def display_name(self) -> str:
        modalities = ", ".join(sorted(self.image_paths_by_modality))
        return f"{self.subject_id} | {self.session_id}  ({modalities})"


def _strip_nifti_suffix(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".nii.gz"):
        return filename[: -len(".nii.gz")]
    if lower.endswith(".nii"):
        return filename[: -len(".nii")]
    return filename


def modality_from_filename(filename: str) -> Optional[str]:
    """Map a BIDS-like nifti basename to a modality name, or None if unknown."""
    stem = _strip_nifti_suffix(os.path.basename(filename))
    for suffix, modality in MODALITY_SUFFIXES:
        if stem.endswith("_" + suffix) or stem.endswith(suffix):
            # Avoid matching ce-gadolinium_T1w as plain T1w (already ordered, but
            # guard the short T1w suffix explicitly).
            if suffix == "T1w" and "ce-gadolinium_T1w" in stem:
                continue
            if suffix == "T2" and stem.endswith("_T2w"):
                continue
            return modality
    return None


def bids_subject_session_from_path(file_path: str) -> Optional[Tuple[str, str]]:
    match = bids_subject_session_pattern.search(os.path.basename(file_path))
    if match:
        return match.group(1), match.group(2)

    # Fall back to directory names: .../sub-X/ses-Y/...
    parts = [part for part in file_path.split(os.sep) if part]
    subject_id = None
    session_id = None
    for part in parts:
        if subject_id is None and subject_dir_pattern.match(part):
            subject_id = part
        elif session_id is None and session_dir_pattern.match(part):
            session_id = part
    if subject_id and session_id:
        return subject_id, session_id
    return None


def preferred_display_modality(modalities: Dict[str, str]) -> Optional[str]:
    for name in DISPLAY_PREFERENCE:
        if name in modalities:
            return name
    if modalities:
        return sorted(modalities)[0]
    return None


def segmentation_output_path(
    output_folder: str, subject_id: str, session_id: str
) -> str:
    filename = SEG_FILENAME_TEMPLATE.format(subject=subject_id, session=session_id)
    return os.path.join(output_folder, subject_id, session_id, "anat", filename)


def export_label_for_segment_name(segment_name: str) -> int:
    """Integer label for a segment, taken from its name (Segment_N / Label_N)."""
    name = (segment_name or "").strip()
    match = _SEGMENT_LABEL_NAME_RE.match(name)
    if match:
        return int(match.group(1))
    if name.isdigit():
        return int(name)
    raise RuntimeError(
        f"Segment '{segment_name}' must be named Segment_N (or Label_N) so its "
        "integer label is preserved on save. Rename it before saving."
    )


def sync_segment_names_from_label_values(segmentation) -> None:
    """After loading a labelmap, name each segment Segment_<label> from LabelValue."""
    segment_ids = [
        segmentation.GetNthSegmentID(segment_index)
        for segment_index in range(segmentation.GetNumberOfSegments())
    ]
    for segment_id in segment_ids:
        segment = segmentation.GetSegment(segment_id)
        if not segment:
            continue
        label = int(segment.GetLabelValue())
        if label <= 0:
            raise RuntimeError(
                "Loaded a segment with non-positive LabelValue; refusing to "
                "guess an integer label."
            )
        segment.SetName(f"Segment_{label}")
        segment.SetLabelValue(label)


def sync_segment_label_values_from_names(segmentation) -> None:
    """Re-assert each segment's LabelValue from its Segment_N name."""
    segment_ids = [
        segmentation.GetNthSegmentID(segment_index)
        for segment_index in range(segmentation.GetNumberOfSegments())
    ]
    for segment_id in segment_ids:
        segment = segmentation.GetSegment(segment_id)
        if not segment:
            continue
        label = export_label_for_segment_name(segment.GetName())
        segment.SetLabelValue(label)


def ensure_semantic_segments(segmentation, labels=(1, 2)) -> None:
    """Ensure Segment_N exists for each label and each sits on its own labelmap layer.

    nnInteractive / Segment Editor can pack several segments into one shared binary
    labelmap (one integer per voxel). Prompting a new ROI then overwrites siblings.
    Call this after load and after adding segments.
    """
    labels_present = set()
    segment_ids = [
        segmentation.GetNthSegmentID(segment_index)
        for segment_index in range(segmentation.GetNumberOfSegments())
    ]
    for segment_id in segment_ids:
        segment = segmentation.GetSegment(segment_id)
        if not segment:
            continue
        try:
            label = export_label_for_segment_name(segment.GetName())
        except RuntimeError:
            label = int(segment.GetLabelValue() or 0)
        if label <= 0:
            continue
        labels_present.add(label)
        segment.SetName(f"Segment_{label}")
        segment.SetLabelValue(label)

    for label in labels:
        if label in labels_present:
            continue
        segment_id = segmentation.AddEmptySegment("", f"Segment_{label}")
        segment = segmentation.GetSegment(segment_id)
        if segment:
            segment.SetName(f"Segment_{label}")
            segment.SetLabelValue(label)

    separate_segment_layers(segmentation)
    sync_segment_label_values_from_names(segmentation)


def find_existing_segmentation_path(
    output_folder: str, subject_id: str, session_id: str
) -> Optional[str]:
    """Return a path to an existing case segmentation under output_folder, if any."""
    canonical = segmentation_output_path(output_folder, subject_id, session_id)
    if os.path.isfile(canonical):
        return canonical

    anat_dir = os.path.join(output_folder, subject_id, session_id, "anat")
    if not os.path.isdir(anat_dir):
        return None

    candidates = []
    for filename in sorted(os.listdir(anat_dir)):
        if not (filename.endswith(".nii") or filename.endswith(".nii.gz")):
            continue
        lower = filename.lower()
        if "dseg" in lower or lower.endswith("_seg.nii") or lower.endswith("_seg.nii.gz"):
            candidates.append(os.path.join(anat_dir, filename))

    if not candidates:
        return None
    for candidate in candidates:
        if "space-orig_dseg" in os.path.basename(candidate):
            return candidate
    return candidates[0]


def discover_cases(input_folder: str) -> List[CaseRecord]:
    """Discover BIDS subject/session cases that contain at least one nifti."""
    if not input_folder or not os.path.isdir(input_folder):
        return []

    matches_by_case: Dict[Tuple[str, str], Dict[str, str]] = {}
    for root, _dirs, files in os.walk(input_folder):
        for filename in sorted(files):
            if not (filename.endswith(".nii") or filename.endswith(".nii.gz")):
                continue
            file_path = os.path.join(root, filename)
            session_key = bids_subject_session_from_path(file_path)
            if not session_key:
                continue
            modality = modality_from_filename(filename)
            if not modality:
                # Keep unknown modalities under their stem so the case is still
                # browsable and can be shown as a last-resort display image.
                modality = _strip_nifti_suffix(filename)
            case_modalities = matches_by_case.setdefault(session_key, {})
            # First match wins for a given modality name.
            case_modalities.setdefault(modality, file_path)

    cases = [
        CaseRecord(
            subject_id=subject_id,
            session_id=session_id,
            image_paths_by_modality=dict(image_paths),
        )
        for (subject_id, session_id), image_paths in sorted(matches_by_case.items())
    ]
    return cases


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


class BidsSegmentationBrowser(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "BIDS Segmentation Browser"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Cursor"]
        self.parent.helpText = (
            "Browse BIDS MRI cases, segment with nnInteractive, and save "
            "segmentations to an output folder in BIDS layout."
        )
        self.parent.acknowledgementText = ""


class BidsSegmentationBrowserWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self.inputFolderEdit = None
        self.outputFolderEdit = None
        self.inputFolderButton = None
        self.outputFolderButton = None
        self.refreshButton = None
        self.previousButton = None
        self.nextButton = None
        self.saveButton = None
        self.caseSelector = None
        self.statusLabel = None
        self.caseBrowserPanel = None
        self.nnInteractivePanel = None
        self.nnInteractiveHost = None
        self.nnInteractiveStatusLabel = None
        self._borrowedNNInteractiveUI = None
        self._nnInteractiveModuleName = None
        self._updating_ui = False
        self.undoShortcut = None
        self.redoShortcut = None
        self._undoShortcutObjectName = "BidsSegmentationBrowserUndoShortcut"
        self._redoShortcutObjectName = "BidsSegmentationBrowserRedoShortcut"

    def setup(self):
        if not SLICER_AVAILABLE:
            raise RuntimeError("This module must be run inside 3D Slicer.")

        super().setup()
        BidsSegmentationBrowserLogic.removeManagedNodesFromScene()
        self.logic = BidsSegmentationBrowserLogic()

        folders_panel = ctk.ctkCollapsibleButton()
        folders_panel.text = "Folders"
        self.layout.addWidget(folders_panel)
        folders_layout = qt.QFormLayout(folders_panel)

        self.inputFolderEdit, self.inputFolderButton = self._make_folder_row(
            folders_layout, "Input folder", "Select BIDS input image folder"
        )
        self.outputFolderEdit, self.outputFolderButton = self._make_folder_row(
            folders_layout, "Output folder", "Select segmentation output folder"
        )

        self.caseBrowserPanel = ctk.ctkCollapsibleButton()
        self.caseBrowserPanel.text = "Case Browser"
        self.layout.addWidget(self.caseBrowserPanel)
        case_layout = qt.QFormLayout(self.caseBrowserPanel)

        self.refreshButton = qt.QPushButton("Refresh cases")
        case_layout.addRow(self.refreshButton)

        self.caseSelector = qt.QComboBox()
        self.caseSelector.setSizeAdjustPolicy(qt.QComboBox.AdjustToMinimumContentsLength)
        case_layout.addRow("Case", self.caseSelector)

        navigation_layout = qt.QHBoxLayout()
        self.previousButton = qt.QPushButton("Previous")
        self.nextButton = qt.QPushButton("Next")
        self.saveButton = qt.QPushButton("Save segmentation")
        navigation_layout.addWidget(self.previousButton)
        navigation_layout.addWidget(self.nextButton)
        navigation_layout.addWidget(self.saveButton)
        case_layout.addRow("Navigation", navigation_layout)

        self.isolateLayersButton = qt.QPushButton("Isolate segment layers")
        self.isolateLayersButton.toolTip = (
            "Fallback only: layers are isolated automatically on case load and when "
            "a segment is added. Click if nnInteractive still seems to overwrite "
            "another ROI."
        )
        case_layout.addRow(self.isolateLayersButton)

        self.statusLabel = qt.QLabel(
            "Select an input folder and an output folder to begin."
        )
        self.statusLabel.wordWrap = True
        case_layout.addRow("Status", self.statusLabel)

        self.nnInteractivePanel = ctk.ctkCollapsibleButton()
        self.nnInteractivePanel.text = "nnInteractive"
        self.layout.addWidget(self.nnInteractivePanel)
        nn_layout = qt.QVBoxLayout(self.nnInteractivePanel)
        self.nnInteractiveStatusLabel = qt.QLabel("")
        self.nnInteractiveStatusLabel.wordWrap = True
        nn_layout.addWidget(self.nnInteractiveStatusLabel)
        self.nnInteractiveHost = qt.QWidget()
        self.nnInteractiveHost.setLayout(qt.QVBoxLayout())
        self.nnInteractiveHost.layout().setContentsMargins(0, 0, 0, 0)
        nn_layout.addWidget(self.nnInteractiveHost)

        self.layout.addStretch(1)

        self.inputFolderButton.connect("clicked()", self.onBrowseInputFolder)
        self.outputFolderButton.connect("clicked()", self.onBrowseOutputFolder)
        self.inputFolderEdit.connect("editingFinished()", self.onFoldersChanged)
        self.outputFolderEdit.connect("editingFinished()", self.onFoldersChanged)
        self.refreshButton.connect("clicked()", self.refreshCases)
        self.previousButton.connect("clicked()", self.loadPreviousCase)
        self.nextButton.connect("clicked()", self.loadNextCase)
        self.saveButton.connect("clicked()", self.onSaveClicked)
        self.isolateLayersButton.connect("clicked()", self.onIsolateLayersClicked)
        self.caseSelector.connect("currentIndexChanged(int)", self.onCaseSelected)

        self._update_enabled_state()
        # Defer nnInteractive embed: module factory attrs / widget setup are more
        # reliable after this module's setup() returns, and selectModule during
        # setup can fight the module panel swap.
        qt.QTimer.singleShot(0, self._embed_nninteractive)
        self._apply_temporary_default_folders()  # TEMPORARY

    def cleanup(self):
        try:
            if self.logic and self.logic.currentCase:
                self.logic.saveCurrentSegmentation()
        except Exception:
            pass
        self._remove_undo_redo_shortcuts()
        # Put nnInteractive's UI back before this module widget is destroyed;
        # otherwise a Reload deletes the borrowed controls permanently.
        self._restore_nninteractive_ui()
        if self.logic:
            self.logic.clearLoadedCase(save=False)
            self.logic.removeManagedNodesFromScene()

    def _make_folder_row(self, form_layout, label: str, placeholder: str):
        row = qt.QHBoxLayout()
        edit = qt.QLineEdit()
        edit.placeholderText = placeholder
        browse = qt.QPushButton("Browse…")
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form_layout.addRow(label, row)
        return edit, browse

    def onBrowseInputFolder(self):
        self._browse_folder(self.inputFolderEdit, "Select input folder")

    def onBrowseOutputFolder(self):
        self._browse_folder(self.outputFolderEdit, "Select output folder")

    def _apply_temporary_default_folders(self):
        # TEMPORARY: auto-fill folders and load cases on module open.
        # Delete this method (and its call in setup / the TEMPORARY_* constants)
        # when removing the hard-coded defaults.
        if not (self.inputFolderEdit.text or "").strip():
            self.inputFolderEdit.text = TEMPORARY_DEFAULT_INPUT_FOLDER
        if not (self.outputFolderEdit.text or "").strip():
            self.outputFolderEdit.text = TEMPORARY_DEFAULT_OUTPUT_FOLDER
            os.makedirs(TEMPORARY_DEFAULT_OUTPUT_FOLDER, exist_ok=True)
        self.onFoldersChanged()

    def _browse_folder(self, line_edit, title: str):
        start = line_edit.text or os.path.expanduser("~")
        selected = qt.QFileDialog.getExistingDirectory(
            slicer.util.mainWindow(), title, start
        )
        if isinstance(selected, (list, tuple)):
            selected = selected[0]
        if not selected:
            return
        line_edit.text = selected
        self.onFoldersChanged()

    def _resolve_nninteractive_module_name(self):
        """Return the registered module name for nnInteractive, or None."""
        # Prefer the factory lookup — slicer.modules.<name> attributes are often
        # lowercase and may be absent until the module has been opened once.
        candidates = ("SlicerNNInteractive", "NNInteractive", "nnInteractive")
        for name in candidates:
            try:
                if slicer.util.getModule(name) is not None:
                    return name
            except Exception:
                continue
        for attr_name in dir(slicer.modules):
            if "nninteractive" in attr_name.lower():
                module = getattr(slicer.modules, attr_name, None)
                if module is not None and hasattr(module, "name"):
                    return module.name
        return None

    def _ensure_nninteractive_widget(self, module_name):
        """Return the nnInteractive module widget, opening the module once if needed."""
        nn_widget = slicer.util.getModuleWidget(module_name)
        if nn_widget is not None and hasattr(nn_widget, "ui"):
            return nn_widget

        current_module = None
        try:
            current_module = slicer.util.moduleSelector().selectedModule
        except Exception:
            pass
        slicer.util.selectModule(module_name)
        nn_widget = slicer.util.getModuleWidget(module_name)
        try:
            if current_module:
                slicer.util.selectModule(current_module)
            else:
                slicer.util.selectModule("BidsSegmentationBrowser")
        except Exception:
            pass
        return nn_widget

    def _find_nninteractive_ui_root(self, nn_widget):
        """Locate the real nnInteractive.ui root; never the Reload & Test panel."""
        search_roots = []
        if self.nnInteractiveHost is not None:
            search_roots.append(self.nnInteractiveHost)
        if nn_widget is not None:
            search_roots.append(nn_widget)
            parent = getattr(nn_widget, "parent", None)
            if callable(parent):
                parent = parent()
            if parent is not None:
                search_roots.append(parent)
        main_window = slicer.util.mainWindow()
        if main_window is not None:
            search_roots.append(main_window)

        for root in search_roots:
            try:
                found = slicer.util.findChild(root, NNINTERACTIVE_UI_OBJECT_NAME)
            except Exception:
                found = None
            if found is not None:
                return found

        if nn_widget is not None and hasattr(nn_widget, "layout") and nn_widget.layout:
            layout = nn_widget.layout
            for index in range(layout.count()):
                item = layout.itemAt(index)
                child = item.widget() if item else None
                if child is not None and child.objectName == NNINTERACTIVE_UI_OBJECT_NAME:
                    return child
        return None

    def _restore_nninteractive_ui(self):
        """Return borrowed nnInteractive UI to its module so Reload cannot destroy it."""
        ui_root = self._borrowedNNInteractiveUI
        self._borrowedNNInteractiveUI = None
        if ui_root is None:
            return
        module_name = self._nnInteractiveModuleName
        nn_widget = None
        if self.logic is not None:
            nn_widget = self.logic.nnInteractiveWidget
        if nn_widget is None and module_name:
            try:
                nn_widget = slicer.util.getModuleWidget(module_name)
            except Exception:
                nn_widget = None
        if nn_widget is None or not hasattr(nn_widget, "layout") or nn_widget.layout is None:
            return
        try:
            nn_widget.layout.addWidget(ui_root)
        except Exception:
            pass

    def _embed_nninteractive(self):
        """Host the nnInteractive module UI inside this panel, if available."""
        # Always restore first — never orphan widgets with setParent(None).
        self._restore_nninteractive_ui()

        try:
            module_name = self._resolve_nninteractive_module_name()
            if not module_name:
                self.nnInteractiveStatusLabel.text = (
                    "nnInteractive extension not found. Install SlicerNNInteractive "
                    "and restart Slicer, then reopen this module."
                )
                return
            self._nnInteractiveModuleName = module_name

            nn_widget = self._ensure_nninteractive_widget(module_name)
            if nn_widget is None:
                self.nnInteractiveStatusLabel.text = (
                    "Could not load the nnInteractive module widget."
                )
                return

            ui_root = self._find_nninteractive_ui_root(nn_widget)
            if ui_root is None:
                # Prior reload may have destroyed a borrowed UI; recreate it.
                try:
                    slicer.util.reloadScriptedModule(module_name)
                except Exception:
                    pass
                nn_widget = self._ensure_nninteractive_widget(module_name)
                ui_root = self._find_nninteractive_ui_root(nn_widget)

            if ui_root is None:
                self.nnInteractiveStatusLabel.text = (
                    "Could not find the nnInteractive UI. Open the nnInteractive "
                    "module once (or restart Slicer), then reload this module."
                )
                self.logic.setNNInteractiveWidget(nn_widget)
                return

            self._borrowedNNInteractiveUI = ui_root
            self.nnInteractiveHost.layout().addWidget(ui_root)
            self.nnInteractiveStatusLabel.text = (
                "nnInteractive controls are embedded below."
            )
            self.logic.setNNInteractiveWidget(nn_widget)
            # nnInteractive registers an app-wide Ctrl+Z that only undoes its own
            # prompts and blocks Segment Editor undo (paint, etc.). Replace it,
            # and snapshot Segment Editor history before nnInteractive writes masks.
            self._patch_nninteractive_to_save_editor_undo(nn_widget)
            self._install_undo_redo_shortcuts(nn_widget)
            # Case load may have run before embed (deferred setup); re-bind now.
            if (
                self.logic.currentSegmentationNode is not None
                and self.logic.currentDisplayModality
                and self.logic.currentDisplayModality
                in self.logic.currentVolumeNodesByName
            ):
                self.logic._bind_editors(
                    self.logic.currentSegmentationNode,
                    self.logic.currentVolumeNodesByName[
                        self.logic.currentDisplayModality
                    ],
                )
        except Exception as exc:
            self.nnInteractiveStatusLabel.text = (
                f"Failed to embed nnInteractive: {exc}"
            )

    def _segment_editor_widget(self):
        nn_widget = self.logic.nnInteractiveWidget if self.logic else None
        return getattr(getattr(nn_widget, "ui", None), "editor_widget", None)

    def _remove_nninteractive_undo_shortcut(self, nn_widget):
        """Drop nnInteractive's Ctrl+Z so it cannot swallow Segment Editor undo."""
        if nn_widget is None:
            return
        shortcut_items = getattr(nn_widget, "shortcut_items", None)
        if not isinstance(shortcut_items, dict):
            return
        for key in list(shortcut_items.keys()):
            if str(key).lower().replace(" ", "") in ("ctrl+z", "meta+z", "cmd+z"):
                shortcut = shortcut_items.pop(key, None)
                if shortcut is None:
                    continue
                try:
                    shortcut.setEnabled(False)
                    shortcut.setParent(None)
                    shortcut.deleteLater()
                except Exception:
                    pass

    def _purge_competing_undo_shortcuts(self):
        """Disable any other app-wide Undo/Redo shortcuts (nnInteractive's, etc.)."""
        main_window = slicer.util.mainWindow()
        if not main_window:
            return
        undo_key = qt.QKeySequence(qt.QKeySequence.Undo).toString()
        redo_key = qt.QKeySequence(qt.QKeySequence.Redo).toString()
        for shortcut in main_window.findChildren(qt.QShortcut):
            if shortcut.objectName in (
                self._undoShortcutObjectName,
                self._redoShortcutObjectName,
            ):
                continue
            try:
                key = shortcut.key().toString()
            except Exception:
                continue
            if key in (undo_key, redo_key, "Ctrl+Z", "Meta+Z", "Ctrl+Shift+Z", "Ctrl+Y"):
                try:
                    shortcut.setEnabled(False)
                except Exception:
                    pass

    def _remove_undo_redo_shortcuts(self):
        for attr in ("undoShortcut", "redoShortcut"):
            shortcut = getattr(self, attr, None)
            if shortcut is not None:
                try:
                    shortcut.setParent(None)
                    shortcut.deleteLater()
                except Exception:
                    pass
                setattr(self, attr, None)
        main_window = slicer.util.mainWindow()
        if not main_window:
            return
        for shortcut in main_window.findChildren(qt.QShortcut):
            if shortcut.objectName in (
                self._undoShortcutObjectName,
                self._redoShortcutObjectName,
            ):
                shortcut.setParent(None)
                shortcut.deleteLater()

    def _patch_nninteractive_to_save_editor_undo(self, nn_widget):
        """Snapshot Segment Editor history before nnInteractive overwrites a mask.

        nnInteractive intentionally skips saveStateForUndo on apply_result, so its
        writes were invisible to Segment Editor Ctrl+Z. Wrap apply_result once.
        """
        if nn_widget is None or getattr(nn_widget, "_bidsBrowserUndoPatched", False):
            return
        editor = getattr(getattr(nn_widget, "ui", None), "editor_widget", None)
        if editor is None or not hasattr(editor, "saveStateForUndo"):
            print(
                "[BidsSegmentationBrowser] Segment Editor has no saveStateForUndo; "
                "nnInteractive undos may still be limited to the remote session."
            )
            return
        if not hasattr(nn_widget, "apply_result"):
            return
        original_apply_result = nn_widget.apply_result

        def apply_result_with_editor_undo(changed_bbox=None):
            try:
                editor.saveStateForUndo()
            except Exception as exc:
                print(
                    f"[BidsSegmentationBrowser] saveStateForUndo before "
                    f"nnInteractive apply failed: {exc}"
                )
            return original_apply_result(changed_bbox)

        nn_widget.apply_result = apply_result_with_editor_undo
        nn_widget._bidsBrowserUndoPatched = True
        if hasattr(editor, "setMaximumNumberOfUndoStates"):
            editor.setMaximumNumberOfUndoStates(100)

    def _install_undo_redo_shortcuts(self, nn_widget):
        self._remove_nninteractive_undo_shortcut(nn_widget)
        self._remove_undo_redo_shortcuts()
        self._purge_competing_undo_shortcuts()
        main_window = slicer.util.mainWindow()
        if not main_window:
            return

        editor = self._segment_editor_widget()
        if editor is not None and hasattr(editor, "setMaximumNumberOfUndoStates"):
            editor.setMaximumNumberOfUndoStates(100)

        self.undoShortcut = qt.QShortcut(main_window)
        self.undoShortcut.objectName = self._undoShortcutObjectName
        self.undoShortcut.setKey(qt.QKeySequence(qt.QKeySequence.Undo))
        self.undoShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.undoShortcut.connect("activated()", self.onUndo)

        self.redoShortcut = qt.QShortcut(main_window)
        self.redoShortcut.objectName = self._redoShortcutObjectName
        self.redoShortcut.setKey(qt.QKeySequence(qt.QKeySequence.Redo))
        self.redoShortcut.setContext(qt.Qt.ApplicationShortcut)
        self.redoShortcut.connect("activated()", self.onRedo)

    def _segmentation_undo_fingerprint(self):
        """Cheap fingerprint to detect whether Segment Editor undo changed anything."""
        node = self.logic.currentSegmentationNode if self.logic else None
        if node is None:
            return None
        try:
            segmentation = node.GetSegmentation()
            parts = [str(segmentation.GetNumberOfSegments())]
            for index in range(segmentation.GetNumberOfSegments()):
                segment_id = segmentation.GetNthSegmentID(index)
                segment = segmentation.GetSegment(segment_id)
                name = segment.GetName() if segment else ""
                try:
                    array = slicer.util.arrayFromSegmentBinaryLabelmap(node, segment_id)
                    voxel_count = int(array.sum()) if array is not None else -1
                except Exception:
                    voxel_count = -1
                parts.append(f"{segment_id}:{name}:{voxel_count}")
            return "|".join(parts)
        except Exception:
            return None

    def onUndo(self):
        """Undo paint/nnInteractive mask edits via Segment Editor history.

        Falls back to nnInteractive's session undo if the editor history did not
        change (e.g. older Slicer without saveStateForUndo).
        """
        editor = self._segment_editor_widget()
        nn_widget = self.logic.nnInteractiveWidget if self.logic else None

        if editor is not None and hasattr(editor, "undo"):
            before = self._segmentation_undo_fingerprint()
            try:
                editor.undo()
            except Exception as exc:
                print(f"[BidsSegmentationBrowser] Segment Editor undo failed: {exc}")
            else:
                after = self._segmentation_undo_fingerprint()
                if (
                    before is not None
                    and after is not None
                    and before != after
                ):
                    slicer.util.showStatusMessage("Undo (Segment Editor)", 2000)
                    return

        if nn_widget is not None and hasattr(nn_widget, "on_undo"):
            try:
                nn_widget.on_undo()
                return
            except Exception as exc:
                print(f"[BidsSegmentationBrowser] nnInteractive undo failed: {exc}")

        slicer.util.showStatusMessage("Nothing to undo", 2000)

    def onRedo(self):
        editor = self._segment_editor_widget()
        if editor is not None and hasattr(editor, "redo"):
            before = self._segmentation_undo_fingerprint()
            editor.redo()
            after = self._segmentation_undo_fingerprint()
            if before != after:
                slicer.util.showStatusMessage("Redo (Segment Editor)", 2000)
                return
        slicer.util.showStatusMessage("Nothing to redo", 2000)

    def _folders_ready(self) -> bool:
        input_folder = (self.inputFolderEdit.text or "").strip()
        output_folder = (self.outputFolderEdit.text or "").strip()
        return bool(input_folder and os.path.isdir(input_folder)) and bool(
            output_folder and os.path.isdir(output_folder)
        )

    def _update_enabled_state(self):
        ready = self._folders_ready()
        self.caseBrowserPanel.enabled = ready
        self.nnInteractivePanel.enabled = ready
        if not ready:
            self.statusLabel.text = (
                "Select an input folder and an output folder to begin."
            )

    def onFoldersChanged(self, _path=None):
        self._update_enabled_state()
        if not self._folders_ready():
            if self.logic:
                self.logic.clearLoadedCase(save=False)
            self.caseSelector.blockSignals(True)
            self.caseSelector.clear()
            self.caseSelector.blockSignals(False)
            return
        self.logic.setFolders(
            (self.inputFolderEdit.text or "").strip(),
            (self.outputFolderEdit.text or "").strip(),
        )
        self.refreshCases()

    def refreshCases(self):
        if not self._folders_ready():
            self._update_enabled_state()
            return

        previous_key = None
        if self.caseSelector.count:
            previous_case = self.caseSelector.itemData(self.caseSelector.currentIndex)
            previous_key = previous_case.case_key if previous_case else None

        self.caseSelector.blockSignals(True)
        self.caseSelector.clear()
        cases = self.logic.refreshCases()
        for case in cases:
            self.caseSelector.addItem(case.display_name, case)
        self.caseSelector.blockSignals(False)

        if not cases:
            self.logic.clearLoadedCase(save=False)
            self.statusLabel.text = (
                "No BIDS cases found under the input folder "
                "(expected sub-*/ses-*/anat/*.nii.gz)."
            )
            self._update_navigation_buttons()
            return

        restored_index = 0
        if previous_key:
            for index, case in enumerate(cases):
                if case.case_key == previous_key:
                    restored_index = index
                    break
        self.caseSelector.setCurrentIndex(restored_index)
        self.statusLabel.text = f"Discovered {len(cases)} case(s)."
        self.onCaseSelected(restored_index)

    def loadPreviousCase(self):
        index = self.caseSelector.currentIndex
        if index > 0:
            self.caseSelector.setCurrentIndex(index - 1)

    def loadNextCase(self):
        index = self.caseSelector.currentIndex
        if index < self.caseSelector.count - 1:
            self.caseSelector.setCurrentIndex(index + 1)

    def _update_navigation_buttons(self):
        index = self.caseSelector.currentIndex
        count = self.caseSelector.count
        has_cases = count > 0
        self.previousButton.enabled = has_cases and index > 0
        self.nextButton.enabled = has_cases and index < count - 1
        self.saveButton.enabled = has_cases and self.logic.currentCase is not None

    def onCaseSelected(self, index: int):
        self._update_navigation_buttons()
        if index < 0:
            return
        case = self.caseSelector.itemData(index)
        if not case:
            return
        try:
            warnings = self.logic.loadCase(case)
            position = f"({index + 1}/{self.caseSelector.count})"
            if self.logic.currentSegmentationSourcePath:
                seg_note = (
                    "Editing existing segmentation: "
                    f"{self.logic.currentSegmentationSourcePath}"
                )
            else:
                seg_note = "No existing segmentation; started empty."
            message = (
                f"Loaded {case.display_name} {position}. "
                f"Display: {self.logic.currentDisplayModality}. {seg_note}"
            )
            if warnings:
                message += " Warnings: " + " | ".join(warnings)
            self.statusLabel.text = message
            self._update_navigation_buttons()
        except Exception as exc:
            self.statusLabel.text = f"Failed to load {case.display_name}: {exc}"
            raise

    def onSaveClicked(self):
        try:
            output_path = self.logic.saveCurrentSegmentation()
            self.statusLabel.text = f"Saved segmentation to {output_path}"
        except Exception as exc:
            self.statusLabel.text = f"Failed to save segmentation: {exc}"
            raise

    def onIsolateLayersClicked(self):
        try:
            self.logic.isolateSegmentLayers()
            self.statusLabel.text = (
                "Isolated segment layers (manual). Select Segment_N, then prompt."
            )
        except Exception as exc:
            self.statusLabel.text = f"Failed to isolate layers: {exc}"
            raise


class BidsSegmentationBrowserLogic(ScriptedLoadableModuleLogic):
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
        self.inputFolder = ""
        self.outputFolder = ""
        self.cases: List[CaseRecord] = []
        self.currentCase: Optional[CaseRecord] = None
        self.currentDisplayModality: Optional[str] = None
        self.currentVolumeNodesByName: Dict[str, object] = {}
        self.currentEditVolumeNode = None
        self.currentSegmentationNode = None
        self.currentSegmentationSourcePath: Optional[str] = None
        self.loadedNodeIDs: List[str] = []
        self.nnInteractiveWidget = None
        self._observedSegmentation = None
        self._segmentAddedObserverTag = None
        self._suppressSegmentAddedIsolate = False

    def setFolders(self, input_folder: str, output_folder: str):
        self.inputFolder = input_folder or ""
        self.outputFolder = output_folder or ""

    def setNNInteractiveWidget(self, nn_widget):
        self.nnInteractiveWidget = nn_widget

    def refreshCases(self) -> List[CaseRecord]:
        self.cases = discover_cases(self.inputFolder)
        return self.cases

    def clearLoadedCase(self, save: bool = True):
        if save and self.currentCase and self.currentSegmentationNode:
            try:
                self.saveCurrentSegmentation()
            except Exception as exc:
                print(f"[BidsSegmentationBrowser] Auto-save failed: {exc}")
        self._unbind_editors()
        self._remove_previously_loaded_nodes()
        self.currentEditVolumeNode = None

    def loadCase(self, case: CaseRecord) -> List[str]:
        if not SLICER_AVAILABLE:
            raise RuntimeError("This logic must be run inside 3D Slicer.")
        if not self.outputFolder:
            raise RuntimeError("Output folder is not set.")

        # Persist any open case (including reload of the same case) before teardown.
        self.clearLoadedCase(save=bool(self.currentCase and self.currentSegmentationNode))

        self.currentCase = case
        self.currentVolumeNodesByName = {}
        warnings: List[str] = []

        for modality, path in case.image_paths_by_modality.items():
            self.currentVolumeNodesByName[modality] = self._load_volume(path, modality)

        t1sub_warning = self._maybe_create_t1sub(case)
        if t1sub_warning:
            warnings.append(t1sub_warning)

        display_modality = preferred_display_modality(self.currentVolumeNodesByName)
        if not display_modality:
            raise RuntimeError(f"No images available for {case.display_name}")
        self.currentDisplayModality = display_modality
        display_volume = self.currentVolumeNodesByName[display_modality]

        self.currentSegmentationNode = self._load_or_create_segmentation(case)
        # Display can stay on T1post, but paint/erase/export must use a volume whose
        # geometry matches the labelmap. Many dsegs are in T1pre grid while the
        # viewer prefers T1post — binding the editor to T1post made Eraser a no-op
        # and could auto-save empty masks.
        edit_volume = (
            self._best_edit_volume(self.currentSegmentationNode) or display_volume
        )
        self.currentEditVolumeNode = edit_volume
        if edit_volume != display_volume:
            edit_name = edit_volume.GetName() if edit_volume is not None else "?"
            warnings.append(
                f"Editing against {edit_name} (matches segmentation geometry); "
                f"displaying {display_modality}."
            )
        self._show_single_axial_volume(display_volume)
        self._bind_editors(self.currentSegmentationNode, edit_volume)
        return warnings

    def saveCurrentSegmentation(self) -> str:
        if not self.currentCase or not self.currentSegmentationNode:
            raise RuntimeError("No case/segmentation is currently loaded.")
        if not self.outputFolder:
            raise RuntimeError("Output folder is not set.")

        output_path = segmentation_output_path(
            self.outputFolder,
            self.currentCase.subject_id,
            self.currentCase.session_id,
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        reference_volume = self.currentEditVolumeNode
        if reference_volume is None:
            reference_volume = self._best_edit_volume(self.currentSegmentationNode)
        if reference_volume is None:
            reference_volume = self.currentVolumeNodesByName.get(
                self.currentDisplayModality
            )
        if reference_volume is None and self.currentVolumeNodesByName:
            reference_volume = next(iter(self.currentVolumeNodesByName.values()))
        if reference_volume is None:
            raise RuntimeError("No reference volume available for export.")

        reference_array = slicer.util.arrayFromVolume(reference_volume)
        output_array = np.zeros(reference_array.shape, dtype=np.int16)

        segmentation = self.currentSegmentationNode.GetSegmentation()
        # Avoid shared-layer corruption at export time.
        separate_segment_layers(segmentation)
        # Names are the source of truth; keep LabelValue aligned before export.
        sync_segment_label_values_from_names(segmentation)
        segment_ids = vtk.vtkStringArray()
        segmentation.GetSegmentIDs(segment_ids)
        diagnostics = []
        for segment_index in range(segment_ids.GetNumberOfValues()):
            segment_id = segment_ids.GetValue(segment_index)
            segment = segmentation.GetSegment(segment_id)
            if not segment:
                continue
            segment_name = segment.GetName()
            label_value = export_label_for_segment_name(segment_name)
            try:
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                    self.currentSegmentationNode, segment_id, reference_volume
                )
            except TypeError:
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                    self.currentSegmentationNode, segment_id
                )
            voxel_count = int((mask > 0).sum()) if mask is not None else 0
            diagnostics.append(
                f"  '{segment_name}' -> label {label_value} (voxels={voxel_count})"
            )
            if mask is None:
                continue
            if mask.shape != output_array.shape:
                raise RuntimeError(
                    "Segment mask geometry does not match the reference volume."
                )
            output_array[mask > 0] = label_value

        labeled_voxels = int((output_array > 0).sum())
        print(
            "[BidsSegmentationBrowser] Export label mapping for "
            f"{self.currentCase.display_name} (labeled_voxels={labeled_voxels}):\n"
            + ("\n".join(diagnostics) if diagnostics else "  (no segments)")
        )

        # Never write an empty labelmap over an existing file — that was wiping
        # real work when auto-save ran on case switch with a failed/empty export.
        if labeled_voxels == 0:
            if os.path.isfile(output_path):
                raise RuntimeError(
                    "Refusing to overwrite existing segmentation with an empty "
                    f"export: {output_path}"
                )
            # Don't create empty placeholder files just from browsing.
            return output_path

        labelmap_node = slicer.modules.volumes.logic().CloneVolume(
            reference_volume, "BidsSegmentationBrowserExport"
        )
        try:
            slicer.util.updateVolumeFromArray(labelmap_node, output_array)
            if not slicer.util.saveNode(labelmap_node, output_path):
                raise RuntimeError(f"Slicer failed to save {output_path}")
        finally:
            slicer.mrmlScene.RemoveNode(labelmap_node)

        return output_path

    def _track_node(self, node):
        if node and node.GetID():
            node.SetAttribute(managed_node_attribute, "1")
            self.loadedNodeIDs.append(node.GetID())

    def _remove_previously_loaded_nodes(self):
        self._remove_segmentation_observers()
        scene = slicer.mrmlScene
        for node_id in reversed(self.loadedNodeIDs):
            node = scene.GetNodeByID(node_id)
            if node:
                scene.RemoveNode(node)
        self.loadedNodeIDs = []
        self.currentCase = None
        self.currentDisplayModality = None
        self.currentVolumeNodesByName = {}
        self.currentSegmentationNode = None
        self.currentSegmentationSourcePath = None

    def _load_volume(self, image_path: str, image_name: str):
        volume_node = slicer.util.loadVolume(image_path, {"show": False})
        if not volume_node:
            raise RuntimeError(f"Could not load image: {image_path}")
        volume_node.SetName(image_name)
        display_node = volume_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        self._track_node(volume_node)
        return volume_node

    def _maybe_create_t1sub(self, case: CaseRecord) -> Optional[str]:
        t1post = self.currentVolumeNodesByName.get("T1post")
        t1pre = self.currentVolumeNodesByName.get("T1pre")
        if t1post is None or t1pre is None:
            missing = []
            if t1post is None:
                missing.append("T1post")
            if t1pre is None:
                missing.append("T1pre")
            message = (
                f"Skipping {T1SUB_NAME} for {case.display_name}: "
                f"missing {', '.join(missing)}."
            )
            slicer.util.warningDisplay(message, windowTitle="T1sub unavailable")
            return message

        mismatch = self._volume_geometry_mismatch_reason(t1post, t1pre)
        if mismatch:
            message = (
                f"Skipping {T1SUB_NAME} for {case.display_name}: {mismatch}."
            )
            slicer.util.warningDisplay(message, windowTitle="T1sub unavailable")
            return message

        subtraction_array = (
            slicer.util.arrayFromVolume(t1post).astype(np.float32)
            - slicer.util.arrayFromVolume(t1pre).astype(np.float32)
        )
        subtraction_node = slicer.modules.volumes.logic().CloneVolume(
            t1post, T1SUB_NAME
        )
        slicer.util.updateVolumeFromArray(subtraction_node, subtraction_array)
        subtraction_node.SetName(T1SUB_NAME)
        display_node = subtraction_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        self._track_node(subtraction_node)
        self.currentVolumeNodesByName[T1SUB_NAME] = subtraction_node
        return None

    def _volume_geometry_mismatch_reason(self, volume_a, volume_b) -> Optional[str]:
        image_a = volume_a.GetImageData()
        image_b = volume_b.GetImageData()
        if image_a is None or image_b is None:
            return "one or both volumes are missing image data"
        if image_a.GetDimensions() != image_b.GetDimensions():
            return (
                f"shape mismatch ({image_a.GetDimensions()} vs "
                f"{image_b.GetDimensions()})"
            )
        return None

    def isolateSegmentLayers(self):
        if not self.currentSegmentationNode:
            raise RuntimeError("No segmentation is currently loaded.")
        self._run_with_segment_added_suppressed(
            lambda: ensure_semantic_segments(
                self.currentSegmentationNode.GetSegmentation()
            )
        )

    def _run_with_segment_added_suppressed(self, fn):
        previous = self._suppressSegmentAddedIsolate
        self._suppressSegmentAddedIsolate = True
        try:
            return fn()
        finally:
            self._suppressSegmentAddedIsolate = previous

    def _remove_segmentation_observers(self):
        if (
            self._observedSegmentation is not None
            and self._segmentAddedObserverTag is not None
        ):
            try:
                self._observedSegmentation.RemoveObserver(self._segmentAddedObserverTag)
            except Exception:
                pass
        self._observedSegmentation = None
        self._segmentAddedObserverTag = None

    def _observe_segmentation_node(self, segmentation_node):
        """Auto-isolate layers whenever a segment is added (Add / Next segment)."""
        self._remove_segmentation_observers()
        if segmentation_node is None:
            return
        segmentation = segmentation_node.GetSegmentation()
        self._observedSegmentation = segmentation
        self._segmentAddedObserverTag = segmentation.AddObserver(
            slicer.vtkSegmentation.SegmentAdded,
            self._on_segment_added,
        )

    def _on_segment_added(self, caller=None, event=None):
        if self._suppressSegmentAddedIsolate:
            return
        # Defer so AddEmptySegment / nnInteractive finish selecting the new segment.
        qt.QTimer.singleShot(0, self._isolate_layers_after_segment_added)

    def _isolate_layers_after_segment_added(self):
        if self._suppressSegmentAddedIsolate or not self.currentSegmentationNode:
            return
        try:
            self._run_with_segment_added_suppressed(
                lambda: separate_segment_layers(
                    self.currentSegmentationNode.GetSegmentation()
                )
            )
            print(
                "[BidsSegmentationBrowser] Isolated labelmap layers after segment add."
            )
        except Exception as exc:
            print(f"[BidsSegmentationBrowser] Auto-isolate after add failed: {exc}")

    def _load_or_create_segmentation(self, case: CaseRecord):
        existing_path = find_existing_segmentation_path(
            self.outputFolder, case.subject_id, case.session_id
        )
        if existing_path:
            segmentation_node = self._import_segmentation_from_file(
                existing_path, f"{case.subject_id}_{case.session_id}_seg"
            )
            segmentation = segmentation_node.GetSegmentation()
            # Lock integer labels into names before layer separation can scramble
            # GetLabelValue(); export later reads the names, not segment order.
            sync_segment_names_from_label_values(segmentation)
            self.currentSegmentationSourcePath = existing_path
        else:
            segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode",
                f"{case.subject_id}_{case.session_id}_seg",
            )
            segmentation_node.CreateDefaultDisplayNodes()
            self._track_node(segmentation_node)
            self.currentSegmentationSourcePath = None

        # Always ensure Segment_1 / Segment_2 exist on isolated layers on case load.
        self._run_with_segment_added_suppressed(
            lambda: ensure_semantic_segments(segmentation_node.GetSegmentation())
        )
        self._observe_segmentation_node(segmentation_node)

        display_node = segmentation_node.GetDisplayNode()
        if display_node:
            display_node.SetVisibility(True)
            display_node.SetVisibility2D(True)
            display_node.SetVisibility2DFill(True)
            display_node.SetOpacity2DFill(0.35)
            display_node.SetVisibility2DOutline(True)
        return segmentation_node

    def _import_segmentation_from_file(self, path: str, name: str):
        segmentation_node = slicer.util.loadSegmentation(path, {"show": False})
        if segmentation_node:
            segmentation_node.SetName(name)
            self._track_node(segmentation_node)
            return segmentation_node

        labelmap_node = slicer.util.loadLabelVolume(path, {"show": False})
        if not labelmap_node:
            raise RuntimeError(f"Could not load segmentation: {path}")
        self._track_node(labelmap_node)
        segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", name
        )
        segmentation_node.CreateDefaultDisplayNodes()
        self._track_node(segmentation_node)
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

    def _show_single_axial_volume(self, volume_node):
        layout_manager = slicer.app.layoutManager()
        layout_manager.setLayout(
            slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView
        )
        slice_widget = layout_manager.sliceWidget("Red")
        if not slice_widget:
            return
        composite_node = slice_widget.sliceLogic().GetSliceCompositeNode()
        composite_node.SetDoPropagateVolumeSelection(False)
        composite_node.SetBackgroundVolumeID(volume_node.GetID())
        composite_node.SetForegroundVolumeID(None)
        composite_node.SetForegroundOpacity(0.0)
        composite_node.SetLabelVolumeID(None)
        slice_node = slice_widget.mrmlSliceNode()
        slice_node.SetOrientationToAxial()
        slice_widget.sliceLogic().FitSliceToAll()

        display_node = volume_node.GetDisplayNode()
        if display_node:
            display_node.SetInterpolate(False)
        # Do not force AdjustWindowLevel here — that steals click-drag from
        # Segment Editor paint/erase until the effect reclaims the mouse.

    def _best_edit_volume(self, segmentation_node):
        """Return the loaded volume where this segmentation's voxels are readable.

        Existing dsegs are often stored in T1pre geometry while the browser
        displays T1post. Exporting/editing against the wrong volume yields empty
        masks (silent data loss) and paint/erase that appear to do nothing.
        """
        if segmentation_node is None or not self.currentVolumeNodesByName:
            return None
        segmentation = segmentation_node.GetSegmentation()
        if segmentation is None or segmentation.GetNumberOfSegments() == 0:
            return None

        best_volume = None
        best_voxels = -1
        segment_ids = [
            segmentation.GetNthSegmentID(index)
            for index in range(segmentation.GetNumberOfSegments())
        ]
        for volume_node in self.currentVolumeNodesByName.values():
            total = 0
            for segment_id in segment_ids:
                try:
                    mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                        segmentation_node, segment_id, volume_node
                    )
                except TypeError:
                    try:
                        mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                            segmentation_node, segment_id
                        )
                    except Exception:
                        mask = None
                except Exception:
                    mask = None
                if mask is not None:
                    total += int((mask > 0).sum())
            if total > best_voxels:
                best_voxels = total
                best_volume = volume_node
        if best_voxels > 0:
            return best_volume
        return None

    def _bind_editors(self, segmentation_node, source_volume_node):
        segmentation_node.SetReferenceImageGeometryParameterFromVolumeNode(
            source_volume_node
        )
        nn_widget = self.nnInteractiveWidget
        if nn_widget is None:
            return
        try:
            editor = getattr(getattr(nn_widget, "ui", None), "editor_widget", None)
            if editor is None:
                return
            segment_editor_node = getattr(nn_widget, "segment_editor_node", None)
            if segment_editor_node is not None:
                editor.setMRMLSegmentEditorNode(segment_editor_node)
            editor.setSegmentationNode(segmentation_node)
            editor.setSourceVolumeNode(source_volume_node)
            if hasattr(editor, "setMaximumNumberOfUndoStates"):
                editor.setMaximumNumberOfUndoStates(100)
            # Mark image data stale so Initialize / next prompt re-uploads.
            if hasattr(nn_widget, "previous_states"):
                nn_widget.previous_states.pop("image_data", None)
        except Exception as exc:
            print(f"[BidsSegmentationBrowser] nnInteractive bind failed: {exc}")

    def _unbind_editors(self):
        nn_widget = self.nnInteractiveWidget
        if nn_widget is None:
            return
        try:
            editor = getattr(getattr(nn_widget, "ui", None), "editor_widget", None)
            if editor is not None:
                editor.setSegmentationNode(None)
            if hasattr(nn_widget, "previous_states"):
                nn_widget.previous_states.pop("image_data", None)
        except Exception:
            pass


def separate_segment_layers(segmentation):
    """Move every segment onto its own binary labelmap layer.

    Shared layers store one value per voxel; interactive editing (nnInteractive)
    can permanently destroy overwritten labels. Collect IDs first because
    separating a segment can renumber them.
    """
    segment_ids = [
        segmentation.GetNthSegmentID(segment_index)
        for segment_index in range(segmentation.GetNumberOfSegments())
    ]
    for segment_id in segment_ids:
        segmentation.SeparateSegmentLabelmap(segment_id)
