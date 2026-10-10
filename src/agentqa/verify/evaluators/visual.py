from __future__ import annotations

import io

from agentqa.contracts.verification import AssertionSpec, Comparator, VisualExpectation
from agentqa.verify.evaluators import Outcome, SceneFacts, capability, from_bool

HANDLED = frozenset({Comparator.VISUAL_MATCH})

SUPPORTED_PROFILE = "visual/1"
PIXEL_CHANNEL_TOLERANCE = 8


def evaluate(assertion: AssertionSpec, facts: SceneFacts) -> Outcome:
    expectation = assertion.visual
    if expectation is None:
        return capability("visual_expectation_required")
    if expectation.profile_version != SUPPORTED_PROFILE:
        return capability("visual_profile_unsupported")
    baseline_bytes = facts.baseline(expectation.baseline_ref)
    observed_bytes = facts.screenshot()
    if baseline_bytes is None:
        return capability("baseline_missing")
    if observed_bytes is None:
        return capability("screenshot_missing")
    return compare(baseline_bytes, observed_bytes, expectation)


def compare(baseline_bytes: bytes, observed_bytes: bytes, expectation: VisualExpectation) -> Outcome:
    import numpy as np
    from PIL import Image

    try:
        baseline_image = Image.open(io.BytesIO(baseline_bytes)).convert("RGB")
        observed_image = Image.open(io.BytesIO(observed_bytes)).convert("RGB")
    except Exception:
        return capability("image_decode_failed")
    if baseline_image.size != observed_image.size:
        return capability("baseline_incompatible")
    baseline = np.asarray(baseline_image, dtype=np.int16)
    observed = np.asarray(observed_image, dtype=np.int16)
    height, width = baseline.shape[:2]
    mask = np.zeros((height, width), dtype=bool)
    for box in expectation.masks:
        x0 = max(0, box.x)
        y0 = max(0, box.y)
        x1 = min(width, box.x + box.width)
        y1 = min(height, box.y + box.height)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    delta = np.abs(baseline - observed).max(axis=2)
    changed = (delta > PIXEL_CHANNEL_TOLERANCE) & ~mask
    considered = int((~mask).sum())
    if considered == 0:
        return capability("mask_covers_all")
    ratio = float(changed.sum()) / float(considered)
    observed_text = f"diff_ratio={ratio:.6f};profile={expectation.profile_version}"
    return from_bool(ratio <= expectation.max_diff_ratio, observed=observed_text)
