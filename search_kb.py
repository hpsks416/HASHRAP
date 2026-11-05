#!/usr/bin/env python3
"""框架知识库检索：FTS5 关键词 + 向量余弦 + RRF 融合 + 跨编码器精排。

用法:
    search_kb.py "查询内容" [--top 8] [--lexical-only] [--no-rerank]
输出: JSON，每项 {source, tag, section, text, score, rerank_score, keyword_hit, vector_hit}
"""
from __future__ import annotations
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

DB = Path(__file__).resolve().parent / "framework_kb.sqlite3"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANK_MODEL = "BAAI/bge-reranker-base"
CANDIDATES = 30


def terms(text: str):
    result = re.findall(r"[a-z0-9_]+", text.lower())
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
    return result


def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(RERANK_MODEL, cache_dir=str(Path(__file__).resolve().parent / "models"),
                            threads=4)


def search(query: str, top: int = 8, lexical_only: bool = False, rerank: bool = True):
    if not DB.is_file():
        return {"error": "知识库未构建，先跑 build_kb.py"}
    q_terms = list(dict.fromkeys(terms(query)))
    db = sqlite3.connect(DB)

    rankings = []
    if q_terms:
        match = " OR ".join('"' + t + '"' for t in q_terms[:80])
        rows = db.execute("SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT ?",
                          (match, CANDIDATES))
        rankings.append([r[0] for r in rows])

    if not lexical_only:
        from fastembed import TextEmbedding
        encoder = TextEmbedding(EMBED_MODEL, cache_dir=str(Path(__file__).resolve().parent / "models"),
                                threads=4)
        qv = np.asarray(next(iter(encoder.query_embed(query))), dtype=np.float32)
        qv /= max(float(np.linalg.norm(qv)), 1e-12)
        rows = db.execute("SELECT chunk_id, vector FROM vectors").fetchall()
        sims = []
        for cid, raw in rows:
            v = np.frombuffer(raw, dtype=np.float32)
            if len(v) == len(qv):
                sims.append((float(v @ qv), cid))
        sims.sort(reverse=True)
        rankings.append([cid for _, cid in sims[:CANDIDATES]])

    scores = collections.defaultdict(float)
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] += 1 / (60 + rank + 1)

    candidates = sorted(scores, key=scores.get, reverse=True)[:CANDIDATES]

    # 跨编码器精排：按 (query, text) 相关性重排候选，取 top
    rerank_scores = {}
    if rerank and candidates:
        texts = []
        for cid in candidates:
            row = db.execute("SELECT text FROM chunks WHERE id=?", (cid,)).fetchone()
            if row:
                texts.append((cid, row[0]))
        if texts:
            model = _reranker()
            vals = list(model.rerank(query, [t for _, t in texts]))
            rerank_scores = dict((cid, float(v)) for (cid, _), v in zip(texts, vals))
            candidates = [cid for cid, _ in sorted(rerank_scores.items(), key=lambda kv: kv[1], reverse=True)]

    shortlist = candidates[:top]
    results = []
    for cid in shortlist:
        row = db.execute("SELECT source, tag, section, text FROM chunks WHERE id=?", (cid,)).fetchone()
        if not row:
            continue
        source, tag, section, text = row
        results.append({
            "source": source, "tag": tag, "section": section, "text": text[:600],
            "score": round(scores[cid], 4),
            "rerank_score": round(rerank_scores.get(cid, 0.0), 4) if rerank_scores else None,
            "keyword_hit": cid in (rankings[0] if rankings else []),
            "vector_hit": cid in (rankings[1] if len(rankings) > 1 and not lexical_only else []),
        })
    db.close()
    return {"query": query, "results": results}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--lexical-only", action="store_true")
    ap.add_argument("--no-rerank", action="store_true")
    args = ap.parse_args()
    print(json.dumps(search(args.query, args.top, args.lexical_only, not args.no_rerank),
                     ensure_ascii=False, indent=2))
