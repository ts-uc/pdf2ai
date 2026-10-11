"""Independently render expanded stroke paths, before Illustrator serialization."""
import argparse
import json
from pathlib import Path

import pikepdf
from PIL import ImageChops, ImageStat
from pdf2ai.vector import read_drawing
from compare_fidelity import render


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--prefix',default='curve-')
    args=parser.parse_args()
    output=args.folder/'outline-proof';output.mkdir(exist_ok=True)
    results=[]
    for source in sorted(args.folder.glob(args.prefix+'*.pdf')):
        with pikepdf.open(source) as original:
            drawing=read_drawing(original.pages[0])
        if drawing.box[:2]!=(0,0):raise ValueError('Fixtures must start at (0,0)')
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=drawing.box[2:])
        page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
        states=pikepdf.Dictionary();content=[]
        for i,item in enumerate(drawing.paths):
            state=item.state
            if item.paint!='fill' or state.fill.model!='RGB' or state.clips:
                raise ValueError('This proof renderer accepts unclipped RGB fill fixtures only')
            states[f'/A{i}']=pikepdf.Dictionary(ca=state.fill_alpha)
            content.append(f'q /A{i} gs '+' '.join(map(str,state.fill.values))+' rg')
            for path in item.paths:
                for op,values in path.commands:
                    content.append(' '.join(map(str,values))+' '+{'m':'m','L':'l','C':'c'}[op])
                if path.closed:content.append('h')
            content.append(('f*' if item.even_odd else 'f')+' Q')
        page.Resources=pikepdf.Dictionary(ExtGState=states)
        page.Contents=pdf.make_stream('\n'.join(content).encode())
        target=output/source.name;pdf.save(target);pdf.close()
        a,b=render(source),render(target)
        if a.size!=b.size:raise ValueError('Unexpected fixture dimensions')
        error=sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/3
        row={'case':source.stem,'mean_absolute_error':error};results.append(row)
        print(source.stem,round(error,6))
    (output/('results-'+args.prefix.rstrip('-')+'.json')).write_text(json.dumps(results,indent=2))


if __name__=='__main__':main()
