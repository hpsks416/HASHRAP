#!/usr/bin/env python3
"""框架知识库构建：把 DSH 框架内容（AGENTS.md 铁律 / persona / meta-drift-log / 全部 SKILL.md / HANDOFF）
分块 + FTS5 关键词索引 + 向量化，产出可检索的 framework_kb.sqlite3。

用法:
    .venv\\Scripts\\python.exe build_kb.py                  # 全量（FTS5 + 向量）
    .venv\\Scripts\\python.exe build_kb.py --lexical-only    # 只建 FTS5（无向量，无需模型）
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

DB = Path(__file__).resolve().parent / "framework_kb.sqlite3"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_CHARS = 900
OVERLAP = 100


# ---- 词项：英文/数字按 token，连续中文按相邻双字（复用 chiprag terms 思路）----
def terms(text: str):
    result = re.findall(r"[a-z0-9_]+", text.lower())
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
    return result


# ---- 分块 ----
def split_text(text: str, limit: int):
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind("。", 0, limit), text.rfind(". ", 0, limit))
        if cut < limit // 2:
            cut = limit
        yield text[:cut].strip()
        text = text[max(1, cut - OVERLAP):].strip()
    if text.strip():
        yield text.strip()


def chunk_markdown(text: str):
    """按标题分段，段内按长度再切；返回 [(section, piece), ...]"""
    sections, heading, lines = [], "", []
    for line in text.splitlines():
        if re.match(r"^#{1,3}\s", line):
            if lines:
                sections.append((heading, "\n".join(lines)))
            heading = line.lstrip("#").strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        sections.append((heading, "\n".join(lines)))
    out = []
    for heading, body in sections:
        for piece in split_text(body, CHUNK_CHARS):
            out.append((heading, piece))
    return out


# ---- 框架内容源 ----
def collect_sources():
    home = Path.home()
    sources = []
    core = [
        (home / ".dsh" / "AGENTS.md", "铁律"),
        (home / ".dsh" / "persona.md", "画像"),
        (home / ".dsh" / "meta-drift-log.md", "偏离日志"),
        (Path("G:/CodexDS/DSH/INTRO/HANDOFF.md"), "交接"),
    ]
    for p, tag in core:
        if p.is_file():
            sources.append((p, tag))
    seen = set()

    def add_skills(root: Path):
        for sk in sorted((root / "skills").glob("*/SKILL.md")):
            name = sk.parent.name
            if name in seen:
                continue
            seen.add(name)
            sources.append((sk, f"skill:{name}"))

    add_skills(home / ".dsh")
    add_skills(home / ".agents")
    add_skills(home / ".codex")
    return sources


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def build(lexical_only: bool):
    sources = collect_sources()
    print(f"收集到 {len(sources)} 个源文档", file=sys.stderr, flush=True)

    DB.unlink(missing_ok=True)
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("CREATE TABLE chunks (id TEXT PRIMARY KEY, source TEXT, tag TEXT, section TEXT, text TEXT)")
    db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, tokens)")
    db.execute("CREATE TABLE vectors (chunk_id TEXT, model TEXT, vector BLOB)")

    encoder = None
    if not lexical_only:
        from fastembed import TextEmbedding
        encoder = TextEmbedding(EMBED_MODEL, cache_dir=str(Path(__file__).resolve().parent / "models"),
                                threads=4)
        print(f"嵌入模型 {EMBED_MODEL} 已加载", file=sys.stderr, flush=True)

    chunks, embeddings = [], []
    for src, tag in sources:
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"跳过 {src}: {exc}", file=sys.stderr)
            continue
        rel = str(src)
        for section, piece in chunk_markdown(text):
            if len(piece.strip()) < 16:
                continue
            cid = hashlib.sha256(f"{rel}|{section}|{piece[:64]}".encode()).hexdigest()[:20]
            chunks.append((cid, rel, tag, section, piece))

    print(f"分块 {len(chunks)} 条", file=sys.stderr, flush=True)

    for cid, rel, tag, section, piece in chunks:
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (cid, rel, tag, section, piece))
        db.execute("INSERT INTO search VALUES (?,?)", (cid, " ".join(terms(section + " " + piece))))

    if encoder is not None and chunks:
        texts = [c[4] for c in chunks]
        batch = 16
        for i in range(0, len(texts), batch):
            for vec in encoder.embed(texts[i:i + batch], batch_size=batch):
                embeddings.append(normalize(vec).tobytes())
            if (i // batch) % 10 == 0:
                print(f"向量化 {min(i + batch, len(texts))}/{len(texts)}", file=sys.stderr, flush=True)
        db.executemany("INSERT INTO vectors VALUES (?,?,?)",
                       [(c[0], EMBED_MODEL, e) for c, e in zip(chunks, embeddings)])
    db.commit()

    n_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_vec = db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
    db.close()
    print(f"完成: {n_chunks} chunks, {n_vec} vectors -> {DB}", file=sys.stderr)
    return {"chunks": n_chunks, "vectors": n_vec, "sources": len(sources), "lexical_only": lexical_only}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lexical-only", action="store_true")
    args = ap.parse_args()
    print(json.dumps(build(args.lexical_only), ensure_ascii=False))
