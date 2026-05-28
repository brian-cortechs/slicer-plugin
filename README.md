# Segmentation Browser

`PediatricGliomaSegmentationBrowser.py` is a view-only 3D Slicer module for
rapidly browsing pediatric glioma cases. It loads a config JSON, discovers
valid sessions by matching BIDS-style filenames, and shows the configured image
set plus the matching segmentation overlays in a linked 2x2 axial layout.

The module currently defaults to `peds-glioma-segs.json` in this repository if
that file exists. If no default JSON is present, the module starts without a
config and you can pick one with `Load config JSON`.

## What it does

- Discovers sessions by parsing `(subject, session)` from BIDS-style filenames
  such as `sub-00001_ses-000_...`.
- Matches images and segmentations by that parsed `(subject, session)` pair.
- Treats image filename rules as regex-capable so `T1post` and `T1pre` can be
  distinguished even though both end with `_T1w.nii.gz`.
- Keeps only sessions that satisfy every configured image rule and every
  configured segmentation rule exactly once.
- Lists all valid sessions in a dropdown and adds `Previous` / `Next` buttons.
- Loads the configured displayed images into a linked 2x2 axial slice layout.
- Loads the matching segmentation set(s), applies configured names/colors per
  label, and respects each segmentation's `visible` and `display_type` values.
- Turns pixel interpolation off for loaded image displays.
- Automatically activates the window/level mouse tool after each case load.
- Adds `Shift+V` to toggle visibility of the loaded segmentation overlays.
- Adds `[` and `]` to cycle backward/forward through loaded segmentations while
  keeping only one segmentation visible at a time.
- Removes nodes created by the module when switching sessions or reloading the
  module in developer mode.

This version does not embed Segment Editor and does not provide export tools.

## Config schema

The current JSON format looks like this:

```json
{
  "image_folders": "/path/to/images/*",
  "image_subfolder": "ses-???/anat",
  "images": [
    {
      "display_name": "T1post",
      "filename_regex": "^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\\.nii\\.gz$",
      "display": true
    }
  ],
  "segmentations": [
    {
      "segmentation_folders": "/path/to/segmentations/*",
      "segmentation_subfolder": "ses-???/anat",
      "display_name": "Glioma segmentation",
      "filename_regex": "^sub-[^_]+_ses-[^_]+_space-orig_dseg\\.nii\\.gz$",
      "visible": true,
      "display_type": "fill",
      "segments": [
        {
          "label": 1,
          "name": "enhancing tissue",
          "color": [255, 0, 0],
          "visible": true
        }
      ]
    }
  ]
}
```

Notes:

- `filename_regex` is preferred for modality matching.
- `filename` is still accepted as a glob-style fallback.
- `display_type` currently supports `fill` and `outline`.
- The browser layout supports at most 4 displayed images at once.

## How to use it in Slicer

1. Open 3D Slicer.
2. Go to `Edit > Application Settings > Modules`.
3. Add `/Users/brian/repos/slicer-plugin` to `Additional module paths`.
4. Restart Slicer or click `Reload and Test`.
5. Open `Segmentation Browser`.
6. If needed, click `Load config JSON` and select a config file.
7. Pick a session from the dropdown or use `Previous` / `Next`.
8. Use `Shift+V` to toggle the currently selected segmentation visibility.
9. Use `[` and `]` to cycle backward/forward through the loaded segmentations.

## Reload during development

To reload the scripted module without restarting Slicer:

1. Open `Edit > Application Settings > Developer`.
2. Turn on `Developer mode`.
3. Reopen `Segmentation Browser`.
4. Click the module's `Reload` button.

You can also reload it from the Python interactor:

```python
slicer.util.reloadScriptedModule("PediatricGliomaSegmentationBrowser")
```
