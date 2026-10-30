from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
root=Path(SPECPATH)
a=Analysis([str(root/'native_app.py')],pathex=[str(root)],
    hiddenimports=collect_submodules('scipy._external',filter=lambda name: '.tests' not in name),
    excludes=['streamlit','plotly','pytest','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick'],
    noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='DQDVAnalyzer-Desktop',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False)
