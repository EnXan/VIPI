"""Vectorized execution of the vendored Anamorpher red-channel solvers.

The upstream per-block equations, linear-light conversion, mask, and null-space
bases are retained. Batching avoids millions of Python/SVD calls. Equivalence
against the original functions is checked by the dataset generator.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'datasets/external/anamorpher/backend/adversarial_generators'


def load_generator(name):
    path = UPSTREAM / f'{name}_gen_payload.py'
    spec = importlib.util.spec_from_file_location(f'anamorpher_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATORS = {name: load_generator(name) for name in ('nearest', 'bilinear', 'bicubic')}


def embed(decoy, target, method, parameters, seed):
    """Return the upstream linear-light result, batching identical edit masks."""
    height, width = target.shape[:2]
    if decoy.shape != (4 * height, 4 * width, 3):
        raise ValueError('Anamorpher requires a 4:1 source/target size ratio')
    module = GENERATORS[method]
    red = decoy[..., 0].reshape(height, 4, width, 4).transpose(0, 2, 1, 3).reshape(-1, 16).copy()
    desired = (target ** parameters['gamma'])[..., 0].reshape(-1)
    random = np.random.RandomState(seed)
    lam, eps = parameters['lam'], parameters['eps']
    if method == 'nearest':
        selected = parameters['offset'] * 5
        difference = desired.astype(np.float64) - red[:, selected].astype(np.float64)
        if lam > 0:
            shift = -difference * lam ** 2 / (1 + 15 * lam ** 2)
            red += shift[:, None]
        red[:, selected] = desired
        if eps > 0:
            one = np.zeros(16, dtype=np.float32)
            one[selected] = 1
            _, _, vh = np.linalg.svd(np.vstack([one, np.ones(16, dtype=np.float32)]), full_matrices=True)
            basis = vh[2:].astype(np.float32)
            noise = random.randn(len(red), 14).astype(np.float32)
            red += eps * (noise @ basis)
    else:
        weights = module.weight_vector(4) if method == 'bicubic' else module.weight_vector_bilinear(4)
        mask = module.bottom_luma_mask(decoy, parameters['dark_frac'])
        masks = mask.reshape(height, 4, width, 4).transpose(0, 2, 1, 3).reshape(-1, 16)
        codes = (masks.astype(np.uint16) * (1 << np.arange(16, dtype=np.uint16))).sum(axis=1).astype(np.uint16)
        current = (red * weights).sum(axis=1)
        difference = desired.astype(np.float64) - current.astype(np.float64)
        patterns = []
        dofs = np.zeros(len(red), dtype=np.int32)
        for code in np.unique(codes):
            indices = np.flatnonzero((int(code) & (1 << np.arange(16))) != 0)
            if not len(indices):
                continue
            subset = weights[indices]
            total = float(subset.sum())
            denominator = len(indices) * float(subset @ subset) + lam ** 2 - total ** 2
            if abs(denominator) < 1e-12:
                continue
            rows = np.flatnonzero(codes == code)
            coefficient = (len(indices) * subset - lam * total) / denominator
            red[np.ix_(rows, indices)] += (difference[rows, None] * coefficient).astype(np.float32)
            if eps > 0 and len(indices) >= 3:
                _, _, vh = np.linalg.svd(np.vstack([subset, np.ones_like(subset)]), full_matrices=True)
                basis = vh[2:].astype(np.float32)
                dofs[rows] = len(indices) - 2
                patterns.append((rows, indices, basis))
        if eps > 0:
            # Preserve the upstream random stream in raster/block order.
            ends = dofs.cumsum(dtype=np.int64)
            starts = ends - dofs
            noise_stream = random.randn(int(ends[-1]))
            for rows, indices, basis in patterns:
                offsets = starts[rows, None] + np.arange(len(indices) - 2)[None, :]
                noise = noise_stream[offsets] @ basis
                red[np.ix_(rows, indices)] += eps * noise.astype(np.float32)
    result = decoy.copy()
    result[..., 0] = red.reshape(height, width, 4, 4).transpose(0, 2, 1, 3).reshape(height * 4, width * 4)
    return result


def verify_equivalence():
    checks = []
    for method, module in GENERATORS.items():
        for eps in (0.0, 0.01):
            for dark_frac in (0.3, 1.0):
                for offset in (0, 1, 2, 3) if method == 'nearest' else (None,):
                    rng = np.random.RandomState(21)
                    decoy = rng.uniform(0.02, 0.2, (32, 32, 3)).astype(np.float32)
                    target = rng.uniform(0.01, 0.12, (8, 8, 3)).astype(np.float32)
                    params = {'lam':0.25, 'eps':eps, 'gamma':0.9}
                    kwargs = {'lam':0.25, 'eps':eps, 'gamma_target':0.9}
                    if method == 'nearest':
                        params['offset'] = kwargs['offset'] = offset
                        function = module.embed_nn
                    else:
                        params['dark_frac'] = kwargs['dark_frac'] = dark_frac
                        function = module.embed if method == 'bicubic' else module.embed_bilinear
                    np.random.seed(741)
                    expected = function(decoy, target, **kwargs)
                    actual = embed(decoy, target, method, params, 741)
                    error = float(np.max(np.abs(expected - actual)))
                    if error > 2e-6:
                        raise AssertionError((method, params, error))
                    checks.append({'method':method, 'parameters':params, 'max_linear_error':error})
    return checks
