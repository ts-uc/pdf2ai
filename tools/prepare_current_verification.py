"""Reconvert all local fidelity fixtures and record runtime, sizes and input hashes."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import time

import pikepdf
from pdf2ai.native import convert
from pdf2ai.dic import normalize_pdf_spots as normalize_dic
from pdf2ai.toyo import normalize_pdf_spots as normalize_toyo
from make_medium_cases import generate
from pdf2ai.image_resources import normalize_image_spaces
from pdf2ai.pdf_groups import explicit_page_knockout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--sources',type=Path,default=Path('output/fidelity-check/after'))
    parser.add_argument('--extra',type=Path,nargs='*',default=[])
    parser.add_argument('--reference-ai',type=Path,help='Read-only source AI for the DIC reference case')
    parser.add_argument('--expected-ai',type=Path,help='Read-only authoritative AI for visual comparison')
    args=parser.parse_args();args.folder.mkdir(parents=True,exist_ok=True)
    expected_parent=Path(__file__).resolve().parents[1]/'output/fidelity-check/after'
    if args.folder.resolve().parent!=expected_parent.resolve():
        parser.error('Verification folder must be a direct child of output/fidelity-check/after')
    if bool(args.reference_ai)!=bool(args.expected_ai):parser.error('--reference-ai and --expected-ai must be supplied together')
    reference_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (args.reference_ai,args.expected_ai) if path is not None}
    generate(args.folder)
    sources=[*sorted(args.sources.glob('*.pdf')),*args.extra,*sorted(args.folder.glob('medium-*.pdf'))]
    if args.reference_ai:
        inputs=args.folder/'.inputs';inputs.mkdir(exist_ok=True)
        reference_source=inputs/'dic1-reference.pdf'
        with pikepdf.open(args.reference_ai) as pdf:pdf.save(reference_source)
        sources.append(reference_source)
    rows=[]
    for source in sources:
        digest=hashlib.sha256(source.read_bytes()).hexdigest();start=time.perf_counter()
        try:
            output=args.folder/source.with_suffix('.ai').name
            report=convert(source,output,overwrite=True,raster_dpi=144)
            expected=args.folder/source.name
            with pikepdf.open(source) as pdf:
                for page in pdf.pages:normalize_dic(page);normalize_toyo(page);normalize_image_spaces(page,pdf);explicit_page_knockout(pdf,page)
                if source.resolve()==expected.resolve():
                    # The generated fixtures are disposable, never reference AI.
                    with pikepdf.open(source,allow_overwriting_input=True) as writable:
                        for page in writable.pages:normalize_dic(page);normalize_toyo(page);normalize_image_spaces(page,writable);explicit_page_knockout(writable,page)
                        writable.save(expected)
                else:pdf.save(expected)
            row={'case':source.stem,'source':str(source),'input_sha256':digest,
                 'seconds':time.perf_counter()-start,'output_bytes':output.stat().st_size,
                 'conversion':report}
            if args.expected_ai and source.stem=='dic1-reference':
                with pikepdf.open(args.expected_ai) as pdf:pdf.save(expected)
        except Exception as error:
            row={'case':source.stem,'source':str(source),'input_sha256':digest,'error':str(error)}
        rows.append(row)
    result={'platform':platform.platform(),'python':platform.python_version(),
            'read_only_reference_sha256':reference_hashes,
            'dependencies':{name:importlib.metadata.version(name) for name in ('pikepdf','PyMuPDF','Pillow','fonttools')},
            'cases':rows}
    for path,digest in reference_hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise RuntimeError('Reference AI changed during verification: '+path)
    (args.folder/'current-conversion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    controls={'run':'after','subfolder':args.folder.name,'cases':[row['case']+'.ai' for row in rows if 'error' not in row]}
    (args.folder.parent.parent/'run.json').write_text(json.dumps(controls,indent=2)+'\n')
    print(json.dumps({'cases':len(rows),'errors':[r for r in rows if 'error' in r],
        'seconds':sum(r.get('seconds',0) for r in rows)},ensure_ascii=False))


if __name__=='__main__':main()
