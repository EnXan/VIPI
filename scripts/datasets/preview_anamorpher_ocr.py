#!/usr/bin/env python3
"""Create representative native pixel crops and verified reveal previews."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT/'datasets/catalog/ocr'
OUTPUT = ROOT/'datasets/derived/anamorpher/v1/review'


def main():
    manifest = json.loads((CATALOG/'anamorpher_manifest.json').read_text())
    groups = {}
    for record in manifest['records']:
        c = record['configuration']
        key = (c['method'],c['profile'],c['parameters'].get('offset'),c['background'])
        if record['accepted_for_ocr']:
            groups.setdefault(key,record)
    records = list(groups.values())
    geometry = {}
    for record in manifest['records']:
        c = record['configuration']
        if (record['accepted_for_ocr'] and c['method'] == 'nearest'
                and c['parameters']['offset'] == 2 and c['profile'] == 'default'
                and c['target_size'] == 1092 and c['font_size_px'] == 64):
            geometry.setdefault(c['alignment'],record)
    seen = {r['id'] for r in records}
    records.extend(r for r in geometry.values() if r['id'] not in seen)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    font = ImageFont.truetype(manifest['font'],17)
    pages = []
    for start in range(0,len(records),4):
        subset = records[start:start+4]
        canvas = Image.new('RGB',(1240,250*len(subset)), '#eeeeee')
        draw = ImageDraw.Draw(canvas)
        for row,record in enumerate(subset):
            c = record['configuration']; best = record['best_reveal']; y = row*250
            label = f"{record['id']} | {c['method']} / {c['profile']} / offset {c['parameters'].get('offset')} / {c['background']}"
            draw.text((15,y+8),label,font=font,fill='black')
            draw.text((15,y+34),'Original: 1:1-Pixelausschnitt (keine Skalierung)',font=font,fill='black')
            draw.text((410,y+34),f"Gepruefte Ansicht: {best['backend']} / {best['method']} -> {c['target_size']} px",font=font,fill='black')
            x0,y0,x1,y1 = record['target_bbox_xyxy']
            # Crop only: resizing this source crop could itself trigger the payload.
            with Image.open(ROOT/record['image']) as image:
                cx,cy = (x0+x1)*2,(y0+y1)*2
                crop = image.crop((max(0,cx-180),max(0,cy-80),min(image.width,cx+180),min(image.height,cy+80)))
                canvas.paste(crop,(15,y+70))
            with Image.open(ROOT/best['image']) as image:
                crop = image.crop((max(0,x0-8),max(0,y0-8),min(image.width,x1+8),min(image.height,y1+8)))
                crop.thumbnail((810,175))
                canvas.paste(crop,(410,y+70))
        path = OUTPUT/f'comparison_{start//4:02d}.png'
        canvas.save(path)
        pages.append({'image':path.relative_to(ROOT).as_posix(),'sample_ids':[r['id'] for r in subset]})
    output = {'representative_count':len(records),'pages':pages,
              'scope':'Representative accepted configurations only; no exhaustive manual certification.',
              'native_crops':'Unscaled 1:1 source pixels; reveal crops may be reduced for contact-sheet display.'}
    (OUTPUT/'preview_manifest.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()
