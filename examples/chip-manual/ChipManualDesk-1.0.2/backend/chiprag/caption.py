"""Optional local VLM captioning for chip-manual figures (config-gated, default OFF).

Closes the "image blind spot" (技术原理详解 §7.2): generate a short text caption for
image/chart blocks at ingest time so figures become text-searchable, instead of the
"[image on PDF page N; inspect original page]" placeholder.

Verified wheel (铁律一): Qwen2-VL is superseded by Qwen2.5-VL / Qwen3-VL, and Ollama's
qwen2-vl entry is gone. Use Qwen/Qwen2.5-VL-2B-Instruct (Apache-2.0) via transformers;
2B is CPU-feasible, 7B needs ~4-14 GB.

WARNING — static-verified only: this module has NOT been run end-to-end in this repo
(no models / no indexed library here). The Qwen2.5-VL model class and the generic
image-to-text pipeline are version-sensitive; verify against your installed transformers
before relying on captions. Captioning is best-effort and never blocks indexing.
"""
from __future__ import annotations
from pathlib import Path


def caption_blocks(blocks, model_name, batch_size=4):
    """Return blocks with a text caption appended to image/chart blocks that have an image path."""
    targets = [b for b in blocks if b.get("type") in ("image", "chart") and b.get("img_path")]
    if not targets:
        return blocks
    from transformers import pipeline
    import torch
    device = 0 if torch.cuda.is_available() else -1
    captioner = pipeline("image-to-text", model=model_name, device=device, trust_remote_code=True)
    for b in targets:
        root = Path(b.get("asset_root") or ".")
        img = Path(b.get("img_path"))
        path = img if img.is_absolute() else root / img
        if not path.is_file():
            continue
        try:
            out = captioner(str(path), max_new_tokens=64)
            text = out[0].get("generated_text") if isinstance(out, list) else str(out)
            b["text"] = (b.get("text") or "") + f"\n[figure caption: {text}]"
        except Exception as exc:  # best-effort: never block indexing on caption failure
            b["text"] = (b.get("text") or "") + f"\n[figure caption failed: {exc}]"
    return blocks
