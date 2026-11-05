from __future__ import annotations
import collections
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
import numpy as np
from filelock import FileLock
from .runtime import prepare, settings, read_json, write_json
from .ingest import manual_dir
from .chunks import make_chunks

def terms(text):
    result = re.findall(r"[a-z0-9_]+", text.lower())
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(word[i:i+2] for i in range(max(1,len(word)-1)))
    return result

def _embedding_backend():
    # fastembed (default) or sentence-transformers. bge-m3 / bge-reranker-v2-m3 are NOT
    # supported by FastEmbed (verified against its supported-models list), so those models
    # require backend="sentence-transformers" (pip install ".[bge]").
    return settings().get("embedding_backend", "fastembed")

def embedding_model(download=False):
    data = prepare(download)
    if _embedding_backend() == "sentence-transformers":
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(settings()["embedding_model"],
                                   cache_folder=str(data / "models" / "retrieval"),
                                   local_files_only=not download)
    from fastembed import TextEmbedding
    return TextEmbedding(settings()["embedding_model"], cache_dir=str(data / "models" / "retrieval"),
                         threads=settings()["threads"], local_files_only=not download)

def reranker_model(download=False):
    data = prepare(download)
    if settings().get("reranker_backend", "fastembed") == "sentence-transformers":
        from sentence_transformers import CrossEncoder
        return CrossEncoder(settings()["reranker_model"],
                            cache_folder=str(data / "models" / "reranker"),
                            local_files_only=not download)
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(settings()["reranker_model"], cache_dir=str(data / "models" / "reranker"),
                            threads=settings()["threads"], local_files_only=not download)

def _tokenizer(encoder):
    # Both backends expose a HuggingFace tokenizers.Tokenizer with .encode().offsets.
    # FastEmbed exposes it as a JSON string; sentence-transformers via .tokenizer.backend_tokenizer.
    if _embedding_backend() == "sentence-transformers":
        tokenizer = encoder.tokenizer.backend_tokenizer
    else:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_str(encoder.model.tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer

def _embed_batch(encoder, texts, batch_size):
    if _embedding_backend() == "sentence-transformers":
        return encoder.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                              show_progress_bar=False, convert_to_numpy=True)
    return encoder.embed(texts, batch_size=batch_size)

def _query_embed(encoder, query):
    if _embedding_backend() == "sentence-transformers":
        return encoder.encode(query, normalize_embeddings=True, convert_to_numpy=True)
    return next(iter(encoder.query_embed(query)))

def embed_windows(text, tokenizer, window_tokens=110):
    # Split by actual multilingual subword offsets, preserving register names and CJK text.
    # 110 + special tokens stays below this model's 128-token limit.
    encoded = tokenizer.encode(text, add_special_tokens=False)
    offsets = encoded.offsets
    for start in range(0, len(offsets), window_tokens-20):
        group = offsets[start:start+window_tokens]
        if group:
            yield text[group[0][0]:group[-1][1]]

def database():
    db = sqlite3.connect(prepare() / "index.sqlite3", timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, doc_id TEXT, chip TEXT, revision TEXT, payload TEXT)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED, tokens)")
    db.execute("CREATE TABLE IF NOT EXISTS vectors (chunk_id TEXT, model TEXT, vector BLOB)")
    db.execute("CREATE INDEX IF NOT EXISTS vector_chunk ON vectors(chunk_id)")
    db.execute("CREATE TABLE IF NOT EXISTS chip_aliases (doc_id TEXT, alias TEXT, PRIMARY KEY(doc_id,alias))")
    return db

def build_index(docid, lexical_only=False):
    dest = manual_dir(docid)
    with FileLock(str(dest / "index.lock"), timeout=1):
        m = read_json(dest / "manifest.json")
        if m["state"] not in ("parsed", "ready", "indexing", "paused"):
            raise ValueError("All pages must parse successfully before indexing")
        m["state"] = "indexing"
        m['index_progress']={'stage':'chunking'}
        write_json(dest / "manifest.json", m)
        blocks = read_json(dest / "blocks.json")
        if settings().get("image_captioning"):
            from .caption import caption_blocks
            blocks = caption_blocks(blocks, settings().get("image_caption_model"),
                                    settings().get("image_caption_batch_size", 4))
        chunks = make_chunks(blocks, {**m, "source_pdf": str(dest / "source.pdf")}, settings()["chunk_characters"])
        if not chunks:
            raise ValueError("No searchable content; inspect parsing output")
        print(f'Indexing {docid}: {len(chunks)} chunks',file=sys.stderr,flush=True)
        embeddings = []
        if not lexical_only:
            encoder = embedding_model()
            tokenizer = _tokenizer(encoder)
            texts, owners = [], []
            for c in chunks:
                heading = " / ".join(c["section"])[-160:]
                for window in embed_windows(heading + "\n" + c["text"], tokenizer):
                    texts.append(window)
                    owners.append(c["id"])
            m['index_progress']={'stage':'embedding','completed':0,'total':len(texts),'chunks':len(chunks)}
            write_json(dest/'manifest.json',m)
            last_progress=time.monotonic()
            from .embedding_cache import vectors
            for record in vectors(dest,texts,owners,encoder):
                embeddings.append(record)
                if time.monotonic()-last_progress>=10 or len(embeddings)==len(texts):
                    m['index_progress']['completed']=len(embeddings)
                    write_json(dest/'manifest.json',m)
                    print(f'Embedding {docid}: {len(embeddings)}/{len(texts)}',file=sys.stderr,flush=True)
                    last_progress=time.monotonic()
        m['index_progress']={'stage':'saving','chunks':len(chunks),'vectors':len(embeddings)}
        write_json(dest/'manifest.json',m)
        with database() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id=?", (docid,))]
            db.executemany("DELETE FROM search WHERE id=?", [(i,) for i in ids])
            db.executemany("DELETE FROM vectors WHERE chunk_id=?", [(i,) for i in ids])
            db.execute("DELETE FROM chunks WHERE doc_id=?", (docid,))
            db.execute('DELETE FROM chip_aliases WHERE doc_id=?',(docid,))
            db.executemany('INSERT INTO chip_aliases VALUES (?,?)',[(docid,a.upper()) for a in set(m.get('chip_aliases',[]))])
            for c in chunks:
                db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (c["id"], docid, m["chip"], m["revision"], json.dumps(c, ensure_ascii=False)))
                db.execute("INSERT INTO search VALUES (?,?)", (c["id"], " ".join(terms(" / ".join(c["section"]) + " " + c["text"]))))
            db.executemany("INSERT INTO vectors VALUES (?,?,?)", embeddings)
        write_json(dest / "chunks.json", chunks)
        m.update(state="ready", chunks=len(chunks), embedding_model=None if lexical_only else settings()["embedding_model"])
        m['index_progress']={'stage':'complete','chunks':len(chunks),'vectors':len(embeddings)}
        write_json(dest / "manifest.json", m)
        from .collections import export_collection
        export_collection(docid)
        (dest/'embedding-checkpoint.sqlite3').unlink(missing_ok=True)
        return {"document": docid, "chunks": len(chunks), "vector_windows": len(embeddings), "state": "ready"}

def search(query, chip=None, revision=None, docid=None, top=8, lexical_only=False, rerank=True, english_query=None):
    if not query.strip() or not 1 <= top <= 50:
        raise ValueError("Provide a query and top between 1 and 50")
    clauses, params = [], []
    for field, value in (("chip", chip.upper() if chip else None), ("revision",revision), ("doc_id",docid)):
        if value:
            if field=='chip':
                clauses.append('(c.chip=? OR EXISTS (SELECT 1 FROM chip_aliases ca WHERE ca.doc_id=c.doc_id AND ca.alias=?))')
                params.extend([value,value])
            else:
                clauses.append("c." + field + "=?")
                params.append(value)
    where = " AND ".join(clauses) or "1=1"
    k = settings()["retrieval_candidates"]
    warnings, rankings = [], []
    with database() as db:
        candidates = {row[0]: json.loads(row[1]) for row in db.execute("SELECT c.id,c.payload FROM chunks c WHERE " + where, params)}
        if not candidates:
            return {"results": [], "warnings": ["No indexed manuals match the selected filters."]}
        query_terms = list(dict.fromkeys(terms(query + " " + (english_query or ""))))
        if query_terms:
            match = " OR ".join('"' + t + '"' for t in query_terms[:80])
            sql = "SELECT c.id FROM search JOIN chunks c ON c.id=search.id WHERE search MATCH ? AND " + where + " ORDER BY bm25(search) LIMIT ?"
            rankings.append([row[0] for row in db.execute(sql, [match,*params,k])])
        similarities = {}
        if not lexical_only:
            rows = db.execute("SELECT v.chunk_id,v.vector FROM vectors v JOIN chunks c ON c.id=v.chunk_id WHERE v.model=? AND " + where,
                              [settings()["embedding_model"], *params])
            encoder = embedding_model()
            qv = np.asarray(_query_embed(encoder, query), dtype=np.float32)
            qv /= max(float(np.linalg.norm(qv)),1e-12)
            # Vectorized matmul over all candidate vectors (still O(V*D), but one numpy call
            # instead of a Python per-row loop). For true ANN at large scale, add an index later
            # (e.g. hnswlib / faiss-cpu) behind a config switch — sqlite-vec is NOT an option:
            # verified that sqlite-vec provides brute-force only, no HNSW.
            fetched = rows.fetchall()
            if fetched:
                cids = [r[0] for r in fetched]
                matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in fetched])
                if matrix.shape[1] != len(qv):
                    raise ValueError("Embedding dimension mismatch; rebuild index")
                for cid, score in zip(cids, matrix @ qv):
                    similarities[cid] = max(similarities.get(cid, -1), float(score))
            rankings.append(sorted(similarities, key=similarities.get, reverse=True)[:k])
            if not similarities:
                warnings.append("No compatible vectors; only lexical retrieval was available.")
        scores = collections.defaultdict(float)
        for ranking in rankings:
            for rank, cid in enumerate(ranking):
                scores[cid] += 1 / (60+rank+1)
        shortlist = sorted(scores, key=scores.get, reverse=True)[:k]
        # English technical reranker: use the caller-supplied English reformulation for Chinese questions.
        if rerank and shortlist and (english_query or not re.search(r"[\u3400-\u9fff]",query)):
            model = reranker_model()
            values = list(model.rerank(english_query or query, [candidates[c]["text"] for c in shortlist]))
            shortlist = [cid for _,cid in sorted(zip(values,shortlist), reverse=True)]
        elif rerank and shortlist:
            warnings.append("Chinese query used multilingual retrieval and rank fusion; supply --english-query for the English cross-encoder.")
        results = []
        for cid in shortlist[:top]:
            result = dict(candidates[cid])
            result["retrieval_score"] = scores[cid]
            result["vector_similarity"] = similarities.get(cid)
            result["citation"] = f"{result['title']} | {result['chip']} | Rev {result['revision']} | PDF p.{result['page']} | {' / '.join(result['section'])}"
            results.append(result)
        distinct = {(r["chip"],r["revision"]) for r in results}
        if len(distinct) > 1:
            warnings.append("Results span multiple chips or revisions; do not combine incompatible specifications.")
        return {"query":query, "results":results, "warnings":warnings,
                "note":"Scores rank candidates; they are not probabilities of correctness. Verify tables and numeric claims against original pages."}

def read_chunk(cid, section=False, offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid pagination")
    with database() as db:
        row = db.execute("SELECT payload FROM chunks WHERE id=?",(cid,)).fetchone()
        if not row:
            raise ValueError("Chunk not found")
        c = json.loads(row[0])
        if not section:
            return c
        all_chunks = [json.loads(r[0]) for r in db.execute("SELECT payload FROM chunks WHERE doc_id=?",(c["doc_id"],))]
        matching = sorted((x for x in all_chunks if x["parent_id"] == c["parent_id"]),key=lambda x:(x["page"],x["block_ordinal"],x["id"]))
        return {"chunks":matching[offset:offset+limit], "total":len(matching),
                "next_offset":offset+limit if offset+limit<len(matching) else None}
