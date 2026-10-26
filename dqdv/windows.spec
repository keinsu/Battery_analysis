from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata
root=Path(SPECPATH)
datas=[];binaries=[];hiddenimports=['core','view','legacy_backend.dqdv','tkinter','streamlit.testing.v1']
for package in ('streamlit','plotly'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hiddenimports+=h
for package in ('streamlit','plotly','pandas','numpy','scipy'):
    datas+=copy_metadata(package)
datas += [(str(root/'app.py'),'.')]
a=Analysis([str(root/'launcher.py')],pathex=[str(root)],binaries=binaries,datas=datas,
           hiddenimports=hiddenimports,excludes=['pytest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='DQDVAnalyzer',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='DQDVAnalyzer')
