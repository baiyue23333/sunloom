# Changelog

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
