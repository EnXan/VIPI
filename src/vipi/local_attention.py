"""Exact causal attention in query chunks for memory-constrained MPS inference."""


def causal_attention(q, k, v, window, scale, *, query_chunk=1024):
    """Keep every key and query; bound temporary score matrices per query block.

    The 1024-query work batch matches the pinned d1 runtime's explicit-attention
    chunk. It is not a context or image limit. The full eight-image orientation
    request exceeded MPS memory on the 16 GB development Mac without chunking.

    Scores are explicit tensor operations rather than masked
    `scaled_dot_product_attention`: on MPS that kernel keeps about 1 GiB of
    driver memory for every new query/key shape, which `torch.mps.empty_cache()`
    does not release, so a folder scan ran out of memory after about a dozen
    images. Keys a block cannot see (later tokens, or outside `window`) are
    skipped; including them would only add masked zeros. Softmax runs in fp32.
    """
    import torch

    length = q.shape[-2]
    groups = q.shape[-3] // k.shape[-3]
    keys = k.repeat_interleave(groups, dim=-3)
    values = v.repeat_interleave(groups, dim=-3)
    outputs = []
    for start in range(0, length, query_chunk):
        end = min(start + query_chunk, length)
        first = 0 if window is None else max(0, start - window + 1)
        rows = torch.arange(start, end, device=q.device)[:, None]
        columns = torch.arange(first, end, device=q.device)[None, :]
        allowed = columns <= rows
        if window is not None:
            allowed = allowed & (columns > rows - window)
        scores = (q[..., start:end, :] * scale) @ keys[..., first:end, :].transpose(
            -1, -2
        )
        scores.masked_fill_(~allowed, float("-inf"))
        weights = torch.softmax(scores, dim=-1, dtype=torch.float32).to(q.dtype)
        del scores
        outputs.append(weights @ values[..., first:end, :])
    return torch.cat(outputs, dim=-2)


def serial_vision_forward(
    forward, pixel_values, spatial_shapes, pixel_attention_mask=None, **kwargs
):
    """Encode every independent image tile, one per forward pass, then rejoin."""
    import torch

    outputs = [
        forward(
            pixel_values=pixel_values[index : index + 1],
            spatial_shapes=spatial_shapes[index : index + 1],
            pixel_attention_mask=pixel_attention_mask[index : index + 1]
            if pixel_attention_mask is not None
            else None,
            **kwargs,
        )
        for index in range(pixel_values.shape[0])
    ]
    first = outputs[0]
    return type(first)(
        last_hidden_state=torch.cat([output.last_hidden_state for output in outputs]),
        pooler_output=torch.cat([output.pooler_output for output in outputs])
        if first.pooler_output is not None
        else None,
        hidden_states=tuple(
            torch.cat([output.hidden_states[layer] for output in outputs])
            for layer in range(len(first.hidden_states))
        )
        if first.hidden_states is not None
        else None,
        attentions=tuple(
            torch.cat([output.attentions[layer] for output in outputs])
            for layer in range(len(first.attentions))
        )
        if first.attentions is not None
        else None,
    )
