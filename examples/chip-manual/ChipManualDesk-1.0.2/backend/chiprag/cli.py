from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from .runtime import ROOT, prepare, settings, read_json

def kit(*args):
    return subprocess.call([str(Path(sys.executable).with_name("mineru-kit.exe")), *args])

def status(docid=None):
    from .ingest import manual_dir
    paths = [manual_dir(docid) / "manifest.json"] if docid else sorted((prepare()/"manuals").glob("*/manifest.json"))
    results = []
    for path in paths:
        m = read_json(path)
        results.append({k:m.get(k) for k in ("id","title","manufacturer","chip","chip_aliases","revision","tier","state","pages","chunks","quality","index_progress","collection_path")} | {
            "completed_pages":sum(s["end"]-s["start"] for s in m["shards"] if s["state"] == "done"),
            "failed_shards":[s for s in m["shards"] if s["state"] == "failed"]})
    return results

def render_page(docid, page, bbox=None):
    from .ingest import manual_dir
    import pypdfium2 as pdfium
    dest = manual_dir(docid)
    with pdfium.PdfDocument(str(dest / "source.pdf")) as pdf:
        if not 1 <= page <= len(pdf):
            raise ValueError("Page outside document")
        p = pdf[page-1]
        bitmap = p.render(scale=1.8)
        image = bitmap.to_pil().copy()
        bitmap.close()
        p.close()
        if bbox:
            if len(bbox) != 4 or not (0 <= bbox[0] < bbox[2] <= 1000 and 0 <= bbox[1] < bbox[3] <= 1000):
                raise ValueError("bbox must use normalized 0-1000 coordinates")
            w,h = image.size
            image = image.crop((bbox[0]*w/1000,bbox[1]*h/1000,bbox[2]*w/1000,bbox[3]*h/1000))
        path = prepare()/"previews"/f"{docid}-page-{page}{'-crop' if bbox else ''}.png"
        image.save(path)
    return {"image":str(path),"page":page,"source_pdf":str(dest/"source.pdf")}

def doctor():
    packages = {}
    for name in ("mineru","fastembed","onnxruntime","pypdf","numpy","mineru-llama-cpp"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "MISSING"
    import onnxruntime as ort
    return {"python":sys.version.split()[0],"data":str(prepare()),"packages":packages,
            "onnxruntime_loaded":{"version":ort.__version__,"providers":ort.get_available_providers()},
            "parser":"local SDK; ONNX + llama.cpp", "tier":settings()["tier"],
            "remote_parsing":False, "model_verification_command":"run.ps1 models-verify",
            "manuals":status()}

def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local MinerU chip-manual knowledge base")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("models-download")
    sub.add_parser("models-verify")
    sub.add_parser("webui")
    sub.add_parser("stop-ui")
    sub.add_parser('detect-ai')
    ai=sub.add_parser('configure-ai')
    ai.add_argument('--targets',default='auto')
    ai.add_argument('--app-root',default=str(ROOT.parent))
    sub.add_parser('organize')
    recover = sub.add_parser("recover-job")
    recover.add_argument("jobid")
    recover.add_argument("--output",required=True)
    recover.add_argument("--source",help="Optional original PDF for page-count verification and preservation")
    imp = sub.add_parser("import")
    imp.add_argument("pdf")
    imp.add_argument("--chip", required=True)
    imp.add_argument("--revision", required=True)
    imp.add_argument("--title")
    imp.add_argument('--manufacturer')
    imp.add_argument("--tier", choices=["standard","advanced","basic","flash"])
    imp.add_argument("--batch-pages", type=int)
    imp.add_argument("--chip-alias",action="append",default=[])
    imp.add_argument("--parsed-dir",help="Attach a matching complete MinerU result without re-parsing")
    imp.add_argument("--prepare-only", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("docid")
    idx = sub.add_parser("index")
    idx.add_argument("docid")
    idx.add_argument("--lexical-only", action="store_true")
    stat = sub.add_parser("status")
    stat.add_argument("docid", nargs="?")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--chip")
    search.add_argument("--revision")
    search.add_argument("--docid")
    search.add_argument("--top",type=int,default=8)
    search.add_argument("--lexical-only",action="store_true")
    search.add_argument("--no-rerank",action="store_true")
    search.add_argument("--english-query")
    read = sub.add_parser("read")
    read.add_argument("chunk_id")
    read.add_argument("--section",action="store_true")
    read.add_argument("--offset",type=int,default=0)
    read.add_argument("--limit",type=int,default=20)
    page = sub.add_parser("page")
    page.add_argument("docid")
    page.add_argument("page",type=int)
    page.add_argument("--bbox",type=float,nargs=4)
    args = parser.parse_args()
    prepare(args.command == "models-download")
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "models-download":
            code = kit("models","download","--tier","standard","--source","modelscope","--small-backend","onnx","--vlm-engine","llama-cpp")
            if code:
                return code
            from .retrieval import embedding_model,reranker_model
            e = embedding_model(True)
            next(iter(e.embed(["ADC clock"])))
            r = reranker_model(True)
            list(r.rerank("ADC",["ADC converter"]))
            result = {"models":"downloaded"}
        elif args.command == "models-verify":
            code = kit("models","verify","--tier","standard","--small-backend","onnx","--vlm-engine","llama-cpp")
            if code:
                return code
            from .retrieval import embedding_model,reranker_model
            e = embedding_model()
            next(iter(e.embed(["ADC clock"])))
            r = reranker_model()
            list(r.rerank("ADC",["ADC converter"]))
            result = {"local_models":"verified","inference":"retrieval smoke passed; use a PDF to verify MinerU inference"}
        elif args.command == "webui":
            from .service import serve
            return serve()
        elif args.command == "stop-ui":
            from .service import stop
            result = stop()
        elif args.command=='detect-ai':
            from .integration import detect_clients
            result=detect_clients()
        elif args.command=='configure-ai':
            from .integration import install_skills
            from .runtime import root
            result=install_skills(args.app_root,root(),args.targets)
        elif args.command=='organize':
            from .deployment import organize
            result=organize()
        elif args.command == "recover-job":
            from .recovery import recover_job
            result = recover_job(args.jobid,args.output,args.source)
        elif args.command == "import":
            from .ingest import import_manual,parse_manual,attach_parsed_result
            did = import_manual(args.pdf,args.chip,args.revision,args.title,args.tier,args.batch_pages,args.chip_alias,args.manufacturer)
            print(json.dumps({"document_id":did,"resume":"run.ps1 resume "+did}),file=sys.stderr,flush=True)
            if not args.prepare_only:
                if args.parsed_dir:
                    attach_parsed_result(did,args.parsed_dir)
                else:
                    parse_manual(did)
            result = status(did)
        elif args.command == "resume":
            from .ingest import parse_manual
            parse_manual(args.docid)
            result = status(args.docid)
        elif args.command == "index":
            from .retrieval import build_index
            result = build_index(args.docid,args.lexical_only)
        elif args.command == "status":
            result = status(args.docid)
        elif args.command == "search":
            from .retrieval import search as search_fn
            result = search_fn(args.query,args.chip,args.revision,args.docid,args.top,args.lexical_only,not args.no_rerank,args.english_query)
        elif args.command == "read":
            from .retrieval import read_chunk
            result = read_chunk(args.chunk_id,args.section,args.offset,args.limit)
        else:
            result = render_page(args.docid,args.page,args.bbox)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error":str(exc),"type":type(exc).__name__},ensure_ascii=False),file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
