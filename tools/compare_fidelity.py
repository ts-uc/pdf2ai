"""Compare PDF views with actual PDFs exported by Illustrator (not AI previews)."""
import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageStat


def render(path):
    with pymupdf.open(path) as pdf:
        pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        return Image.frombytes('RGB', (pix.width,pix.height), pix.samples)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--cases',nargs='+',help='Compare only the named PDF stems')
    parser.add_argument('--report',default='visual-results.json',help='Report filename within the case folder')
    args=parser.parse_args()
    results=[]
    for original in sorted(args.folder.glob('*.pdf')):
        if args.cases is not None and original.stem not in args.cases:
            continue
        saved=args.folder/'illustrator'/original.name
        if not saved.exists():
            results.append({'case':original.stem,'error':'No Illustrator PDF'})
            continue
        a,b=render(original),render(saved)
        row={'case':original.stem,'original_size':a.size,'saved_size':b.size}
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
            image.save(args.folder/(original.stem+'-comparison.png'))
        results.append(row)
    if args.cases is not None:
        for missing in sorted(set(args.cases)-{r['case'] for r in results}):
            results.append({'case':missing,'error':'No original PDF'})
    (args.folder/args.report).write_text(json.dumps(results,indent=2))
    for r in results:
        print(r['case'],r.get('mean_absolute_error',r.get('error')),r.get('pixels_difference_over_16'))


if __name__=='__main__':main()
