from pathlib import Path
import os
import subprocess
import sys
exe=Path(sys.argv[1]).resolve()
output=Path('native-verification.txt').resolve()
if output.exists():output.unlink()
env=os.environ.copy()
for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'):env.pop(key,None)
env['PATH']=str(Path(env.get('SystemRoot','C:/Windows'))/'System32')
try:
    subprocess.run([str(exe),'--self-test',str(output)],env=env,check=True,timeout=180)
except Exception:
    error=Path(str(output)+'.error.txt')
    if error.exists():print(error.read_text(encoding='utf-8'))
    raise
assert output.read_text(encoding='utf-8')=='NATIVE_EXE_SELF_TEST_OK'
assert output.with_suffix('.png').is_file()
print('Native standalone EXE passed: tool selector, Qt window, CSV, source parity, cycle selection, hover coordinates and invalid selection.')
