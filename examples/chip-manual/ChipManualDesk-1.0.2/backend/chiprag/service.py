"""Local API/UI supervisor using normal child processes rather than named-pipe control."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx
from filelock import FileLock
from .runtime import ROOT,prepare,write_json,settings

API_URL = "http://127.0.0.1:18765"
UI_URL = "http://127.0.0.1:7860"

def configure_ui_polling():
    # MinerU 4.0.12 exposes no public UI job-wait setting. Keep this compatibility
    # adjustment in our launcher, rather than modifying the installed dependency.
    import math
    from mineru.parser import api_client
    cfg=settings()
    timeout=float(cfg.get('ui_wait_timeout_seconds',28800))
    interval=float(cfg.get('ui_poll_interval_seconds',2))
    if not 60<=timeout<=604800 or not .1<=interval<=60:
        raise ValueError('Invalid UI wait timeout / polling interval')
    api_client._POLL_INTERVAL_SECONDS=interval
    api_client._POLL_MAX_ATTEMPTS=math.ceil(timeout/interval)

def child(mode):
    data=prepare()
    os.environ.pop("MINERU_MANAGED_CONTROL",None)
    if mode=='api':
        from mineru.kit.commands.api_server import main
        sys.argv=['mineru-kit api-server','--host','127.0.0.1','--port','18765',
                  '--tier','standard','--concurrency','1','--upload-dir',str(data/'api')]
    else:
        configure_ui_polling()
        from mineru.kit.commands.webui import main
        sys.argv=['mineru-kit webui','--api-url',API_URL,'--server-name','127.0.0.1',
                  '--server-port','7860','--output-dir',str(data/'ui'),'--no-enable-example']
    main()

def stop():
    path=prepare()/'ui.stop'
    path.touch()
    return {'stop_requested':True}

def serve():
    data=prepare()
    processes=[]
    logs=[]
    stopfile=data/'ui.stop'
    with FileLock(str(data/'ui.lock'),timeout=1):
        stopfile.unlink(missing_ok=True)
        try:
            for mode in ('api','ui'):
                log=(data/'logs'/f'{mode}.log').open('w',encoding='utf-8')
                logs.append(log)
                env=os.environ.copy()
                env.pop('MINERU_MANAGED_CONTROL',None)
                proc=subprocess.Popen([sys.executable,'-m','chiprag.service',mode],cwd=ROOT,
                                      env=env,stdout=log,stderr=subprocess.STDOUT)
                processes.append(proc)
                url=API_URL+'/v1/health' if mode=='api' else UI_URL+'/config'
                deadline=time.monotonic()+90
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f'{mode} exited {proc.returncode}; inspect {data / "logs" / (mode+".log")}')
                    try:
                        with httpx.Client(trust_env=False,timeout=2) as client:
                            response=client.get(url)
                            response.raise_for_status()
                            break
                    except httpx.HTTPError:
                        if time.monotonic()>deadline:
                            raise RuntimeError(f'{mode} startup timeout; inspect local logs')
                        time.sleep(.5)
            write_json(data/'ui-session.json',{'supervisor_pid':os.getpid(),
                       'api_pid':processes[0].pid,'ui_pid':processes[1].pid,'api_url':API_URL,'ui_url':UI_URL})
            print(f'Local MinerU ready: {UI_URL}',flush=True)
            while not stopfile.exists():
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('Local service exited unexpectedly; inspect data/logs')
                time.sleep(.5)
        except KeyboardInterrupt:
            pass
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            for log in logs:
                log.close()
            (data/'ui-session.json').unlink(missing_ok=True)
            stopfile.unlink(missing_ok=True)
    return 0

if __name__=='__main__':
    child(sys.argv[1])
