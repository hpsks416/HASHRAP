from __future__ import annotations
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from filelock import FileLock
from pypdf import PdfReader
from .runtime import ROOT, prepare, settings, read_json, write_json, cancelled


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for buf in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def ranges(total, size, overlap):
    if total < 1 or size < 1 or not 0 <= overlap < size:
        raise ValueError("Invalid page count / batch size / overlap")
    return [dict(start=a, end=min(a+size, total), parse_start=max(0, a-overlap),
                 parse_end=min(total, a+size+overlap), state="pending", attempts=0)
            for a in range(0, total, size)]


def bookmarks(reader):
    found = []
    def walk(items, parents):
        current = parents
        for item in items:
            if isinstance(item, list):
                walk(item, current)
            else:
                title = str(item.title)
                page = reader.get_destination_page_number(item)
                current = parents + [title]
                if page is not None and page >= 0:
                    found.append({"page": page, "path": current})
    try:
        walk(reader.outline, [])
    except (ValueError, KeyError, AttributeError):
        pass
    return sorted(found, key=lambda b: b["page"])


def import_manual(pdf, chip, revision, title=None, tier=None, batch_pages=None, chip_aliases=None, manufacturer=None):
    data = prepare()
    source = Path(pdf).resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("Provide an existing PDF file")
    cfg = settings()
    tier = tier or cfg["tier"]
    size = batch_pages or cfg["batch_pages"]
    overlap = min(cfg["overlap_pages"], max(0, size - 1))
    sha = fingerprint(source)
    # Include parser and normalization settings: results cannot be silently reused across changes.
    identity = {"sha256": sha, "chip": chip.upper().strip(), "revision": revision,
                "title": title or source.stem, "tier": tier, "batch": size,
                "overlap": overlap, "mineru": importlib.metadata.version("mineru"),
                "normalizer": 1, "config_sha256": fingerprint(ROOT / "mineru.yaml")}
    if chip_aliases:
        identity["chip_aliases"] = sorted(set(a.strip().upper() for a in chip_aliases if a.strip()))
    docid = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    dest = data / "manuals" / docid
    dest.mkdir(parents=True, exist_ok=True)
    with FileLock(str(dest / "import.lock"), timeout=1):
        manifest_file = dest / "manifest.json"
        if manifest_file.exists():
            return docid
        reader = PdfReader(source)
        source_encrypted=reader.is_encrypted
        if reader.is_encrypted:
            # An owner/permissions password can coexist with an empty open password.
            # is_encrypted remains True after successful authentication in pypdf.
            # Only try the standard empty password; never guess a user's password.
            if not reader.decrypt(''):
                raise ValueError('此 PDF 需要打开密码。请先在 PDF 阅读器中使用正确密码打开，并另存为无需密码的副本后导入。')
        page_count = len(reader.pages)
        if page_count < 1:
            raise ValueError("PDF contains no pages")
        shutil.copy2(source, dest / "source.pdf")
        manifest = dict(id=docid, **identity, original_path=str(source), pages=page_count,
                        page_labels=reader.page_labels, bookmarks=bookmarks(reader),
                        shards=ranges(page_count, size, overlap), state="prepared",
                        created=time.time(), quality={})
        manifest['manufacturer']=manufacturer or 'Unspecified'
        manifest['source_encryption']={'encrypted':source_encrypted,
                                       'opened_with_empty_password':bool(source_encrypted)}
        write_json(manifest_file, manifest)
    return docid


def attach_parsed_result(docid, parsed_dir, index=True):
    """Attach a complete, already-produced local MinerU result without running inference."""
    from mineru.parser import ParseResult
    from mineru.render import render, RenderFormat
    dest = manual_dir(docid)
    source = Path(parsed_dir).resolve()
    middle = source / 'middle_json.json'
    if not middle.is_file():
        raise ValueError('Parsed directory must contain middle_json.json')
    with FileLock(str(dest / 'import.lock'),timeout=1):
        m = read_json(dest / 'manifest.json')
        if m['state']=='ready':
            return m
        parsed = ParseResult.from_json(middle.read_text(encoding='utf-8'))
        actual = sorted(p.page_idx for p in parsed.pages)
        if actual != list(range(m['pages'])):
            raise ValueError('Parsed result must cover every original PDF page exactly once')
        out = dest / 'parsed' / 'imported'
        if source != out.resolve():
            shutil.copytree(source,out,dirs_exist_ok=True,ignore=shutil.ignore_patterns('model_output.json'))
        blocks = [{**b,'asset_root':str(out)} for b in render(parsed.middle_json,RenderFormat.CONTENT_LIST)]
        if any(b.get('page_idx') not in range(m['pages']) for b in blocks):
            raise ValueError('Invalid original page index in imported content')
        write_json(out/'blocks.json',blocks)
        write_json(out/'pages.json',actual)
        write_json(dest/'blocks.json',blocks)
        with_blocks = {b['page_idx'] for b in blocks}
        m.update(state='parsed',shards=[dict(start=0,end=m['pages'],parse_start=0,parse_end=m['pages'],
                 state='done',attempts=0,output=str(out))],
                 parsed_provenance={'mode':'existing_mineru_output','directory':str(source),
                                    'middle_sha256':fingerprint(middle)},
                 quality={'parsed_pages':len(actual),'pages_without_blocks':
                          [p+1 for p in actual if p not in with_blocks],
                          'note':'Page coverage verified; numerical and OCR accuracy still require source review.'})
        write_json(dest/'manifest.json',m)
    if index:
        from .retrieval import build_index
        build_index(docid)
    return read_json(dest/'manifest.json')


def manual_dir(docid):
    if not docid or any(c not in "0123456789abcdef" for c in docid) or len(docid) != 20:
        raise ValueError("Invalid document ID")
    dest = prepare() / "manuals" / docid
    if not (dest / "manifest.json").is_file():
        raise ValueError("Document not found")
    return dest


def parse_manual(docid, index=True):
    dest = manual_dir(docid)
    # One parser per GPU; a separate command can still read task status.
    with FileLock(str(prepare() / "parser.lock"), timeout=1):
        manifest_file = dest / "manifest.json"
        m = read_json(manifest_file)
        if m["state"] == "ready" and index:
            return m
        m["state"] = "parsing"
        write_json(manifest_file, m)
        i = 0
        while i < len(m["shards"]):
            if cancelled():
                m['state']='paused'; write_json(manifest_file,m); return m
            shard = m["shards"][i]
            key = f"{shard['start']:06d}-{shard['end']:06d}"
            out = dest / "parsed" / key
            if shard["state"] == "done" and (out / "blocks.json").is_file():
                i += 1
                continue
            shard["state"] = "running"
            shard["attempts"] += 1
            shard["output"] = str(out)
            write_json(manifest_file, m)
            print(f"Parsing {docid}: pages {shard['start']+1}-{shard['end']}/{m['pages']}", file=sys.stderr, flush=True)
            out.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-m", "chiprag.worker", str(dest / "source.pdf"), str(out),
                   m["tier"], f"{shard['parse_start']+1}-{shard['parse_end']}"]
            error = None
            try:
                with (out / "parse.log").open("w", encoding="utf-8") as log:
                    proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                          timeout=settings()["parse_timeout_seconds"])
                if proc.returncode:
                    raise RuntimeError(f"MinerU exited {proc.returncode}; see {out / 'parse.log'}")
                actual = read_json(out / "pages.json")
                expected = list(range(shard["parse_start"], shard["parse_end"]))
                if sorted(actual) != expected:
                    raise RuntimeError("Original page mapping mismatch: refusing to index")
                blocks = read_json(out / "blocks.json")
                if any(b.get("page_idx") not in expected for b in blocks):
                    raise RuntimeError("A content block has an invalid original page index")
            except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                error = str(exc)
            if error:
                shard.update(state="failed", error=error)
                # A bounded retry, then reduce the core range. Never loop forever.
                if shard["attempts"] < 2:
                    write_json(manifest_file, m)
                    continue
                if shard["end"] - shard["start"] > 1:
                    mid = (shard["start"] + shard["end"]) // 2
                    children = []
                    for a, b in ((shard["start"], mid), (mid, shard["end"])):
                        children.append(dict(start=a, end=b, parse_start=max(0,a-m["overlap"]),
                                             parse_end=min(m["pages"],b+m["overlap"]), state="pending", attempts=0))
                    m.setdefault("failed_attempts", []).append(dict(shard))
                    m["shards"][i:i+1] = children
                else:
                    m["state"] = "failed"
                    write_json(manifest_file, m)
                    raise RuntimeError(error)
            else:
                shard.update(state="done", error=None)
                i += 1
            write_json(manifest_file, m)
        # Select one authoritative core shard per page, retaining overlap for the parser only.
        merged = []
        for shard in m["shards"]:
            blocks = read_json(Path(shard["output"]) / "blocks.json")
            for b in blocks:
                if shard["start"] <= b["page_idx"] < shard["end"]:
                    merged.append({**b, "asset_root": shard["output"]})
        write_json(dest / "blocks.json", merged)
        with_text = {b["page_idx"] for b in merged}
        m["quality"] = {"parsed_pages": m["pages"], "pages_without_blocks":
                        [p+1 for p in range(m["pages"]) if p not in with_text],
                        "note": "Empty pages require review; parsing success does not prove OCR accuracy."}
        m["state"] = "parsed"
        write_json(manifest_file, m)
    if index:
        from .retrieval import build_index
        build_index(docid)
    return read_json(manifest_file)
