#!/usr/bin/env python3
"""Check the entire generated grid, reference coverage and reproducibility."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import itertools
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from jsonschema import Draft202012Validator

import generate_anamorpher_ocr as gen


def profile_equivalence():
    checks = []
    for method, module in gen.GENERATORS.items():
        for profile, parameters in gen.PROFILES.items():
            for offset in range(4) if method == 'nearest' else (None,):
                params = dict(parameters)
                if method == 'nearest':
                    params.pop('dark_frac')
                    params['offset'] = offset
                kwargs = {k:v for k,v in params.items() if k != 'gamma'}
                kwargs['gamma_target'] = params['gamma']
                rng = np.random.RandomState(21)
                decoy = rng.uniform(.02,.2,(32,32,3)).astype(np.float32)
                target = rng.uniform(.01,.12,(8,8,3)).astype(np.float32)
                function = module.embed_nn if method == 'nearest' else module.embed_bilinear if method == 'bilinear' else module.embed
                np.random.seed(741)
                expected = function(decoy,target,**kwargs)
                actual = gen.embed(decoy,target,method,params,741)
                error = float(np.max(np.abs(expected-actual)))
                assert error <= 2e-6, (method,profile,error)
                assert np.array_equal(actual[...,1:],decoy[...,1:])
                checks.append({'method':method,'profile':profile,'offset':offset,'max_linear_error':error})
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-catalog',action='store_true')
    parser.add_argument('--reproduce',action='store_true')
    args = parser.parse_args()
    lock = (gen.OUTPUT/'.generation.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Wait for the Anamorpher generator/append process to finish')
    manifest = json.loads(gen.MANIFEST.read_text())
    grid = list(gen.configurations())
    records = manifest['records']
    assert len(records) == manifest['planned_count'] == len(grid) == 1728
    assert manifest['adapter_sha256'] == gen.sha(Path(gen.__file__).with_name('anamorpher_adapter.py'))
    assert manifest['font_sha256'] == gen.sha(gen.FONT)
    versions = {'numpy':gen.np.__version__,'pillow':gen.PIL.__version__,
                'opencv':gen.cv2.__version__,'pytorch':gen.torch.__version__,
                'tensorflow':gen.tf.__version__}
    assert manifest['libraries'] == versions
    for path,digest in manifest['upstream_file_sha256'].items():
        assert gen.sha(gen.ROOT/path) == digest, path
    assert len({record['image'] for record in records}) == len(records)
    assert len({record['sha256'] for record in records}) == len(records)
    checked_paths = set()
    missing_full_checks = []
    for index,record in enumerate(records):
        assert record['id'] == f'anamorpher_{index:04d}'
        assert record['configuration'] == grid[index]
        expected_seed = (manifest['seed'] + int.from_bytes(hashlib.sha256(json.dumps(grid[index],sort_keys=True).encode()).digest()[:4],'big')) % 2**32
        assert record['seed'] == expected_seed
        assert record['text'] == gen.TEXTS[grid[index]['text_id']]
        size = grid[index]['target_size']
        assert record['source_dimensions'] == [size*4,size*4]
        assert record['scope'] == 'target_text_only_after_declared_downscale'
        assert record['content_group_id'] == f'anamorpher_payload_{grid[index]["text_id"]}'
        assert {(p['backend'],p['method']) for p in record['downscale_probes']} == set(itertools.product(gen.BACKENDS,gen.METHODS))
        assert len(record['downscale_probes']) == 12
        for path_key,hash_key,dimensions in (
            ('image','sha256',(size*4,size*4)), ('target_image','target_sha256',(size,size)),
            ('decoy_image','decoy_sha256',(size*4,size*4)),
        ):
            path = gen.ROOT/record[path_key]
            if str(path) not in checked_paths:
                assert gen.sha(path) == record[hash_key], str(path)
                with Image.open(path) as image:
                    assert image.mode == 'RGB' and image.size == dimensions
                    image.verify()
                checked_paths.add(str(path))
        best = record['best_reveal']
        path = gen.ROOT/best['image']
        assert gen.sha(path) == best['sha256'], str(path)
        with Image.open(path) as image:
            assert image.mode == 'RGB' and image.size == (size,size)
            image.verify()
        assert record['accepted_for_ocr'] == (best['ocr_score'] >= .95 and best['stroke_contrast_gray_levels'] >= 3)
        if not best.get('full_image_ocr_verified'):
            # Early generation evaluated whole frames; independently certify their
            # saved full views too, so every final record uses the same contract.
            pixels = np.asarray(Image.open(path))
            score,recognized = gen.ocr(pixels,record['target_bbox_xyxy'],record['text'])
            x,y,right,bottom = record['target_bbox_xyxy']
            ink = np.asarray(Image.open(gen.ROOT/record['target_image']))[y:bottom,x:right,0] < 25
            gray = np.asarray(Image.fromarray(pixels).convert('L'))[y:bottom,x:right]
            contrast = abs(float(gray[ink].mean())-float(gray[~ink].mean()))
            assert record['accepted_for_ocr'] == (score >= .95 and contrast >= 3), record['id']
            best.update(ocr_score=round(score,6),ocr_text=recognized,
                        stroke_contrast_gray_levels=round(contrast,6),
                        full_image_ocr_verified=True,evaluation_region_only=False)
            missing_full_checks.append(record['id'])
        record['rejection_reasons'] = []
        if best['ocr_score'] < .95:
            record['rejection_reasons'].append('ocr_score_below_0.95')
        if best['stroke_contrast_gray_levels'] < 3:
            record['rejection_reasons'].append('stroke_contrast_below_3_gray_levels')
    reproducible = []
    if args.reproduce:
        representatives = {}
        for record in records:
            c = record['configuration']
            key = (c['method'],c['profile'],c['parameters'].get('offset'))
            representatives.setdefault(key,record)
        for record in representatives.values():
            c = record['configuration']
            d,_ = gen.decoy(c['target_size'],c['background'])
            t,_,_ = gen.target(c['target_size'],c['font_size_px'],c['alignment'],c['text_id'])
            linear = gen.embed(d,t,c['method'],c['parameters'],record['seed'])
            with np.errstate(invalid='ignore'):
                pixels = gen.GENERATORS[c['method']].lin2srgb(linear).round().astype(np.uint8)
            encoded = io.BytesIO()
            Image.fromarray(pixels).save(encoded,format='PNG')
            assert hashlib.sha256(encoded.getvalue()).hexdigest() == record['sha256'], record['id']
            best = record['best_reveal']
            reduced = gen.DOWNSAMPLERS[best['backend']].downsample(pixels,(c['target_size'],)*2,best['method'])
            encoded = io.BytesIO()
            Image.fromarray(reduced).save(encoded,format='PNG')
            assert hashlib.sha256(encoded.getvalue()).hexdigest() == best['sha256'], record['id']
            score,_ = gen.ocr(reduced,record['target_bbox_xyxy'],record['text'])
            assert round(score,6) == best['ocr_score'], record['id']
            reproducible.append(record['id'])
    accepted = [r for r in records if r['accepted_for_ocr']]
    total = None
    if args.check_catalog:
        active = json.loads((gen.CATALOG/'ocr_metadata.json').read_text())
        base = json.loads((gen.CATALOG/'ocr_metadata.pre_anamorpher.json').read_text())
        assert active[:1000] == base
        assert active[1000:] == [{'image':r['image'],'text':r['text'],'category':'anamorpher'} for r in accepted]
        assert len({r['image'] for r in active}) == len(active)
        Draft202012Validator(json.loads((gen.CATALOG/'ocr_metadata.schema.json').read_text())).validate(active)
        report = json.loads((gen.CATALOG/'ocr_selection_report.json').read_text())
        refs = report['selected_references']
        old_report = json.loads((gen.CATALOG/'ocr_selection_report.pre_anamorpher.json').read_text())
        assert refs[:1000] == old_report['selected_references']
        for ref in refs[:1000]:
            assert gen.sha(gen.ROOT/ref['image']) == ref['sha256'], ref['image']
        assert [r['image'] for r in refs] == [r['image'] for r in active]
        assert report['selected_count'] == len(active)
        assert report['scope_counts'] == dict(Counter(r['scope'] for r in refs))
        assert report['quality_counts'] == dict(Counter(r['annotation']['quality'] for r in refs))
        total = len(active)
    records_hash = hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
    path = gen.CATALOG/'anamorpher_validation.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous.get('dataset_records_sha256') == records_hash:
        if not args.reproduce:
            reproducible = previous.get('byte_identical_regenerated_cases',[])
        missing_full_checks = previous.get('early_full_reveals_rechecked',[]) + missing_full_checks
    summary = {'dataset_records_sha256':records_hash,
               'generated_count':len(records),'accepted_count':len(accepted),
               'failed_controls':len(records)-len(accepted),'active_catalog_count':total,
               'rejected_reason_combinations':dict(Counter('+'.join(r['rejection_reasons']) for r in records if not r['accepted_for_ocr'])),
               'grid_complete':True,'all_image_hashes_and_dimensions_verified':True,
               'all_accepted_full_image_reveals_ocr_verified':True,
               'profile_equivalence':profile_equivalence(),
               'byte_identical_regenerated_cases':reproducible,
               'early_full_reveals_rechecked':missing_full_checks,
               'accepted_by_mode_profile':dict(Counter(f"{r['configuration']['method']}:{r['configuration']['profile']}:offset={r['configuration']['parameters'].get('offset')}" for r in accepted)),
               'limitations':['No universal native stealth certificate; no exhaustive human readability verification.',
                              'The automatic acceptance gate selects for Tesseract readability under known-region contrast normalization.',
                              '12 backend probes use padded text windows; the selected full-frame reveal is authoritative.',
                              'Normalization ignores punctuation/case for the automatic acceptance gate. Reference text preserves both.']}
    manifest['generator_script_sha256'] = gen.sha(Path(gen.__file__))
    manifest['validation']['all_full_reveals_verified'] = True
    manifest['validation']['acceptance_bias'] = 'Tesseract under known-region grayscale contrast normalization; not OCR-engine-independent.'
    gen.write_json_atomic(manifest,gen.MANIFEST)
    gen.write_json_atomic(summary,path)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('profile_equivalence','early_full_reveals_rechecked')},indent=2))


if __name__ == '__main__':
    main()
