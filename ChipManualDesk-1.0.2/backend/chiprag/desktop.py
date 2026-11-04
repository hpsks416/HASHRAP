"""Small Windows GUI; parser/model dependencies live in the separately installed runtime."""
from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

def bundle_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'release'

def default_app():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'ChipManualDesk'

def read_config():
    for base in (bundle_root(),default_app()):
        path=base/'desktop-settings.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return {'app_root':str(default_app()),'library_root':str(Path.home()/'Documents'/'ChipManualLibrary'),
            'python':str(default_app()/'runtime'/'venv'/'Scripts'/'python.exe'),'backend':str(default_app()/'backend')}

class Desk:
    def __init__(self,window):
        self.window=window; self.config=read_config(); self.events=queue.Queue(); self.busy=False
        self.process=None; self.docid=None; self.cancel_path=None; self.manuals={}
        window.title('ChipManualDesk · 芯片手册知识库'); window.geometry('1120x830'); window.minsize(1000,760)
        window.configure(bg='#edf2f8')
        style=ttk.Style(); style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#edf2f8'); style.configure('TLabel',background='#edf2f8',foreground='#192b47')
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',22,'bold'))
        style.configure('TButton',padding=(12,7)); style.configure('Accent.TButton',foreground='white',background='#2458be')
        style.map('Accent.TButton',background=[('active','#1b4392')])
        top=ttk.Frame(window,padding=(24,18)); top.pack(fill='x')
        ttk.Label(top,text='芯片手册知识库',style='Title.TLabel').pack(anchor='w')
        ttk.Label(top,text='本地解析  /  自动向量化  /  原页证据  /  AI 软件接入').pack(anchor='w',pady=(5,0))
        self.tabs=ttk.Notebook(window); self.tabs.pack(fill='both',expand=True,padx=22)
        self.setup_tab=ttk.Frame(self.tabs,padding=18); self.import_tab=ttk.Frame(self.tabs,padding=18)
        self.library_tab=ttk.Frame(self.tabs,padding=18); self.ai_tab=ttk.Frame(self.tabs,padding=18)
        for tab,title in ((self.import_tab,'解析并入库'),(self.library_tab,'手册与检索'),(self.ai_tab,'AI 软件配置'),(self.setup_tab,'环境与存储')):
            self.tabs.add(tab,text=title)
        self.make_setup(); self.make_import(); self.make_library(); self.make_ai()
        footer=ttk.Frame(window,padding=(24,12)); footer.pack(fill='x')
        self.status=tk.StringVar(value='就绪' if self.installed() else '首次使用：请先完成一键安装')
        ttk.Label(footer,textvariable=self.status).pack(anchor='w')
        self.progress=ttk.Progressbar(footer,maximum=100); self.progress.pack(fill='x',pady=7)
        self.log=tk.Text(footer,height=7,bg='#122038',fg='#d5e4ff',font=('Consolas',9),relief='flat',wrap='word')
        self.log.pack(fill='x')
        # Reserve the footer before the flexible notebook so progress/logs remain visible.
        footer.pack_configure(side='bottom')
        self.tabs.pack_forget(); self.tabs.pack(fill='both',expand=True,padx=22)
        window.after(200,self.tick); window.protocol('WM_DELETE_WINDOW',self.close)
        if self.installed(): self.refresh()
        else: self.tabs.select(self.setup_tab)

    def installed(self): return Path(self.config['python']).is_file() and (Path(self.config['backend'])/'chiprag'/'cli.py').is_file()
    def line(self,text):
        self.log.insert('end',text.rstrip()+'\n'); self.log.see('end')
    def env(self):
        env=os.environ.copy(); env['PYTHONUTF8']='1'; env['PYTHONIOENCODING']='utf-8'; env['CHIPRAG_DATA']=self.config['library_root']
        env['PYTHONPATH']=self.config['backend']
        if self.cancel_path: env['CHIPRAG_CANCEL_FILE']=str(self.cancel_path)
        return env
    def cli(self,args): return [self.config['python'],'-m','chiprag.cli',*args]
    def start(self,command,cwd=None,callback=None):
        if self.busy: messagebox.showinfo('任务进行中','请等待当前任务完成。'); return
        self.busy=True; self.docid=None; self.progress['value']=0; self.status.set('正在运行，请查看进度…')
        self.cancel_path=Path(self.config['library_root'])/'tmp'/('cancel-'+uuid.uuid4().hex)
        def worker():
            try:
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                self.process=subprocess.Popen(command,cwd=cwd,env=self.env(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                              text=True,encoding='utf-8',errors='replace',creationflags=flags)
                captured=[]
                for line in self.process.stdout:
                    captured.append(line); self.events.put(('line',line))
                code=self.process.wait(); self.events.put(('done',(code,''.join(captured),callback)))
            except Exception as exc: self.events.put(('done',(1,str(exc),callback)))
        threading.Thread(target=worker,daemon=True).start()
    def run(self,args,callback=None):
        if not self.installed(): messagebox.showinfo('尚未安装','先在“环境与存储”中完成安装。'); self.tabs.select(self.setup_tab); return
        self.start(self.cli(args),self.config['backend'],callback)

    def make_setup(self):
        p=self.setup_tab
        ttk.Label(p,text='首次安装会下载独立 Python、MinerU 和模型；完成后可在本机解析与检索。',wraplength=900).pack(anchor='w')
        ttk.Label(p,text='知识库固定位置').pack(anchor='w',pady=(18,5))
        row=ttk.Frame(p); row.pack(fill='x')
        self.library_path=tk.StringVar(value=self.config['library_root']); ttk.Entry(row,textvariable=self.library_path).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='选择文件夹',command=self.pick_library).pack(side='left',padx=8)
        ttk.Label(p,text='应用与运行环境位置').pack(anchor='w',pady=(14,5))
        self.app_path=tk.StringVar(value=self.config['app_root']); ttk.Entry(p,textvariable=self.app_path).pack(fill='x')
        ttk.Label(p,text='手册按制造商 / 芯片 / 手册分类保存独立索引，统一索引用于跨手册检索。',wraplength=900).pack(anchor='w',pady=14)
        buttons=ttk.Frame(p); buttons.pack(fill='x')
        ttk.Button(buttons,text='一键安装 / 修复',style='Accent.TButton',command=self.install).pack(side='left')
        ttk.Button(buttons,text='检查模型',command=lambda:self.run(['models-verify'])).pack(side='left',padx=8)
        ttk.Button(buttons,text='打开知识库目录',command=self.open_library).pack(side='left')
        ttk.Label(p,text='已有知识库改位置时，请先复制完整目录，再重新安装指向新位置；原目录不会自动删除。',wraplength=900).pack(anchor='w',pady=18)
    def pick_library(self):
        value=filedialog.askdirectory(title='选择固定知识库位置')
        if value: self.library_path.set(value)
    def install(self):
        script=bundle_root()/'Install.ps1'
        if not script.exists(): script=Path(self.config['app_root'])/'Install.ps1'
        if not script.exists(): messagebox.showerror('安装脚本缺失','请完整解压发行包，保留 EXE 旁的脚本和 backend 文件夹。'); return
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-InstallRoot',self.app_path.get(),'-LibraryRoot',self.library_path.get()]
        def done(code,text):
            path=Path(self.app_path.get())/'desktop-settings.json'
            self.config=json.loads(path.read_text(encoding='utf-8')) if path.exists() else read_config()
            if not code: self.status.set('安装完成，可以选择 PDF 解析并入库。'); self.refresh()
        self.start(command,str(script.parent),done)

    def make_import(self):
        p=self.import_tab
        ttk.Label(p,text='选择 PDF 后，一次完成分批解析、向量化和分类归档。').pack(anchor='w')
        self.pdf=tk.StringVar(); self.chip=tk.StringVar(); self.revision=tk.StringVar(); self.title=tk.StringVar(); self.aliases=tk.StringVar(); self.vendor=tk.StringVar()
        self.parsed=tk.StringVar(); self.tier=tk.StringVar(value='standard')
        row=ttk.Frame(p); row.pack(fill='x',pady=(15,8))
        ttk.Entry(row,textvariable=self.pdf).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='选择 PDF',command=self.pick_pdf).pack(side='left',padx=8)
        form=ttk.Frame(p); form.pack(fill='x')
        fields=[('制造商',self.vendor),('芯片或系列（必填）',self.chip),('手册编号 / 标题',self.title),('手册修订版（必填）',self.revision),('适用型号，逗号分隔',self.aliases)]
        for i,(label,value) in enumerate(fields):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',pady=6,padx=(0,15)); ttk.Entry(form,textvariable=value).grid(row=i,column=1,sticky='ew',pady=6)
        form.columnconfigure(1,weight=1)
        row=ttk.Frame(p); row.pack(fill='x',pady=8)
        ttk.Label(row,text='解析质量').pack(side='left'); ttk.Combobox(row,textvariable=self.tier,values=['standard','advanced','basic'],state='readonly',width=14).pack(side='left',padx=12)
        ttk.Label(row,text='默认每批 50 页，支持中断后恢复').pack(side='left')
        row=ttk.Frame(p); row.pack(fill='x',pady=5)
        ttk.Entry(row,textvariable=self.parsed).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='复用已有解析结果（可选）',command=self.pick_parsed).pack(side='left',padx=8)
        row=ttk.Frame(p); row.pack(fill='x',pady=10)
        ttk.Button(row,text='开始解析并入库',style='Accent.TButton',command=self.import_pdf).pack(side='left')
        ttk.Button(row,text='安全暂停',command=self.pause).pack(side='left',padx=8)
    def pick_pdf(self):
        value=filedialog.askopenfilename(filetypes=[('PDF 手册','*.pdf')])
        if value:
            self.pdf.set(value)
            if not self.title.get(): self.title.set(Path(value).stem)
    def pick_parsed(self):
        value=filedialog.askdirectory(title='选择包含 middle_json.json 的完整解析目录')
        if value: self.parsed.set(value)
    def import_pdf(self):
        if not Path(self.pdf.get()).is_file() or not self.chip.get().strip() or not self.revision.get().strip():
            messagebox.showinfo('填写手册信息','请选择 PDF 并填写芯片型号和手册修订版；未知版本可明确填 unknown。'); return
        args=['import',self.pdf.get(),'--chip',self.chip.get().strip(),'--revision',self.revision.get().strip(),'--title',self.title.get() or Path(self.pdf.get()).stem,'--tier',self.tier.get(),'--manufacturer',self.vendor.get() or 'Unspecified']
        for alias in self.aliases.get().replace('，',',').split(','):
            if alias.strip(): args+=['--chip-alias',alias.strip()]
        if self.parsed.get(): args+=['--parsed-dir',self.parsed.get()]
        self.run(args)
    def pause(self):
        if self.busy and not self.docid:
            messagebox.showinfo('正在执行环境操作','当前环境操作请等待完成；解析与索引任务开始后可安全暂停。'); return
        if self.busy and self.cancel_path:
            self.cancel_path.parent.mkdir(parents=True,exist_ok=True); self.cancel_path.touch()
            self.status.set('已请求安全暂停：解析将在当前批次结束后停止。')

    def make_library(self):
        p=self.library_tab; row=ttk.Frame(p); row.pack(fill='x')
        ttk.Button(row,text='刷新手册',command=self.refresh).pack(side='left'); ttk.Button(row,text='恢复选中任务',command=self.resume).pack(side='left',padx=8)
        ttk.Button(row,text='打开选中 PDF',command=self.open_pdf).pack(side='left')
        self.tree=ttk.Treeview(p,columns=('title','chip','revision','pages','state'),show='headings',height=8)
        for name,label,width in [('title','手册',400),('chip','芯片 / 系列',210),('revision','版本',60),('pages','页数',60),('state','状态',100)]:
            self.tree.heading(name,text=label); self.tree.column(name,width=width)
        self.tree.pack(fill='x',pady=12)
        self.query=tk.StringVar(); row=ttk.Frame(p); row.pack(fill='x')
        ttk.Entry(row,textvariable=self.query).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='检索选中手册',command=self.search).pack(side='left',padx=8)
        self.results=tk.Text(p,height=9,wrap='word',font=('Microsoft YaHei UI',10),relief='flat'); self.results.pack(fill='both',expand=True,pady=12)
        ttk.Label(p,text='这里显示证据片段；综合问答由配置好的 Codex / Claude Code 完成。').pack(anchor='w')
    def refresh(self):
        if not self.installed() or self.busy: return
        def done(code,text):
            if code: return
            try:
                rows=json.loads(text)
                self.tree.delete(*self.tree.get_children()); self.manuals={m['id']:m for m in rows}
                labels={'ready':'可查询','prepared':'待解析','parsing':'解析中','parsed':'待建索引','indexing':'索引中','paused':'已暂停','failed':'需恢复'}
                for m in rows: self.tree.insert('', 'end',iid=m['id'],values=(m['title'],m['chip'],m['revision'],m['pages'],labels.get(m['state'],m['state'])))
            except Exception as exc: self.line(str(exc))
        self.run(['status'],done)
    def selected(self):
        selection=self.tree.selection()
        if not selection: messagebox.showinfo('选择手册','先在列表中选择一份手册。'); return None
        return selection[0]
    def resume(self):
        did=self.selected()
        if did: self.run(['resume',did])
    def open_pdf(self):
        did=self.selected()
        if did: os.startfile(str(Path(self.config['library_root'])/'manuals'/did/'source.pdf'))
    def search(self):
        did=self.selected()
        if not did or not self.query.get().strip(): return
        def done(code,text):
            if code: return
            try:
                data=json.loads(text); self.results.delete('1.0','end')
                for hit in data['results']:
                    self.results.insert('end',f"PDF 第 {hit['page']} 页 · {' / '.join(hit['section'])}\n{hit['text']}\n\n")
            except Exception as exc: self.line(str(exc))
        self.run(['search',self.query.get(),'--docid',did,'--top','5','--no-rerank'],done)

    def make_ai(self):
        p=self.ai_tab
        ttk.Label(p,text='自动检测已安装的 AI 软件，只配置已支持的本地技能入口。').pack(anchor='w')
        ttk.Label(p,text='支持 Codex 和 Claude Code；Claude 普通桌面聊天不能仅靠本机目录接入。',wraplength=900).pack(anchor='w',pady=8)
        self.ai_info=tk.Text(p,height=12,wrap='word',font=('Microsoft YaHei UI',10),relief='flat'); self.ai_info.pack(fill='both',expand=True,pady=12)
        row=ttk.Frame(p); row.pack(fill='x')
        ttk.Button(row,text='检测本机 AI 软件',command=self.detect_ai).pack(side='left')
        ttk.Button(row,text='一键配置已检测软件',style='Accent.TButton',command=self.configure_ai).pack(side='left',padx=8)
        ttk.Label(p,text='只新增/更新本工具的 Skill；原技能会备份到知识库 backups/skills。完成后打开新聊天使用。',wraplength=900).pack(anchor='w',pady=12)
    def detect_ai(self):
        from .integration import detect_clients
        self.ai_info.delete('1.0','end')
        for c in detect_clients():
            state='已检测' if c['detected'] else '未检测到'
            support='可自动配置' if c['supported'] else c.get('note','需手动配置')
            self.ai_info.insert('end',f"{c['name']}：{state} · {support}\n")
    def configure_ai(self): self.run(['configure-ai','--app-root',self.config['app_root']])
    def open_library(self):
        path=Path(self.config['library_root']); path.mkdir(parents=True,exist_ok=True); os.startfile(str(path))
    def tick(self):
        try:
            while True:
                event,data=self.events.get_nowait()
                if event=='line':
                    self.line(data)
                    try:
                        obj=json.loads(data)
                        if obj.get('document_id'): self.docid=obj['document_id']
                    except (ValueError,AttributeError): pass
                else:
                    code,text,callback=data; self.busy=False; self.process=None
                    stopped=self.cancel_path and self.cancel_path.exists()
                    self.status.set('任务已安全暂停，可从列表恢复。' if stopped else ('操作完成' if code==0 else '操作未完成，请查看下方日志'))
                    if not code: self.progress['value']=100
                    if callback: callback(code,text)
                    elif not code: self.window.after(100,self.refresh)
        except queue.Empty: pass
        if self.busy and self.docid:
            try:
                m=json.loads((Path(self.config['library_root'])/'manuals'/self.docid/'manifest.json').read_text(encoding='utf-8'))
                ip=m.get('index_progress',{})
                if m['state']=='indexing' and ip.get('total'):
                    percent=ip['completed']/ip['total']*100; self.progress['value']=percent
                    self.status.set(f"生成向量：{ip['completed']:,} / {ip['total']:,}（{percent:.1f}%）")
                elif m['state']=='parsing':
                    done=sum(s['end']-s['start'] for s in m['shards'] if s['state']=='done')
                    self.progress['value']=done/m['pages']*100; self.status.set(f"解析：已完成 {done} / {m['pages']} 页")
            except (OSError,ValueError,KeyError): pass
        self.window.after(250,self.tick)
    def close(self):
        if self.busy:
            if messagebox.askyesno('任务进行中','请求安全暂停？请等当前批次结束后再关闭窗口。'):
                self.pause()
            return
        self.window.destroy()

def main():
    window=tk.Tk(); app=Desk(window)
    if '--smoke-report' in sys.argv:
        report=Path(sys.argv[sys.argv.index('--smoke-report')+1])
        report.write_text(json.dumps({'title':window.title(),'tk':window.tk.call('info','patchlevel'),'config':app.config,'installed':app.installed()},ensure_ascii=False,indent=2),encoding='utf-8')
        window.after(5000,window.destroy)
    window.mainloop()
