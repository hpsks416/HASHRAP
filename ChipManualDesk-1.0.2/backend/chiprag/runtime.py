from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def root() -> Path:
    if os.environ.get('CHIPRAG_DATA'):
        return Path(os.environ['CHIPRAG_DATA']).resolve()
    installed=ROOT/'installation.json'
    if installed.is_file():
        return Path(read_json(installed)['library_root']).resolve()
    return (ROOT/'data').resolve()

def settings() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

def prepare(download: bool = False) -> Path:
    data = root()
    data.mkdir(parents=True, exist_ok=True)
    for name in ("manuals", "models", "mineru", "logs", "previews", "cache", "tmp"):
        (data / name).mkdir(exist_ok=True)
    os.environ["TEMP"] = str(data / "tmp")
    os.environ["TMP"] = str(data / "tmp")
    tempfile.tempdir = str(data / "tmp")
    os.environ["MINERU_HOME"] = str(data / "mineru")
    if os.environ.get('CHIPRAG_DATA') or (ROOT/'installation.json').exists():
        model_config=data/'mineru-runtime.yaml'
        text='model:\n  source: local\n  base_dir: '+json.dumps((data/'models'/'mineru').as_posix())+'\n  small_backend: onnx\n  vlm:\n    engine: llama-cpp\n    max_concurrency: 2\nllm_aided:\n  features:\n    title_leveling: false\n    cross_page_table_cell_merge: '+('true' if settings().get('cross_page_table_cell_merge', False) else 'false')+'\n'
        if not model_config.exists() or model_config.read_text(encoding='utf-8')!=text:
            model_config.write_text(text,encoding='utf-8')
        os.environ['MINERU_CONFIG']=str(model_config)
    else:
        os.environ["MINERU_CONFIG"] = str(ROOT / "mineru.yaml")
    os.environ["MINERU_MODEL_SOURCE"] = "auto" if download else "local"
    os.environ["MINERU_MODEL_SMALL_BACKEND"] = "onnx"
    os.environ["MINERU_MODEL_VLM_ENGINE"] = "llama-cpp"
    os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = "8"
    os.environ["MINERU_PDF_RENDER_THREADS"] = "2"
    os.environ["MINERU_INTRA_OP_NUM_THREADS"] = "4"
    os.environ["MINERU_INTER_OP_NUM_THREADS"] = "1"
    os.environ["HF_HOME"] = str(data / "cache" / "huggingface")
    os.environ["MODELSCOPE_CACHE"] = str(data / "cache" / "modelscope")
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["PYTHONUTF8"] = "1"
    for key in ("MINERU_API_URL", "MINERU_API_KEY", "MINERU_MODEL_VLM_SERVER_URL", "MINERU_MODEL_VLM_API_KEY", "MINERU_LLM_API_KEY"):
        os.environ.pop(key, None)
    return data

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def cancelled():
    value=os.environ.get('CHIPRAG_CANCEL_FILE')
    return bool(value and Path(value).is_file())
