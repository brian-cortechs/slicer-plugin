# Segmentation Review

`SegmentationReview.py` is a 3D Slicer module for reviewing a glioma segmentation
on four linked axial views:

| View | Image |
|---|---|
| T1pre | T1-precontrast (`*_T1w.nii.gz`) |
| T1post | T1-postcontrast (`*_ce-gadolinium_T1w.nii.gz`) |
| T1sub | T1post minus T1pre, voxel by voxel |
| FLAIR | FLAIR |

T2 (`*_T2w.nii.gz`) has to be in the case, but it is not shown. Interpolation is
off, so voxel edges stay sharp. The segmentation is drawn on all four views.

Labels follow `derivatives/ground-truth-segs/dseg.tsv`:

| Label | Name | Color |
|---|---|---|
| 1 | Non-Enhancing Tumor Core | red |
| 2 | Surrounding Non-Enhancing FLAIR Hyperintensity | green |
| 3 | Enhancing Tissue | yellow |
| 4 | Resection Cavity | blue |

## Setup

1. In Slicer, `Edit > Application Settings > Modules`, add this repo under
   **Additional module paths**, then restart Slicer.
2. Open **Segmentation Review** (category **Segmentation**).
3. The held-out spreadsheet is filled in when that file is present:
   `/Users/brian/repos/glioma-segmentation/glioma-heldout-set/heldout_studies.csv`.
   Relative `bids_study_dir` and `segmentation_study_dir` paths are resolved from
   the dataset root (the glioma-segmentation repo root). Change either path and
   click **Load spreadsheet**.

## Reviewing

- Pick a case from the dropdown, or use **Previous** / **Next** (`[` / `]`).
- Scroll, pan, and zoom are linked across the four views. Window/level is not,
  so T1sub and FLAIR keep their own contrast.
- **Show segmentation** and **Opacity** control the overlay. `Shift+V` shows or hides every segment.
- If a case is missing T1-precontrast, T1-postcontrast, T2, or FLAIR, or those
  two T1 images are not the same size, an error is shown and the case already
  on screen stays loaded.

## Reload during development

1. `Edit > Application Settings > Developer`, turn on **Developer mode**.
2. Restart Slicer once so it drops the old module file, then reopen
   **Segmentation Review** and use **Reload**, or run:

```python
slicer.util.reloadScriptedModule("SegmentationReview")
```
