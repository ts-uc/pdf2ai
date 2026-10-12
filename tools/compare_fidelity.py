"""Compare PDF views with actual PDFs exported by Illustrator (not AI previews)."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageStat


def render(path, page=0, dpi=144, renderer='mupdf', ghostscript=None):
    if renderer=='ghostscript':
        executable=ghostscript or next((shutil.which(name) for name in ('gs','gswin64c','gswin32c') if shutil.which(name)),None)
        if executable is None:raise RuntimeError('Ghostscript is required for this comparison')
        with tempfile.TemporaryDirectory(prefix='pdf2ai-proof-') as directory:
            target=Path(directory)/'page.png'
            subprocess.run([executable,'-dSAFER','-dBATCH','-dNOPAUSE','-q','-sDEVICE=png16m',
                '-dUseCropBox','-dGraphicsAlphaBits=4','-dTextAlphaBits=4',f'-r{dpi}',
                f'-dFirstPage={page+1}',f'-dLastPage={page+1}','-sOutputFile='+str(target),str(path)],
                capture_output=True,check=True,timeout=120)
            with Image.open(target) as image:return image.convert('RGB')
    with pymupdf.open(path) as pdf:
        pix = pdf[page].get_pixmap(matrix=pymupdf.Matrix(dpi/72, dpi/72), alpha=False)
        return Image.frombytes('RGB', (pix.width,pix.height), pix.samples)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--cases',nargs='+',help='Compare only the named PDF stems')
    parser.add_argument('--report',default='visual-results.json',help='Report filename within the case folder')
    parser.add_argument('--dpi',type=float,default=144)
    parser.add_argument('--max-error',type=float,help='Return failure when mean absolute error exceeds this value')
    parser.add_argument('--renderer',choices=['mupdf','ghostscript'],default='mupdf')
    parser.add_argument('--ghostscript',help='Ghostscript executable for independent rendering')
    args=parser.parse_args()
    if not math.isfinite(args.dpi) or not 72<=args.dpi<=1200:parser.error('--dpi must be between 72 and 1200')
    results=[]
    for original in sorted(args.folder.glob('*.pdf')):
        if args.cases is not None and original.stem not in args.cases:
            continue
        saved=args.folder/'illustrator'/original.name
        if not saved.exists():
            results.append({'case':original.stem,'error':'No Illustrator PDF'})
            continue
        with pymupdf.open(original) as a_doc,pymupdf.open(saved) as b_doc:
            if len(a_doc)!=len(b_doc):
                results.append({'case':original.stem,'error':'Page count differs'})
                continue
            count=len(a_doc)
        for number in range(count):
            results.append(compare_page(original,saved,args.folder,number,count,args.dpi,args.renderer,args.ghostscript))
    if args.cases is not None:
        for missing in sorted(set(args.cases)-{r['case'] for r in results}):
            results.append({'case':missing,'error':'No original PDF'})
    (args.folder/args.report).write_text(json.dumps(results,indent=2))
    for r in results:
        print(r['case'],r.get('mean_absolute_error',r.get('error')),r.get('pixels_difference_over_16'))
    return int(any(r.get('error') or (args.max_error is not None and r.get('mean_absolute_error',float('inf'))>args.max_error) for r in results))


def compare_page(original,saved,folder,number,count,dpi,renderer='mupdf',ghostscript=None):
    a,b=render(original,number,dpi,renderer,ghostscript),render(saved,number,dpi,renderer,ghostscript)
    row={'case':original.stem,'original_size':a.size,'saved_size':b.size,'dpi':dpi,'renderer':renderer}
    if count>1:row['page']=number+1
    if a.size==b.size:
        diff=ImageChops.difference(a,b)
        maximum=ImageChops.lighter(ImageChops.lighter(*diff.split()[:2]),diff.split()[2])
        row['mean_absolute_error']=sum(ImageStat.Stat(diff).mean)/3
        row['pixels_difference_over_16']=sum(maximum.histogram()[17:])/(a.width*a.height)
        image=Image.new('RGB',(a.width*3,a.height+24),'white')
        image.paste(a,(0,24));image.paste(b,(a.width,24));image.paste(diff,(a.width*2,24))
        draw=ImageDraw.Draw(image)
        for x,label in enumerate(('Original PDF','Illustrator re-saved PDF','Absolute difference')):
            draw.text((x*a.width+5,5),label,fill='black')
        suffix=f'-page-{number+1}' if count>1 else ''
        image.save(folder/(original.stem+suffix+'-comparison.png'))
    else:row['error']='Page dimensions differ'
    return row


if __name__=='__main__':raise SystemExit(main())
