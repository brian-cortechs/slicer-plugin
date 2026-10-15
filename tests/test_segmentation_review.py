import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "SegmentationReview.py"


def load_module():
    sys.modules.pop("SegmentationReview", None)
    spec = importlib.util.spec_from_file_location("SegmentationReview", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SpreadsheetAndFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.module = load_module()

    def tearDown(self):
        self.temp.cleanup()

    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")

    def _write_csv(self, rows):
        path = self.root / "cases.csv"
        header = (
            "patient_id,study_id,session_id,operation_status,grade,glioma_type,"
            "bids_study_dir,segmentation_study_dir\n"
        )
        path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
        return path

    def _case_dirs(self, subject="sub-00001", session="ses-000"):
        image_dir = self.root / "data" / "raw" / subject / session / "anat"
        seg_dir = self.root / "data" / "segs" / subject / session / "anat"
        self._touch(image_dir / f"{subject}_{session}_T1w.nii.gz")
        self._touch(image_dir / f"{subject}_{session}_ce-gadolinium_T1w.nii.gz")
        self._touch(image_dir / f"{subject}_{session}_T2w.nii.gz")
        self._touch(image_dir / f"{subject}_{session}_FLAIR.nii.gz")
        self._touch(seg_dir / f"{subject}_{session}_space-orig_dseg.nii.gz")
        return (
            f"data/raw/{subject}/{session}",
            f"data/segs/{subject}/{session}",
        )

    def test_reads_cases_in_order(self):
        bids, segs = self._case_dirs()
        path = self._write_csv(
            [
                f"sub-00001,BraTS-GLI-00001-000,ses-000,pre,HGG,,{bids},{segs}",
            ]
        )
        cases = self.module.read_cases(str(path))
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].study_id, "BraTS-GLI-00001-000")
        self.assertEqual(cases[0].operation_status, "pre")
        self.assertEqual(
            self.module.case_label(cases[0]),
            "BraTS-GLI-00001-000 | pre | HGG | sub-00001/ses-000",
        )

    def test_reads_patient_id_when_excel_prefixes_a_bom(self):
        bids, segs = self._case_dirs()
        path = self._write_csv(
            [f"sub-00078,BraTS-GLI-00101-000,ses-000,pre,HGG,,{bids},{segs}"]
        )
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        cases = self.module.read_cases(str(path))
        self.assertEqual(cases[0].patient_id, "sub-00078")
        self.assertIn("sub-00078/ses-000", self.module.case_label(cases[0]))

    def test_missing_column_is_an_error(self):
        path = self.root / "bad.csv"
        path.write_text("patient_id\nsub-1\n", encoding="utf-8")
        with self.assertRaises(self.module.CaseLoadError) as raised:
            self.module.read_cases(str(path))
        self.assertIn("bids_study_dir", str(raised.exception))

    def test_finds_images_and_does_not_treat_postcontrast_as_pre(self):
        bids, segs = self._case_dirs()
        path = self._write_csv(
            [f"sub-00001,BraTS-GLI-00001-000,ses-000,pre,HGG,,{bids},{segs}"]
        )
        case = self.module.read_cases(str(path))[0]
        files = self.module.find_case_files(case, str(self.root))
        self.assertTrue(files.t1pre.endswith("ses-000_T1w.nii.gz"))
        self.assertTrue(files.t1post.endswith("ce-gadolinium_T1w.nii.gz"))
        self.assertTrue(files.t2.endswith("T2w.nii.gz"))
        self.assertTrue(files.flair.endswith("FLAIR.nii.gz"))
        self.assertTrue(files.segmentation.endswith("space-orig_dseg.nii.gz"))

    def test_missing_t2_is_an_error(self):
        bids, segs = self._case_dirs()
        image_dir = self.root / bids / "anat"
        (image_dir / "sub-00001_ses-000_T2w.nii.gz").unlink()
        path = self._write_csv(
            [f"sub-00001,BraTS-GLI-00001-000,ses-000,pre,,,{bids},{segs}"]
        )
        case = self.module.read_cases(str(path))[0]
        with self.assertRaises(self.module.CaseLoadError) as raised:
            self.module.find_case_files(case, str(self.root))
        self.assertIn("T2 is not present", str(raised.exception))

    def test_missing_segmentation_is_an_error(self):
        bids, segs = self._case_dirs()
        seg_file = self.root / segs / "anat" / "sub-00001_ses-000_space-orig_dseg.nii.gz"
        seg_file.unlink()
        path = self._write_csv(
            [f"sub-00001,BraTS-GLI-00001-000,ses-000,pre,,,{bids},{segs}"]
        )
        case = self.module.read_cases(str(path))[0]
        with self.assertRaises(self.module.CaseLoadError) as raised:
            self.module.find_case_files(case, str(self.root))
        self.assertIn("segmentation is not present", str(raised.exception))

    def test_duplicate_image_is_an_error(self):
        bids, segs = self._case_dirs()
        extra = self.root / bids / "anat" / "sub-00001_ses-000_T1w.nii"
        extra.write_bytes(b"")
        path = self._write_csv(
            [f"sub-00001,BraTS-GLI-00001-000,ses-000,pre,,,{bids},{segs}"]
        )
        case = self.module.read_cases(str(path))[0]
        with self.assertRaises(self.module.CaseLoadError) as raised:
            self.module.find_case_files(case, str(self.root))
        self.assertIn("more than one T1-precontrast", str(raised.exception))

    def test_infers_dataset_root_from_spreadsheet_location(self):
        bids, segs = self._case_dirs()
        nested = self.root / "tables"
        nested.mkdir()
        path = nested / "cases.csv"
        path.write_text(
            "bids_study_dir,segmentation_study_dir\n"
            f"{bids},{segs}\n",
            encoding="utf-8",
        )
        root = self.module.infer_dataset_root(str(path), bids)
        self.assertEqual(root, str(self.root))

    def test_absolute_paths_do_not_need_a_dataset_root(self):
        bids, segs = self._case_dirs()
        path = self._write_csv(
            [
                "sub-00001,BraTS-GLI-00001-000,ses-000,pre,,,"
                f"{self.root / bids},{self.root / segs}"
            ]
        )
        case = self.module.read_cases(str(path))[0]
        files = self.module.find_case_files(case, "")
        self.assertTrue(os.path.isfile(files.flair))

    def test_shape_mismatch_message(self):
        message = self.module.same_shape_error((240, 240, 155), (240, 240, 160), "BraTS-GLI-1")
        self.assertIn("240 x 240 x 155", message)
        self.assertIn("240 x 240 x 160", message)
        self.assertIsNone(self.module.same_shape_error((10, 10, 10), (10, 10, 10), "ok"))


class HeldoutSpreadsheetTest(unittest.TestCase):
    def test_heldout_cases_resolve(self):
        module = load_module()
        spreadsheet = module.DEFAULT_SPREADSHEET
        if not os.path.isfile(spreadsheet):
            self.skipTest("held-out spreadsheet is not on this machine")
        cases = module.read_cases(spreadsheet)
        self.assertGreaterEqual(len(cases), 1)
        root = module.infer_dataset_root(spreadsheet, cases[0].bids_study_dir)
        self.assertTrue(root and os.path.isdir(root))
        for case in cases:
            files = module.find_case_files(case, root)
            for path in (files.t1pre, files.t1post, files.t2, files.flair, files.segmentation):
                self.assertTrue(os.path.isfile(path), path)


if __name__ == "__main__":
    unittest.main()
