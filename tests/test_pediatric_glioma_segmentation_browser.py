import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / (
    "PediatricGliomaSegmentationBrowser.py"
)


def load_module():
    sys.modules.pop("PediatricGliomaSegmentationBrowser", None)
    spec = importlib.util.spec_from_file_location(
        "PediatricGliomaSegmentationBrowser",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DiscoverSessionsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.images_root = self.root / "images-root"
        self.segmentations_root = self.root / "segmentations-root"
        self.default_config_path = Path(__file__).resolve().parents[1] / (
            "peds-glioma-segs.json"
        )
        self.original_default_config = self.default_config_path.read_text(
            encoding="utf-8"
        )

    def tearDown(self):
        self.default_config_path.write_text(
            self.original_default_config,
            encoding="utf-8",
        )
        self.temp_dir.cleanup()

    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def _set_default_config(self):
        t1post_regex = (
            "^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\\\\.nii\\\\.gz$"
        )
        t1pre_regex = "^sub-[^_]+_ses-[^_]+_T1w\\\\.nii\\\\.gz$"
        flair_regex = "^sub-[^_]+_ses-[^_]+_FLAIR\\\\.nii\\\\.gz$"
        t2_regex = "^sub-[^_]+_ses-[^_]+_T2w?\\\\.nii\\\\.gz$"
        dseg_regex = "^sub-[^_]+_ses-[^_]+_space-orig_dseg\\\\.nii\\\\.gz$"

        self.default_config_path.write_text(
            f"""
{{
  "image_folders": "{self.images_root.as_posix()}/*",
  "image_subfolder": "ses-???/anat",
  "images": [
    {{
      "display_name": "T1post",
      "filename_regex": "{t1post_regex}",
      "display": true
    }},
    {{
      "display_name": "T1pre",
      "filename_regex": "{t1pre_regex}",
      "display": true
    }},
    {{
      "display_name": "FLAIR",
      "filename_regex": "{flair_regex}",
      "display": true
    }},
    {{
      "display_name": "T2",
      "filename_regex": "{t2_regex}",
      "display": true
    }}
  ],
  "segmentations": [
    {{
      "segmentation_folders": "{self.segmentations_root.as_posix()}/*",
      "segmentation_subfolder": "ses-???/anat",
      "display_name": "Glioma segmentation",
      "filename_regex": "{dseg_regex}",
      "visible": true,
      "display_type": "fill",
      "segments": [
        {{
          "label": 1,
          "name": "enhancing tissue",
          "color": [255, 0, 0],
          "visible": true
        }}
      ]
    }}
  ]
}}
""".strip(),
            encoding="utf-8",
        )

    def _load_module(self):
        self._set_default_config()
        return load_module()

    def test_discovers_only_complete_sessions(self):
        module = self._load_module()

        valid_image_dir = self.images_root / "sub-00001" / "ses-000" / "anat"
        valid_seg_dir = (
            self.segmentations_root / "sub-00001" / "ses-000" / "anat"
        )
        self._touch(
            valid_image_dir / "sub-00001_ses-000_ce-gadolinium_T1w.nii.gz"
        )
        self._touch(valid_image_dir / "sub-00001_ses-000_T1w.nii.gz")
        self._touch(valid_image_dir / "sub-00001_ses-000_FLAIR.nii.gz")
        self._touch(valid_image_dir / "sub-00001_ses-000_T2w.nii.gz")
        self._touch(valid_seg_dir / "sub-00001_ses-000_space-orig_dseg.nii.gz")

        incomplete_image_dir = (
            self.images_root / "sub-00002" / "ses-000" / "anat"
        )
        incomplete_seg_dir = (
            self.segmentations_root / "sub-00002" / "ses-000" / "anat"
        )
        self._touch(
            incomplete_image_dir / "sub-00002_ses-000_ce-gadolinium_T1w.nii.gz"
        )
        self._touch(incomplete_image_dir / "sub-00002_ses-000_T1w.nii.gz")
        self._touch(incomplete_image_dir / "sub-00002_ses-000_T2w.nii.gz")
        self._touch(
            incomplete_seg_dir / "sub-00002_ses-000_space-orig_dseg.nii.gz"
        )

        sessions = module.discover_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_key, "sub-00001/ses-000")
        self.assertEqual(
            sessions[0].display_image_names,
            [
                "T1post",
                "T1pre",
                "FLAIR",
                "T2",
            ],
        )
        self.assertEqual(
            [
                Path(sessions[0].image_paths_by_name[name]).name
                for name in sessions[0].display_image_names
            ],
            [
                "sub-00001_ses-000_ce-gadolinium_T1w.nii.gz",
                "sub-00001_ses-000_T1w.nii.gz",
                "sub-00001_ses-000_FLAIR.nii.gz",
                "sub-00001_ses-000_T2w.nii.gz",
            ],
        )
        self.assertEqual(
            Path(sessions[0].segmentations[0].path).name,
            "sub-00001_ses-000_space-orig_dseg.nii.gz",
        )

    def test_bids_subject_session_parser(self):
        module = self._load_module()
        self.assertEqual(
            module._bids_subject_session_from_path(
                "/tmp/sub-00001_ses-000_ce-gadolinium_T1w.nii.gz"
            ),
            ("sub-00001", "ses-000"),
        )
        self.assertEqual(
            module._bids_subject_session_from_path("/tmp/not-bids.nii.gz"),
            None,
        )

    def test_export_label_resolves_by_name_and_rejects_unconfigured(self):
        module = self._load_module()
        segments = [
            module.SegmentDefinition(label=1, name="enhancing tumor"),
            module.SegmentDefinition(label=5, name="resection cavity"),
        ]
        # Name wins over segment order: the second entry must not resolve to 2.
        self.assertEqual(
            module._export_label_for_segment_name("resection cavity", segments),
            5,
        )
        with self.assertRaises(RuntimeError):
            module._export_label_for_segment_name("Segment_1", segments)

    def test_regex_prevents_t1pre_from_matching_t1post(self):
        module = self._load_module()
        t1post_regex = (
            "^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\\.nii\\.gz$"
        )
        self.assertEqual(
            module._match_filename_rule(
                "sub-00001_ses-000_ce-gadolinium_T1w.nii.gz",
                t1post_regex,
                "regex",
            ),
            True,
        )
        self.assertEqual(
            module._match_filename_rule(
                "sub-00001_ses-000_T1w.nii.gz",
                t1post_regex,
                "regex",
            ),
            False,
        )

    def test_load_config_values(self):
        module = self._load_module()
        config_path = self.root / "test-config.json"
        config_path.write_text(
            """
{
  "image_folders": "/tmp/images/*",
  "image_subfolder": "ses-???/anat",
  "images": [
    {
      "display_name": "T1post",
      "filename_regex": "^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\\\\.nii\\\\.gz$",
      "display": true
    }
  ],
  "segmentations": [
    {
      "segmentation_folders": "/tmp/segs/*",
      "display_name": "Seg",
      "filename": "*_dseg.nii.gz",
      "visible": true,
      "display_type": "outline",
      "segments": [
        {
          "label": "1",
          "name": "one",
          "color": [255, 0, 0],
          "visible": true
        }
      ]
    }
  ]
}
""".strip(),
            encoding="utf-8",
        )

        config = module._load_config_values(str(config_path))

        self.assertEqual(config["images"]["folders_glob"], "/tmp/images/*")
        self.assertEqual(config["images"]["displayed_names"], ["T1post"])
        self.assertEqual(config["segmentations"][0].pattern_type, "glob")
        self.assertEqual(config["segmentations"][0].segments[0].label, 1)
        self.assertEqual(
            config["segmentations"][0].segments[0].color,
            [1.0, 0.0, 0.0],
        )

    def test_toggle_segmentation_visibility(self):
        module = self._load_module()

        class FakeDisplayNode:
            def __init__(self):
                self.visible = True

            def GetVisibility(self):
                return self.visible

            def SetVisibility(self, visible):
                self.visible = bool(visible)

        class FakeSegmentationNode:
            def __init__(self, name):
                self.name = name
                self.display_node = FakeDisplayNode()

            def GetDisplayNode(self):
                return self.display_node

            def GetName(self):
                return self.name

        logic = module.PediatricGliomaSegmentationBrowserLogic()
        logic.currentSegmentationNodes = [
            FakeSegmentationNode("seg A"),
            FakeSegmentationNode("seg B"),
        ]
        logic.currentVisibleSegmentationIndex = 0

        self.assertFalse(logic.toggleSegmentationVisibility())
        self.assertFalse(
            logic.currentSegmentationNodes[0].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[1].GetDisplayNode().visible
        )
        self.assertTrue(logic.toggleSegmentationVisibility())
        self.assertTrue(
            logic.currentSegmentationNodes[0].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[1].GetDisplayNode().visible
        )

    def test_cycle_visible_segmentation_keeps_only_one_visible(self):
        module = self._load_module()

        class FakeDisplayNode:
            def __init__(self):
                self.visible = False

            def GetVisibility(self):
                return self.visible

            def SetVisibility(self, visible):
                self.visible = bool(visible)

        class FakeSegmentationNode:
            def __init__(self, name):
                self.name = name
                self.display_node = FakeDisplayNode()

            def GetDisplayNode(self):
                return self.display_node

            def GetName(self):
                return self.name

        logic = module.PediatricGliomaSegmentationBrowserLogic()
        logic.currentSegmentationNodes = [
            FakeSegmentationNode("seg A"),
            FakeSegmentationNode("seg B"),
            FakeSegmentationNode("seg C"),
        ]
        logic.currentVisibleSegmentationIndex = 0
        logic._setExclusiveSegmentationVisibility(0, True)

        self.assertEqual(logic.cycleVisibleSegmentation(1), "seg B")
        self.assertFalse(
            logic.currentSegmentationNodes[0].GetDisplayNode().visible
        )
        self.assertTrue(
            logic.currentSegmentationNodes[1].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[2].GetDisplayNode().visible
        )

        self.assertEqual(logic.cycleVisibleSegmentation(1), "seg C")
        self.assertFalse(
            logic.currentSegmentationNodes[0].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[1].GetDisplayNode().visible
        )
        self.assertTrue(
            logic.currentSegmentationNodes[2].GetDisplayNode().visible
        )

        self.assertEqual(logic.cycleVisibleSegmentation(1), "seg A")
        self.assertTrue(
            logic.currentSegmentationNodes[0].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[1].GetDisplayNode().visible
        )
        self.assertFalse(
            logic.currentSegmentationNodes[2].GetDisplayNode().visible
        )


class FakeSegmentation:
    """Minimal vtkSegmentation stand-in that renumbers on separate, as Slicer does."""

    def __init__(self, segment_ids):
        self.segment_ids = list(segment_ids)
        self.separated = []

    def GetNumberOfSegments(self):
        return len(self.segment_ids)

    def GetNthSegmentID(self, index):
        return self.segment_ids[index]

    def SeparateSegmentLabelmap(self, segment_id):
        self.separated.append(segment_id)
        # Slicer may reorder/renumber segment IDs when a segment moves to its own
        # layer; snapshotting IDs up front is what keeps the loop correct.
        self.segment_ids.reverse()


class SeparateSegmentLayersTest(unittest.TestCase):
    def test_every_segment_separated_exactly_once(self):
        module = load_module()
        # An even count matters: with an odd one, re-reading the renumbered IDs each
        # iteration still happens to touch every segment, so the bug would hide.
        segmentation = FakeSegmentation(["a", "b", "c", "d"])

        module._separate_segment_layers(segmentation)

        self.assertEqual(segmentation.separated, ["a", "b", "c", "d"])

    def test_empty_segmentation_is_a_noop(self):
        module = load_module()
        segmentation = FakeSegmentation([])

        module._separate_segment_layers(segmentation)

        self.assertEqual(segmentation.separated, [])


if __name__ == "__main__":
    unittest.main()
