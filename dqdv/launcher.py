"""Windows portable launcher: local Streamlit server plus a small control window."""
import multiprocessing
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def command(*args):
    return ([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,__file__])+list(args)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def serve(port):
    from streamlit.web import bootstrap
    bootstrap.run(str(resource_root()/'app.py'),False,[],{
        'server.address':'127.0.0.1','server.port':int(port),'server.headless':True,
        'browser.gatherUsageStats':False,'server.fileWatcherType':'none',
        'global.developmentMode':False,
    })


def self_test():
    # Exercise frozen imports, numerical engine, and the uploaded-data UI path.
    import io
    from unittest.mock import patch
    import numpy as np
    import pandas as pd
    import core
    import view
    from streamlit.testing.v1 import AppTest
    raw=pd.DataFrame({'Voltage(V)':np.linspace(4.2,3.,101),'Current(mA)':-1000.,
        'Capacity(mAh)':np.linspace(0,1000,101),'TotCycle':1,'Type':'방전','StepNo':4,'Channel':'test'})
    mapping=dict(voltage='Voltage(V)',current='Current(mA)',capacity='Capacity(mAh)',cycle='TotCycle',type='Type')
    frame=core.normalize(raw,mapping,dict(voltage='V',current='mA',capacity='mAh'))
    result,_=core.calculate_cycle(frame,'1','discharge')
    np.testing.assert_allclose(result['dqdv'],-1000/1.2,atol=1e-8)
    file=io.BytesIO(raw.to_csv(index=False).encode());file.name='synthetic.csv'
    with patch('streamlit.file_uploader',return_value=file):
        app=AppTest.from_file(str(resource_root()/'app.py'),default_timeout=60).run()
        if app.exception:raise RuntimeError(str([x.message for x in app.exception]))
    print('FROZEN_SELF_TEST_OK',flush=True)


def main():
    multiprocessing.freeze_support()
    if len(sys.argv)>1 and sys.argv[1]=='--serve':
        serve(sys.argv[2]);return
    if len(sys.argv)>1 and sys.argv[1]=='--self-test':
        self_test();return
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.title('dQ/dV Cycling');window.geometry('460x220')
    port=free_port();url=f'http://127.0.0.1:{port}'
    log_path=Path(tempfile.gettempdir())/f'dqdv-{os.getpid()}.log'
    log=log_path.open('w',encoding='utf-8')
    process=subprocess.Popen(command('--serve',str(port)),stdout=log,stderr=log,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    status=tk.StringVar(value='분석 화면을 준비하고 있습니다…')
    tk.Label(window,text='dQ/dV Cycling',font=('',18)).pack(pady=16)
    tk.Label(window,textvariable=status,wraplength=430).pack(pady=8)
    button=tk.Button(window,text='분석 화면 열기',command=lambda:webbrowser.open(url),state='disabled')
    button.pack(pady=8)
    tk.Label(window,text='이 창을 닫으면 분석 프로그램도 종료됩니다.').pack()
    started=time.monotonic()
    def close():
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close();window.destroy()
    def ready():
        if process.poll() is not None:
            status.set('실행에 실패했습니다.');messagebox.showerror('실행 오류',f'로그 파일: {log_path}');return
        try:
            with urllib.request.urlopen(url+'/_stcore/health',timeout=.5) as response:
                healthy=response.status==200
        except Exception:healthy=False
        if healthy:
            status.set('브라우저에서 CSV를 선택해 분석하세요.');button.config(state='normal');webbrowser.open(url);return
        if time.monotonic()-started>90:
            status.set(f'시작 지연: 로그 확인 {log_path}')
        window.after(700,ready)
    window.protocol('WM_DELETE_WINDOW',close);window.after(500,ready);window.mainloop()


if __name__=='__main__':main()
