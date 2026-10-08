# BIDS Segmentation Browser

`BidsSegmentationBrowser.py` is a 3D Slicer module for browsing BIDS-formatted
MRI cases and creating segmentations with **nnInteractive**.

## Features

- Pick an **input folder** (BIDS images) and an **output folder** (saved segs)
  before case browsing is enabled
- Discover `sub-*/ses-*` cases that contain one or more NIfTI files
- On case open:
  - Load available modalities (`T1post`, `T1pre`, `FLAIR`, `T2`, …)
  - Compute `T1sub = T1post - T1pre` when both exist and share the same shape
    (otherwise warn and skip)
  - Show **one** volume in a single axial Red view, interpolation **off**
    (preference: T1post → T1pre → any)
  - Create a new segmentation, or resume one already saved in the output folder
  - Bind that segmentation + displayed volume as the nnInteractive source
- Embed the nnInteractive UI (including its Segment Editor tools) in the module
  panel
- Auto-save the segmentation to the output folder (BIDS layout) when switching
  cases; also **Save segmentation** manually

## Install

1. Install the [nnInteractive](https://github.com/MIC-DKFZ/nnInteractive) /
   `SlicerNNInteractive` extension in Slicer (Extension Manager), and complete
   its first-run setup.
2. `Edit > Application Settings > Modules`, add this repo path under
   **Additional module paths**, restart Slicer.
3. Open **BIDS Segmentation Browser**.

## nnInteractive server (Docker)

This browser embeds the nnInteractive UI and expects a running inference
backend. Remote mode against a local GPU container is the usual setup.

Start the official server (NVIDIA Container Toolkit required):

```bash
docker run --gpus all --runtime=nvidia -p 1527:1527 \
  ghcr.io/mic-dkfz/nninteractive-server:latest
```

The server listens on `http://localhost:1527`. With no
`NN_INTERACTIVE_API_KEY` set, the server is unauthenticated — leave the API key
field empty in Slicer. To require a key instead:

```bash
docker run --gpus all --runtime=nvidia -p 1527:1527 \
  -e NN_INTERACTIVE_API_KEY="$(openssl rand -hex 32)" \
  ghcr.io/mic-dkfz/nninteractive-server:latest
```

### Connect from Slicer

1. Open **BIDS Segmentation Browser** (or the standalone **nnInteractive**
   module) and wait for a case/volume to load.
2. In the embedded nnInteractive **Configuration** tab:
   - Mode: **Remote**
   - Server URL: `http://localhost:1527`
   - API key: leave blank (unless you started the container with a key)
   - Optionally click **Test connection**
3. Switch to the **nnInteractive Prompts** tab and click **Initialize**.
   This connects to the container and uploads the current image; prompt tools
   stay disabled until it finishes. The button then shows **Uninitialize**.

Re-click **Initialize** after the container restarts, or after changing the
URL / key / mode.

## Usage

1. Set **Input folder** to a BIDS tree of images, e.g.
   `.../preprocessed-niftis` with `sub-*/ses-*/anat/*.nii.gz`.
2. Set **Output folder** to where segmentations should be written.
3. Start the nnInteractive container and Initialize (see above).
4. Pick a case (or Previous / Next) and segment with nnInteractive.
5. Switch cases — the current segmentation is saved automatically as:

```text
{output}/{sub}/{ses}/anat/{sub}_{ses}_space-orig_dseg.nii.gz
```

## Semantic labels with nnInteractive (important)

nnInteractive edits **one selected segment** at a time. In Slicer, several segments
can share a single binary labelmap layer (one integer per voxel). If they share a
layer, prompting a new ROI **overwrites** the other segment — this looks like
nnInteractive “ate” your work. Your colleague is right: each ROI/class needs its
**own labelmap layer** (not a separate NIfTI file on disk).

This plugin creates `Segment_1` and `Segment_2` and **isolates layers automatically
on case load**, and again whenever a segment is added (Add / Next segment). The
**Isolate segment layers** button is only a manual fallback if something still
looks shared.

Suggested workflow (label 2 = enhancing, label 1 = non-enhancing):

1. Select **`Segment_2`**, Initialize, prompt enhancing tumor (lasso/scribble).
2. Select **`Segment_1`** (do not leave Segment_2 selected).
3. Prompt non-enhancing components.
4. If they overlap and you want NET to win: Logical operators → subtract
   `Segment_1` from `Segment_2` (or the reverse, depending on priority).
5. Save. Export writes integers from the `Segment_N` names.

Never prompt while the wrong segment is selected. Prefer a temp instance segment
only if needed, then OR it into `Segment_1` / `Segment_2`.

## Supported image names

Both short CTX-style and canonical BIDS suffixes are recognized:

| Modality | Accepted suffixes |
|----------|-------------------|
| T1post   | `_T1post`, `_ce-gadolinium_T1w` |
| T1pre    | `_T1pre`, `_T1w` (not contrast-enhanced) |
| FLAIR    | `_FLAIR` |
| T2       | `_T2`, `_T2w` |

## Reload during development

1. `Edit > Application Settings > Developer`, enable **Developer mode**.
2. Reopen the module and click **Reload**, or in the Python interactor:

```python
slicer.util.reloadScriptedModule("BidsSegmentationBrowser")
```

## Tests

Pure-Python discovery helpers (no Slicer required):

```bash
python -m unittest discover -s tests -v
```
