# Changelog

## 2.1.0 (2026-11-17) - Light-Guided Pipelines & Reproduction Quality

### New
- **Light-guided pipelines (A / L / M1 / B)** selectable from the reprojection panel:
  - `A` mature mixed plate (default, unified lighting);
  - `L` light-and-composition plate (fast, single pass);
  - `M1` dual-underpainting plate (2×2 background slices + clean character implant);
  - `B` dual-paint prototype (empty plate + independent figure).
  New `tools/light_draft.py` procedurally paints a light/value underlayer (window light shaft,
  figure receiving light, directional cast shadow) for the L/M1 stages.
- **Automatic hand refinement** (params → `自动手部精修`): SDPose detects the hands, then a local
  crop is enlarged and repainted; enabled by default and can be switched off per run.
- **Prompt quality baseline**: scene prompts get `masterpiece, best quality, highres` and a
  `detailed background / atmospheric depth / unified environmental lighting` suffix when a
  `@SET_*` block is present; non-closeup shots relax the rigid symmetric face lock while keeping
  the red-right / grey-left heterochromia.
- **Parameter data modal** in the params card: shows the local Anima LoRA recommendation table and
  the environment/character ratio reference.

### Fixes
- **Reprojection masks**: widen narrow body crops (`>=0.62`), union BiRefNet + SDPose masks instead
  of picking one, and cap multi-LoRA stacking on the plate stage.
- **Prompt conflicts**: strip studio white-background words when a real scene is present, remove
  numeric people-count prefixes in scene shots, block half-body/closeup + seated/lying poses,
  and prevent multi-ID leakage.
- **Workflow wizard**: dual mode (direct / reprojection), Anima-only LoRA filter with separate
  environment and character picks, conditional gender re-render, ratio and character-card integration.
- **Identity safety**: never inject owned `@ID_*`/`@BODY_*` blocks or a leaked role LoRA when no
  character card is selected.
- **Anima reprojection defaults**: ratio `0.34`, environment weight `0.70`, character weight `0.85`.

### Docs
- README: document the pipeline selector, automatic hand refinement, and new `light_draft.py`.

## 2.0.0 (2026-11-16) - Open Anima Workstation Release

### Architecture & Features
- Modular FastAPI backend (`station/server.py`, `svc_state.py`, `svc_recipes.py`, `svc_jobs.py`, `svc_mem.py`, `routes_*.py`).
- **Anima (`anima-base` / Qwen-Image)** unified inference workflows (`anima_t2i.json`, `anima_i2i.json`, `anima_inpaint.json`, `anima_zimage_relight.json`) using `UNETLoader + CLIPLoader + VAELoader`.
- 660+ modular `@宏` prompt blocks with gender split (`f`/`m`), outfit garments (`casual_knit`, `slip`, `school`, `gala`, etc.), and runtime character cards (`cards.json`, imported cleanly without bundled private characters).
- Three-tab Reprojection (`coop_reproject`) + silhouette/matting (`cutout`, `standee_template`, `layers`) + automated prompt rule audit (`ir.py`, `prompt_fix.py`, `light_guide.py`).
- SQLite WAL storage (`core/store.py`) + dynamic ComfyUI path resolution (`tools/comfy_paths.py`).
- Cleaned repository: removed all private LoRA filenames/recipes, painting/ONNX weights, and private character cards.

## 1.0.0 - Initial Public Scaffolding
- Installer scripts (`install/install.ps1`, `install/bind_pipeline.ps1`), ComfyUI node checks, and privacy pre-publish scanner (`tools/check_clean.py`).
