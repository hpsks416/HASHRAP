from __future__ import annotations
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from .runtime import prepare,root,read_json,write_json

def copy_missing(source,target):
    source=Path(source); target=Path(target)
    if not source.exists(): return
    for path in source.rglob('*'):
        if path.is_file() and not path.name.endswith('.lock'):
            dest=target/path.relative_to(source)
            if not dest.exists():
                dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,dest)

def migrate_library(source):
    old=Path(source).resolve(); new=prepare()
    if old==new: return {'state':'same_location'}
    copy_missing(old/'models',new/'models')
    target=new/'index.sqlite3'
    if target.exists():
        return {'state':'preserved_existing_library','path':str(new)}
    if not (old/'index.sqlite3').exists():
        return {'state':'models_only','path':str(new)}
    copy_missing(old/'manuals',new/'manuals')
    # SQLite backup creates a consistent snapshot even when the source uses WAL.
    source_db=sqlite3.connect(old/'index.sqlite3'); target_db=sqlite3.connect(target)
    source_db.backup(target_db); source_db.close()
    old_prefix=str(old); new_prefix=str(new)
    def rewrite(value):
        if isinstance(value,str) and value.lower().startswith(old_prefix.lower()):
            return new_prefix+value[len(old_prefix):]
        if isinstance(value,list): return [rewrite(v) for v in value]
        if isinstance(value,dict): return {k:rewrite(v) for k,v in value.items()}
        return value
    with target_db:
        rows=target_db.execute('SELECT id,payload FROM chunks').fetchall()
        target_db.executemany('UPDATE chunks SET payload=? WHERE id=?',[(json.dumps(rewrite(json.loads(payload)),ensure_ascii=False),cid) for cid,payload in rows])
    target_db.close()
    for manifest in (new/'manuals').glob('*/manifest.json'):
        m=rewrite(read_json(manifest))
        if not m.get('manufacturer') or m['manufacturer']=='Unspecified':
            from pypdf import PdfReader
            author=str((PdfReader(manifest.parent/'source.pdf').metadata or {}).get('/Author',''))
            if 'STMICROELECTRONICS' in author.upper(): m['manufacturer']='STMicroelectronics'
        write_json(manifest,m)
        for name in ('blocks.json','chunks.json'):
            path=manifest.parent/name
            if path.exists(): write_json(path,rewrite(read_json(path)))
    return {'state':'copied','path':str(new),'source_preserved':True}

def organize():
    from .collections import export_collection
    results=[]
    for manifest in (prepare()/'manuals').glob('*/manifest.json'):
        m=read_json(manifest)
        if m.get('state')=='ready': results.append(export_collection(m['id']))
    write_json(root()/'collections'/'catalog.json',results)
    return results

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--app-root',required=True)
    p.add_argument('--library',required=True)
    p.add_argument('--seed-library')
    p.add_argument('--configure',action='store_true')
    args=p.parse_args()
    import os
    app=Path(args.app_root).resolve(); library=Path(args.library).resolve()
    os.environ['CHIPRAG_DATA']=str(library)
    config={'version':1,'app_root':str(app),'library_root':str(library),
            'python':str(app/'runtime'/'venv'/'Scripts'/'python.exe'),'backend':str(app/'backend')}
    write_json(app/'desktop-settings.json',config)
    write_json(app/'backend'/'installation.json',config)
    result={'configuration':config}
    if args.seed_library: result['migration']=migrate_library(args.seed_library)
    result['collections']=organize()
    if args.configure:
        from .integration import install_skills
        result['ai']=install_skills(app,library)
    write_json(library/'installation-report.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
