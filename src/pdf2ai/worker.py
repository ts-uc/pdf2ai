"""Isolated conversion for CLI timeouts. Requests arrive on stdin, never argv."""
import json
import os
import signal
import subprocess
import sys
from contextlib import redirect_stdout

from .vector import ConversionError
from .i18n import set_language


def run_conversion(request, timeout):
    options = {'start_new_session':True} if os.name!='nt' else {
        'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
    process = subprocess.Popen([sys.executable,'-m','pdf2ai.worker'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf-8',**options)
    try:
        stdout,stderr = process.communicate(json.dumps(request),timeout=timeout)
    except BaseException:
        if os.name!='nt':
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        else:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                           capture_output=True,check=False)
            if process.poll() is None: process.kill()
        process.communicate()
        raise
    if process.returncode:
        raise ConversionError(stderr.strip()[-2000:] or 'Conversion worker failed')
    return json.loads(stdout)


def main():
    from .native import convert
    from .multiboard import convert_document
    try:
        request = json.load(sys.stdin)
        set_language(request.pop('language','en'))
        source,output = request.pop('source'),request.pop('output')
        combined = request.pop('combined')
        function = convert_document if combined else convert
        with redirect_stdout(sys.stderr):
            result = function(source,output,**request)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(str(error),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
