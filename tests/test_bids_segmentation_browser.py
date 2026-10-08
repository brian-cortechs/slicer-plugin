import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "BidsSegmentationBrowser.py"


def load_module():
    sys.modules.pop("BidsSegmentationBrowser", None)
    spec = importlib.util.spec_from_file_location(
        "BidsSegmentationBrowser",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ModalityAndPathHelpersTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_modality_from_short_and_canonical_names(self):
        self.assertEqual(
            self.module.modality_from_filename(
                "sub-A_ses-1_T1post.nii.gz"
            ),
            "T1post",
        )
        self.assertEqual(
            self.module.modality_from_filename(
                "sub-A_ses-1_ce-gadolinium_T1w.nii.gz"
            ),
            "T1post",
        )
        self.assertEqual(
            self.module.modality_from_filename("sub-A_ses-1_T1pre.nii.gz"),
            "T1pre",
        )
        self.assertEqual(
            self.module.modality_from_filename("sub-A_ses-1_T1w.nii.gz"),
            "T1pre",
        )
        self.assertEqual(
            self.module.modality_from_filename("sub-A_ses-1_FLAIR.nii.gz"),
            "FLAIR",
        )
        self.assertEqual(
            self.module.modality_from_filename("sub-A_ses-1_T2.nii.gz"),
            "T2",
        )
        self.assertEqual(
            self.module.modality_from_filename("sub-A_ses-1_T2w.nii.gz"),
            "T2",
        )

    def test_t1pre_does_not_match_t1post_canonical(self):
        self.assertNotEqual(
            self.module.modality_from_filename(
                "sub-A_ses-1_ce-gadolinium_T1w.nii.gz"
            ),
            "T1pre",
        )

    def test_bids_subject_session_from_filename_and_dirs(self):
        self.assertEqual(
            self.module.bids_subject_session_from_path(
                "/tmp/sub-00001_ses-000_T1post.nii.gz"
            ),
            ("sub-00001", "ses-000"),
        )
        self.assertEqual(
            self.module.bids_subject_session_from_path(
                "/data/sub-00001/ses-000/anat/image.nii.gz"
            ),
            ("sub-00001", "ses-000"),
        )
        self.assertIsNone(
            self.module.bids_subject_session_from_path("/tmp/not-bids.nii.gz")
        )

    def test_preferred_display_modality(self):
        self.assertEqual(
            self.module.preferred_display_modality(
                {"FLAIR": "a", "T1pre": "b", "T1post": "c"}
            ),
            "T1post",
        )
        self.assertEqual(
            self.module.preferred_display_modality({"FLAIR": "a", "T1pre": "b"}),
            "T1pre",
        )
        self.assertEqual(
            self.module.preferred_display_modality({"FLAIR": "a", "T2": "b"}),
            "FLAIR",
        )
        self.assertIsNone(self.module.preferred_display_modality({}))

    def test_segmentation_output_path(self):
        path = self.module.segmentation_output_path(
            "/out", "sub-001", "ses-002"
        )
        self.assertEqual(
            Path(path),
            Path("/out/sub-001/ses-002/anat/sub-001_ses-002_space-orig_dseg.nii.gz"),
        )

    def test_find_existing_segmentation_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            anat = root / "sub-001" / "ses-002" / "anat"
            anat.mkdir(parents=True)
            missing = self.module.find_existing_segmentation_path(
                str(root), "sub-001", "ses-002"
            )
            self.assertIsNone(missing)

            seg_path = anat / "sub-001_ses-002_space-orig_dseg.nii.gz"
            seg_path.write_text("", encoding="utf-8")
            found = self.module.find_existing_segmentation_path(
                str(root), "sub-001", "ses-002"
            )
            self.assertEqual(Path(found), seg_path)

    def test_export_label_resolves_from_segment_name(self):
        self.assertEqual(
            self.module.export_label_for_segment_name("Segment_2"), 2
        )
        self.assertEqual(
            self.module.export_label_for_segment_name("Label_5"), 5
        )
        self.assertEqual(self.module.export_label_for_segment_name("3"), 3)
        # Name wins over any notion of "first remaining segment" → 1.
        self.assertNotEqual(
            self.module.export_label_for_segment_name("Segment_2"), 1
        )
        with self.assertRaises(RuntimeError):
            self.module.export_label_for_segment_name("tumor")


class DiscoverCasesTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def test_discovers_partial_and_complete_cases(self):
        complete = self.root / "sub-00001" / "ses-000" / "anat"
        self._touch(complete / "sub-00001_ses-000_T1post.nii.gz")
        self._touch(complete / "sub-00001_ses-000_T1pre.nii.gz")
        self._touch(complete / "sub-00001_ses-000_FLAIR.nii.gz")

        partial = self.root / "sub-00002" / "ses-000" / "anat"
        self._touch(partial / "sub-00002_ses-000_T1post.nii.gz")

        cases = self.module.discover_cases(str(self.root))
        self.assertEqual(len(cases), 2)
        by_key = {case.case_key: case for case in cases}
        self.assertEqual(
            set(by_key["sub-00001/ses-000"].image_paths_by_modality),
            {"T1post", "T1pre", "FLAIR"},
        )
        self.assertEqual(
            set(by_key["sub-00002/ses-000"].image_paths_by_modality),
            {"T1post"},
        )

    def test_empty_or_missing_input(self):
        self.assertEqual(self.module.discover_cases(""), [])
        self.assertEqual(
            self.module.discover_cases(str(self.root / "missing")),
            [],
        )

    def test_canonical_bids_names(self):
        anat = self.root / "sub-X" / "ses-Y" / "anat"
        self._touch(anat / "sub-X_ses-Y_ce-gadolinium_T1w.nii.gz")
        self._touch(anat / "sub-X_ses-Y_T1w.nii.gz")
        self._touch(anat / "sub-X_ses-Y_T2w.nii.gz")

        cases = self.module.discover_cases(str(self.root))
        self.assertEqual(len(cases), 1)
        self.assertEqual(
            set(cases[0].image_paths_by_modality),
            {"T1post", "T1pre", "T2"},
        )


class SeparateSegmentLayersTest(unittest.TestCase):
    def test_every_segment_separated_exactly_once(self):
        module = load_module()

        class FakeSegmentation:
            def __init__(self, segment_ids):
                self.segment_ids = list(segment_ids)
                self.separated = []

            def GetNumberOfSegments(self):
                return len(self.segment_ids)

            def GetNthSegmentID(self, index):
                return self.segment_ids[index]

            def SeparateSegmentLabelmap(self, segment_id):
                self.separated.append(segment_id)
                self.segment_ids.reverse()

        segmentation = FakeSegmentation(["a", "b", "c", "d"])
        module.separate_segment_layers(segmentation)
        self.assertEqual(segmentation.separated, ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()
