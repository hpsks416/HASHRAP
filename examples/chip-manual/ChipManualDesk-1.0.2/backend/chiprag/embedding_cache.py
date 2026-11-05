"""Durable vector checkpoints for safe pause/restart during a large import."""
import hashlib
import sqlite3
import numpy as np
from .runtime import settings,cancelled,read_json,write_json

def vectors(dest,texts,owners,encoder):
    digest=hashlib.sha256(settings()['embedding_model'].encode())
    for text,owner in zip(texts,owners):
        digest.update(owner.encode());digest.update(b'\0');digest.update(text.encode());digest.update(b'\0')
    signature=digest.hexdigest()
    db=sqlite3.connect(dest/'embedding-checkpoint.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (signature TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS cache (position INTEGER PRIMARY KEY,owner TEXT,model TEXT,vector BLOB)')
    previous=db.execute('SELECT signature FROM metadata LIMIT 1').fetchone()
    if not previous or previous[0]!=signature:
        db.execute('DELETE FROM cache');db.execute('DELETE FROM metadata');db.execute('INSERT INTO metadata VALUES (?)',(signature,));db.commit()
    def check_cancel():
        if cancelled():
            db.commit()
            manifest=read_json(dest/'manifest.json');manifest['state']='paused'
            manifest.setdefault('index_progress',{})['stage']='paused'
            write_json(dest/'manifest.json',manifest)
            raise RuntimeError('Task paused safely; use resume to continue cached vectors')
    position=0
    try:
        for pos,owner,model,raw in db.execute('SELECT position,owner,model,vector FROM cache ORDER BY position'):
            check_cancel()
            if pos!=position or owner!=owners[pos]: raise ValueError('Invalid embedding checkpoint')
            yield owner,model,raw; position+=1
        backend=settings().get('embedding_backend','fastembed')
        batch=texts[position:]
        if backend=='sentence-transformers':
            pairs=zip(owners[position:],encoder.encode(batch,batch_size=settings()['embedding_batch_size'],
                                                       normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True))
        else:
            pairs=zip(owners[position:],encoder.embed(batch,batch_size=settings()['embedding_batch_size']))
        for owner,vector in pairs:
            check_cancel()
            v=np.asarray(vector,dtype=np.float32);v/=max(float(np.linalg.norm(v)),1e-12)
            record=(owner,settings()['embedding_model'],v.tobytes())
            db.execute('INSERT INTO cache VALUES (?,?,?,?)',(position,*record));position+=1
            if position%128==0: db.commit()
            yield record
        db.commit()
    finally:
        db.close()
