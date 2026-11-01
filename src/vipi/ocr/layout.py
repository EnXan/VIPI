"""Reviewed PDFMiner grouping in the readable view's coordinate frame."""

from copy import deepcopy

import cv2
import numpy as np

from ._layout_spacing import adjust
from ._layout_split import propose

LAYOUT_VERSION = "pdfminer-checkpoint1-v1"


def group_reading(step, raster, view):
    local = deepcopy(step)
    for region in local["regions"]:
        region["input_polygon"] = region["polygon"]
    groups = adjust(
        local, propose(local, cv2.cvtColor(np.asarray(raster), cv2.COLOR_RGB2BGR))
    )
    regions = []
    for group in groups:
        left, top, right, bottom = group["box"]
        polygon = [[left, top], [right, top], [right, bottom], [left, bottom]]
        regions.append(
            {
                **group,
                "polygon": polygon,
                "input_polygon": view.map_polygon(polygon),
            }
        )
    return "\n".join(group["text"] for group in groups), regions
