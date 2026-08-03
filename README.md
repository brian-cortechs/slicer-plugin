# Segmentation Browser

`PediatricGliomaSegmentationBrowser.py` is a config-driven 3D Slicer module for
reviewing **and** editing pediatric glioma segmentations. It loads a config
JSON, discovers valid sessions by matching BIDS-style filenames, and shows the
configured images plus segmentation overlays in a linked 2x2 axial layout.

It has two modes, and only one is active at a time:

- **Review** — compare read-only segmentation layers (e.g. `dev`, `onq-2896`,
  your own edits) and flip between them.
- **Segment** — edit one segmentation with the embedded Segment Editor and
  export the result.

## Per-user setup (no more personal branches)

Everyone uses the same code; you point it at your own paths with your own config
JSON. **You no longer need a personal branch with hard-coded paths.**

1. Copy the template `peds-glioma-segs.example.json` to a local config, e.g.
   `peds-glioma-segs.json` (or `something.local.json`). These names are
   git-ignored, so your personal paths never get committed.
2. Edit the paths in your copy for your machine (image folder, segmentation
   folders, and `output_folder`).
3. In Slicer, `Edit > Application Settings > Modules`, add the path to this repo
   under `Additional module paths`, then restart Slicer.
4. Open **Segmentation Browser**. It auto-loads `peds-glioma-segs.json` from the
   repo folder if present; otherwise click **Load config JSON** and pick yours.

## The label-swapping fix (why exports are now correct)

The previous editing plugin sometimes saved segments under the **wrong label**
(e.g. a region you drew as "non-enhancing tumor core" got saved as "enhancing").
Two root causes:

1. The old export wrote integer labels by **segment order**, not by the segment's
   meaning. Any case missing one of the four labels got its labels permuted.
2. Slicer's per-segment `GetLabelValue()` is itself unreliable after editing — a
   segment holding the tumor could still report value `1`.

The current export fixes this by writing each region's integer from the segment's
**name**, matched against the canonical `segments` list in your config. So a
segment named `non-enhancing tumor core` always saves as label `2`, regardless of
Slicer's internal bookkeeping or segment order. Each export also prints a
per-segment summary to the Python Console (`'<name>' -> writes label N ... voxels=...`)
so you can confirm what was saved.

> Note: ground-truth segmentations produced with the old plugin may already be
> corrupted. For those cases the `dev` originals usually hold the correct labels —
> see "Start from" below.

## Review mode

- Pick a session from the dropdown, or use `Previous` / `Next`.
- Comparison layers are listed in the config under `segmentations`. Use `[` and
  `]` to cycle backward/forward through them (only one shown at a time), and
  `Shift+V` to toggle the current layer on/off.
- Layers can be marked `"required": false` so a case still appears even if that
  layer is missing (e.g. your edits, which only exist for cases you've exported).

## Segment mode

Available when the config has an `editing` block. Switch the **Mode** dropdown to
**Segment** to reveal the Segmentation panel:

- **Start from** — choose what loads as your starting point for each case:
  - `Auto` — resume your previous export if one exists, else the edit source.
  - `Edit source` — the segmentation configured under `editing`.
  - any review layer by name (e.g. `dev seg` for the correct originals).
  - `Empty (blank)` — start from scratch.
  Changing this reloads the current case from the chosen source.
- **Editing source** — the volume the Segment Editor paints/thresholds against
  (also shown as an overlay, controlled by the **Edit overlay** opacity slider).
  Includes a computed `T1 subtraction` if configured.
- Edit with the embedded **Segment Editor**. `Ctrl+Z` / `Ctrl+Y` undo/redo, and
  `Shift+V` toggles the editable segmentation's visibility.
- **Export segmentation** writes the result to the configured `output_folder`,
  preserving the `sub-XXXXX/ses-XXX/anat/...` structure. It never overwrites the
  source you loaded.

To fix a case whose source is mislabeled, set **Start from → dev seg** (or
whichever layer has the correct labels), adjust as needed, and export.

## Config schema

```jsonc
{
  "image_folders": "/path/to/images/*",
  "image_subfolder": "ses-???/anat",
  "images": [
    { "display_name": "T1post",
      "filename_regex": "^sub-[^_]+_ses-[^_]+_ce-gadolinium_T1w\\.nii\\.gz$",
      "display": true }
  ],

  "segmentations": [
    { "segmentation_folders": "/path/to/ground-truth-segs-dev/*",
      "segmentation_subfolder": "ses-???/anat",
      "display_name": "dev seg",
      "filename_regex": "^sub-[^_]+_ses-[^_]+_space-orig_dseg\\.nii\\.gz$",
      "visible": false,
      "display_type": "fill",
      "required": false,
      "segments": [
        { "label": 1, "name": "enhancing tumor", "color": [255, 255, 0] },
        { "label": 2, "name": "nonenhancing tumor", "color": [255, 0, 0] },
        { "label": 3, "name": "cystic component", "color": [255, 140, 0] },
        { "label": 4, "name": "surrounding nonenhancing FLAIR hyperintensity", "color": [0, 255, 0] },
        { "label": 5, "name": "resection cavity", "color": [0, 255, 255] }
      ]
    }
  ],

  "editing": {
    "segmentation_folders": "/path/to/ground-truth-segs/*",
    "segmentation_subfolder": "ses-???/anat",
    "filename_regex": "^sub-[^_]+_ses-[^_]+_space-orig_dseg\\.nii\\.gz$",
    "output_folder": "/path/to/your-edited-segs",
    "display_name": "my edit",
    "display_type": "fill",
    "editing_sources": ["T1post", "T1pre", "T1 subtraction", "FLAIR", "T2"],
    "subtraction": { "display_name": "T1 subtraction", "minuend": "T1post", "subtrahend": "T1pre" },
    "segments": [
      { "label": 1, "name": "enhancing tumor", "color": [255, 255, 0] },
      { "label": 2, "name": "nonenhancing tumor", "color": [255, 0, 0] },
      { "label": 3, "name": "cystic component", "color": [255, 140, 0] },
      { "label": 4, "name": "surrounding nonenhancing FLAIR hyperintensity", "color": [0, 255, 0] },
      { "label": 5, "name": "resection cavity", "color": [0, 255, 255] }
    ]
  }
}
```

Notes:

- A session is kept only if it matches every image rule and every **required**
  segmentation rule exactly once. Omit the `editing` block for a review-only
  config.
- **Keep review layers `"required": false`.** A required layer silently removes
  every case it doesn't cover, and the result looks identical to "that data
  doesn't exist". Two separate instances of this bit us: `dev seg` /
  `onq-2896 seg` only cover the original 257-case set, and `ground-truth-segs`
  only covers the 346 sessions that have been segmented. With all four optional
  the browser lists all 409 BIDS sessions; a case with no segmentation yet is
  still editable via **Start from → Empty**.
- `filename_regex` is preferred for matching; `filename` is accepted as a
  glob-style fallback. `display_type` supports `fill` and `outline`.
- `segments` defines the canonical label scheme — names here are what the export
  uses to assign integer labels, so keep them consistent across layers.
- The canonical scheme is `derivatives/ground-truth-segs/dseg.tsv`:

  | label | name | color |
  |---|---|---|
  | 1 | enhancing tumor (ET) | yellow |
  | 2 | nonenhancing tumor (NET) | red |
  | 3 | cystic component (CC) | orange |
  | 4 | surrounding nonenhancing FLAIR hyperintensity (SNFH) | green |
  | 5 | resection cavity (RC) | cyan |

  SNFH was previously called "peritumoral edema" — same tissue, same integer,
  renamed to match the adult `dseg.tsv` and BraTS wording. Label 5 is new: most
  peds cases are pre-operative, but the Gradient Health cohort has post-operative
  scans. No existing file uses 5, so adding it changes nothing already drawn.
- Colors come from the shared palette used by the ml-dashboard
  (`ml_dashboard/config/tumor_palette.py`), keyed by tissue, so a region looks the
  same in both tools. They previously disagreed on labels 3 and 4 — cystic was blue
  here and yellow there, edema the reverse — which made correct work look mislabeled.
- The layout supports at most 4 displayed images at once.
- See `peds-glioma-segs.example.json` for a complete working example.

## Reload during development

To reload the scripted module without restarting Slicer:

1. `Edit > Application Settings > Developer`, turn on **Developer mode**.
2. Reopen **Segmentation Browser** and click the module's **Reload** button, or
   run in the Python interactor:

```python
slicer.util.reloadScriptedModule("PediatricGliomaSegmentationBrowser")
```

Editing UI is established from the active config when the module loads. If you
switch to a config with/without an `editing` block, reopen the module.
