import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / (
    "PediatricGliomaSegmentationBrowser.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "PediatricGliomaSegmentationBrowser",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiscoverSessionsTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.images_root = self.root / "images"
        self.segmentations_root = self.root / "segmentations"
        self.participants_csv_path = (
            self.root / "pediatric-glioma-participants.csv"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def _write_participants_csv(self, rows):
        self.participants_csv_path.write_text(
            "participant_id,session_id,assignee\n"
            + "\n".join(
                f"{participant_id},{session_id},{assignee}"
                for participant_id, session_id, assignee in rows
            )
            + "\n",
            encoding="utf-8",
        )

    def test_discovers_only_complete_sessions(self):
        valid_image_dir = self.images_root / "sub-00001" / "ses-000" / "anat"
        valid_seg_dir = (
            self.segmentations_root / "sub-00001" / "ses-000" / "anat"
        )
        self._touch(valid_image_dir / "sub-00001_ses-000_T1w.nii.gz")
        self._touch(
            valid_image_dir / "sub-00001_ses-000_ce-gadolinium_T1w.nii.gz"
        )
        self._touch(valid_image_dir / "sub-00001_ses-000_T2w.nii.gz")
        self._touch(valid_image_dir / "sub-00001_ses-000_FLAIR.nii.gz")
        self._touch(
            valid_seg_dir / "sub-00001_ses-000_space-orig_dseg.nii.gz"
        )

        missing_image_dir = self.images_root / "sub-00002" / "ses-000" / "anat"
        missing_seg_dir = (
            self.segmentations_root / "sub-00002" / "ses-000" / "anat"
        )
        self._touch(missing_image_dir / "sub-00002_ses-000_T1w.nii.gz")
        self._touch(
            missing_image_dir / "sub-00002_ses-000_ce-gadolinium_T1w.nii.gz"
        )
        self._touch(missing_image_dir / "sub-00002_ses-000_T2w.nii.gz")
        self._touch(
            missing_seg_dir / "sub-00002_ses-000_space-orig_dseg.nii.gz"
        )
        self._write_participants_csv(
            [
                ("sub-00001", "ses-000", "BK"),
                ("sub-00002", "ses-000", "AG"),
            ]
        )

        sessions = self.module.discover_sessions(
            str(self.images_root),
            str(self.segmentations_root),
            str(self.participants_csv_path),
            "BK",
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_key, "sub-00001/ses-000")
        self.assertEqual(
            [Path(path).name for path in sessions[0].image_paths],
            [
                "sub-00001_ses-000_ce-gadolinium_T1w.nii.gz",
                "sub-00001_ses-000_T1w.nii.gz",
                "sub-00001_ses-000_T2w.nii.gz",
                "sub-00001_ses-000_FLAIR.nii.gz",
            ],
        )
        self.assertEqual(
            Path(sessions[0].segmentation_path).name,
            "sub-00001_ses-000_space-orig_dseg.nii.gz",
        )

    def test_reads_assigned_sessions_in_csv_order(self):
        self._write_participants_csv(
            [
                ("sub-00003", "ses-000", "BK"),
                ("sub-00001", "ses-001", "BK"),
                ("sub-00003", "ses-000", "BK"),
                ("sub-00002", "ses-000", "AG"),
            ]
        )

        self.assertEqual(
            self.module._read_assigned_session_keys(
                str(self.participants_csv_path),
                "BK",
            ),
            [("sub-00003", "ses-000"), ("sub-00001", "ses-001")],
        )

    def test_display_name_mapping(self):
        self.assertEqual(
            self.module._display_name_for_image_path(
                "/tmp/sub-00001_ses-000_ce-gadolinium_T1w.nii.gz"
            ),
            "T1post",
        )
        self.assertEqual(
            self.module._display_name_for_image_path(
                "/tmp/sub-00001_ses-000_T1w.nii.gz"
            ),
            "T1pre",
        )
        self.assertEqual(
            self.module._display_name_for_image_path(
                "/tmp/sub-00001_ses-000_FLAIR.nii.gz"
            ),
            "FLAIR",
        )
        self.assertEqual(
            self.module._display_name_for_image_path(
                "/tmp/sub-00001_ses-000_T2.nii.gz"
            ),
            "T2",
        )

    def test_displayed_volume_names(self):
        self.assertEqual(
            self.module._displayed_volume_names(use_subtraction=True),
            ["T1post", "T1pre", "FLAIR", "T1 subtraction"],
        )
        self.assertEqual(
            self.module._displayed_volume_names(use_subtraction=False),
            ["T1post", "T1pre", "FLAIR", "T2"],
        )
        self.assertEqual(
            self.module._display_name_for_image_path(
                "/tmp/sub-00001_ses-000_T2w.nii.gz"
            ),
            "T2",
        )

    def test_available_editing_source_names(self):
        self.assertEqual(
            self.module._available_editing_source_names(
                [
                    "T2",
                    "FLAIR",
                    "T1post",
                    "other",
                    "T1 subtraction",
                ]
            ),
            ["T1post", "FLAIR", "T1 subtraction", "T2"],
        )


if __name__ == "__main__":
    unittest.main()
