"""Recover an existing local API result without submitting or parsing a document again."""
from __future__ import annotations
import re
import shutil
import zipfile
from pathlib import Path
import httpx
from .runtime import prepare,write_json
from .service import API_URL

def extract_result(archive:Path,target:Path):
    target=target.resolve()
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        members=z.infolist()
        if sum(i.file_size for i in members)>8*1024**3:
            raise ValueError('Archive exceeds recovery size limit')
        for member in members:
            path=(target/member.filename).resolve()
            if not path.is_relative_to(target) or '\\' in member.filename:
                raise ValueError('Unsafe archive path')
            # Preserve large raw model outputs in the ZIP, without duplicating them on disk.
            if member.is_dir() or Path(member.filename).name=='model_output.json':
                continue
            path.parent.mkdir(parents=True,exist_ok=True)
            with z.open(member) as source,path.open('wb') as dest:
                shutil.copyfileobj(source,dest,length=1024*1024)

def recover_job(jobid:str,output:str,source_pdf:str|None=None):
    prepare()
    if not re.fullmatch(r'job_[a-f0-9]+',jobid):
        raise ValueError('Invalid job ID')
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    with httpx.Client(trust_env=False,timeout=httpx.Timeout(300,connect=10)) as client:
        response=client.get(f'{API_URL}/v1/parse/jobs/{jobid}')
        response.raise_for_status()
        job=response.json()
        write_json(out/'job.json',job)
        if job.get('status')!='completed':
            raise ValueError(f"Job is {job.get('status')}; existing task was not resubmitted")
        files=job.get('files',[])
        if len(files)!=1 or files[0].get('status')!='completed':
            raise ValueError('Recovery currently requires one completed file')
        file=files[0]
        archive_info=file.get('output_files',{}).get('zip')
        if not archive_info:
            raise ValueError('Job has no ZIP output')
        def download(fileid,path,expected=None):
            if path.exists() and (expected is None or path.stat().st_size==expected):
                return
            temp=path.with_suffix(path.suffix+'.part')
            with client.stream('GET',f'{API_URL}/v1/files/{fileid}/content') as stream:
                stream.raise_for_status()
                with temp.open('wb') as dest:
                    for chunk in stream.iter_bytes(1024*1024):
                        dest.write(chunk)
            if expected is not None and temp.stat().st_size!=expected:
                raise ValueError('Incomplete download; rerun recovery to retry')
            temp.replace(path)
        archive=out/'MinerU-result.zip'
        download(archive_info['file_id'],archive,archive_info.get('bytes'))
        extract_result(archive,out/'parsed')
    from .runtime import read_json
    pages=len(read_json(out/'parsed'/'middle_json.json').get('pages',[]))
    original=None
    if source_pdf:
        from pypdf import PdfReader
        source=Path(source_pdf).resolve()
        if len(PdfReader(source).pages)!=pages:
            raise ValueError('Source PDF page count does not match recovered result')
        original=out/'source.pdf'
        if source!=original:
            shutil.copy2(source,original)
    return {'job':jobid,'status':'recovered','pages':pages,'archive':str(archive),
            'markdown':str(out/'parsed'/'markdown.md'),'source_pdf':str(original) if original else None,
            'note':'Recovered existing completed output; no parsing task was created.'}
