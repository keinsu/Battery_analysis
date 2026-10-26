"""Run the packaged EXE, not the source, including an actual local HTTP server."""
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
exe=Path(sys.argv[1]).resolve()
subprocess.run([str(exe),'--self-test'],check=True,timeout=180)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
process=subprocess.Popen([str(exe),'--serve',str(port)])
try:
    for _ in range(90):
        if process.poll() is not None:raise RuntimeError('Packaged server exited early')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=1) as response:
                if response.status==200:break
        except OSError:pass
        time.sleep(1)
    else:raise RuntimeError('Packaged server did not become healthy')
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=5) as response:
        assert response.status==200 and b'<html' in response.read().lower()
    print('FROZEN_HTTP_TEST_OK')
finally:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
