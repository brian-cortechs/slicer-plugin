# Pediatric Glioma Segmentation Browser

This repository contains a first-pass Python scripted module for 3D Slicer:
`PediatricGliomaSegmentationBrowser.py`.

The module is currently hard-coded to these dataset roots:

- Images: `/Users/brian/repos/pediatric-glioma-segmentation/data/datasets/derivatives/preprocessed/images`
- Segmentations: `/Users/brian/repos/pediatric-glioma-segmentation/data/datasets/derivatives/preprocessed/ground-truth-segs`
- Participants CSV: `/Users/brian/repos/slicer-plugin/pediatric-glioma-participants.csv`
- Output folder: `/Users/brian/repos/pediatric-glioma-segmentation/exported-segmentations`
- Assignee filter: `YOUR_INITIALS = "BK"`

## What it does

- Reads `pediatric-glioma-participants.csv` and only considers rows whose
  `assignee` matches `YOUR_INITIALS`.
- Uses each selected row's `participant_id` and `session_id` to construct the
  image and segmentation paths.
- Keeps only sessions with exactly 4 image files in `anat/`.
- Keeps only sessions with exactly 1 segmentation file containing `_dseg` in the
  matching segmentation `anat/` folder.
- Lists all valid sessions in a dropdown. Adds `Previous` and `Next` buttons for quick case-to-case navigation.
- When you select a session, unloads the prior case loaded by this module, then
  loads the 4 images and the segmentation for the selected session.
- Switches Slicer into a custom 2x2 linked axial slice layout so the 4 loaded
  modalities are visible side by side.
- Displays `T1post`, `T1pre`, `FLAIR`, and a derived `T1post - T1pre`
  subtraction image.
- If `T1post` and `T1pre` do not have matching shape and geometry, shows an
  alert and falls back to displaying `T2` instead of the subtraction image.
- Links the slice views so pan, zoom, and slice scrolling stay synchronized.
- Lets you choose an explicit `Editing source` volume for Segment Editor tools.
- Shows the chosen editing source as a foreground overlay in all four slice
  views so threshold-based editing is consistent while all backgrounds remain
  visible.
- Adds a global `Shift+V` shortcut to toggle the current segmentation
  visibility while editing.
- Uses the top-level `DISPLAYED_VIEW_VOLUME_NAMES` constant to control which
  volumes appear in the four slice views and in what order.
- Embeds the full Segment Editor pane directly in this module so you can edit
  without switching modules.
- Adds an `Export segmentation` button that writes the current segmentation to
  `OUTPUT_SEG_FOLDER` as a `.nii.gz` file using the original segmentation
  filename, without a save confirmation dialog.
- Names the loaded segmentation node `glioma segmentation`.
- Renames loaded image nodes to cleaner modality labels: `T1post`, `T1pre`,
  `FLAIR`, and `T2`.
- Turns pixel interpolation off for the loaded image displays.
- Automatically activates the window/level mouse tool after loading a case.
- Tries to point Segment Editor at the loaded segmentation and a preferred edit
  volume (`T1post` first, then `T1pre`).

## How to use it in Slicer

1. Open 3D Slicer.
2. Go to `Edit > Application Settings > Modules`.
3. Add `/Users/brian/repos/slicer-plugin` to `Additional module paths`.
4. Restart Slicer or click `Reload and Test`.
5. Open the `Pediatric Glioma Segmentation Browser` module.
6. Pick a session from the dropdown or use `Previous` / `Next`.
7. Choose an `Editing source` if you want Segment Editor tools such as
   `Threshold`, or `Paint` with masking, to operate from a specific image.
8. Adjust `Edit overlay` opacity if you want the editing source to be more or
   less visible across all views.
9. Press `Shift+V` at any time to toggle all loaded segments on or off.
10. Click `Export segmentation` to write the current edited segmentation to the
    configured output folder.

The windowing tool will be automatically selected after each case load.

## Reload during development

To reload the scripted module without restarting Slicer:

1. Open `Edit > Application Settings > Developer`.
2. Turn on `Developer mode`.
3. Reopen `Pediatric Glioma Segmentation Browser`.
4. Click the module's `Reload` button.

You can also reload it from the Python interactor:

```python
slicer.util.reloadScriptedModule("PediatricGliomaSegmentationBrowser")
```

## Notes

- Switching sessions removes the previously loaded nodes that were created by this
  module from the scene.
- This version focuses only on dataset discovery, loading, and rapid case
  switching.
