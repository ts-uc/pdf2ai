"""Measure bounded synthetic large-document conversion in fresh processes."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import pikepdf
from pdf2ai.multiboard import convert_document
from pdf2ai.preflight import inspect_document


def worker(case, folder):
    source=folder/(case+'.pdf');output=folder/(case+'.ai')
    pdf=pikepdf.new()
    counts=[30000,6000] if case=='dense-paths' else [20]*100
    for count in counts:
        page=pdf.add_blank_page(page_size=(240,240))
        content=['.1 .4 .7 rg']+[f'{i%200} {(i//200)%200} 1 1 re f' for i in range(count)]
        page.Contents=pdf.make_stream('\n'.join(content).encode())
    pdf.save(source);start=time.perf_counter()
    inspection=inspect_document(source);inspect_seconds=time.perf_counter()-start
    start=time.perf_counter();reports=convert_document(source,output,raster_fallback=False)
    row={'case':case,'synthetic':True,'pages':len(counts),'paths':sum(counts),
         'inspection_seconds':inspect_seconds,'conversion_seconds':time.perf_counter()-start,
         'output_bytes':output.stat().st_size,'all_vector':all(not r['rasterized'] for r in reports),
         'inspection_all_native':all(r['native_supported'] for r in inspection)}
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        row['peak_process_memory_bytes']=peak if sys.platform=='darwin' else peak*1024
    except ImportError:row['peak_process_memory_bytes']=None
    print(json.dumps(row))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=Path('output/medium-benchmark.json'))
    parser.add_argument('--worker',choices=['dense-paths','many-pages'])
    parser.add_argument('--folder',type=Path)
    args=parser.parse_args()
    if args.worker:
        worker(args.worker,args.folder);return
    args.report.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='benchmark-',dir=args.report.parent) as directory:
        for case in ('dense-paths','many-pages'):
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',case,'--folder',directory],
                capture_output=True,text=True,timeout=120,check=True)
            rows.append(json.loads(result.stdout))
    args.report.write_text(json.dumps({'platform':platform.platform(),'cases':rows},indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
