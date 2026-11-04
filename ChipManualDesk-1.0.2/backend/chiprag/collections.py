"""Independent per-manual index snapshots grouped by manufacturer and chip."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from .runtime import root,read_json,write_json

def safe_name(value,limit=65):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(value)).strip(' .')[:limit]
    if not value or value.upper() in {'CON','PRN','AUX','NUL','COM1','LPT1'}:
        value='manual_'+value
    return value

def export_collection(docid):
    base=root(); manual=base/'manuals'/docid; m=read_json(manual/'manifest.json')
    dest=base/'collections'/safe_name(m.get('manufacturer','Unspecified'))/safe_name(m['chip'])/(safe_name(m['title'],55)+'--'+docid[:8])
    dest.mkdir(parents=True,exist_ok=True)
    target=dest/'index.sqlite3'; temp=dest/'index.sqlite3.new'
    if temp.exists(): temp.unlink()
    with sqlite3.connect(temp) as out,sqlite3.connect(base/'index.sqlite3') as source:
        out.execute('CREATE TABLE chunks (id TEXT PRIMARY KEY,doc_id TEXT,chip TEXT,revision TEXT,payload TEXT)')
        out.execute('CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,tokens)')
        out.execute('CREATE TABLE vectors (chunk_id TEXT,model TEXT,vector BLOB)')
        out.execute('CREATE INDEX vector_chunk ON vectors(chunk_id)')
        out.execute('CREATE TABLE chip_aliases (doc_id TEXT,alias TEXT,PRIMARY KEY(doc_id,alias))')
        out.executemany('INSERT INTO chunks VALUES (?,?,?,?,?)',source.execute('SELECT * FROM chunks WHERE doc_id=?',(docid,)))
        out.executemany('INSERT INTO search VALUES (?,?)',source.execute('SELECT s.id,s.tokens FROM search s JOIN chunks c ON c.id=s.id WHERE c.doc_id=?',(docid,)))
        out.executemany('INSERT INTO vectors VALUES (?,?,?)',source.execute('SELECT v.* FROM vectors v JOIN chunks c ON c.id=v.chunk_id WHERE c.doc_id=?',(docid,)))
        if source.execute("SELECT 1 FROM sqlite_master WHERE name='chip_aliases'").fetchone():
            out.executemany('INSERT INTO chip_aliases VALUES (?,?)',source.execute('SELECT * FROM chip_aliases WHERE doc_id=?',(docid,)))
    # SQLite context managers commit but do not close their connections.
    out.close(); source.close()
    temp.replace(target)
    record={k:m.get(k) for k in ('id','title','chip','chip_aliases','revision','manufacturer','pages','chunks','embedding_model')}
    record.update(index=str(target),source_pdf=str(manual/'source.pdf'),manifest=str(manual/'manifest.json'))
    write_json(dest/'manual.json',record)
    m['collection_path']=str(dest); write_json(manual/'manifest.json',m)
    return record
