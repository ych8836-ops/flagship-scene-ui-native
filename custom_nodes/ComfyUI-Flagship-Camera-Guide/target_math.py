"""Framing from measured visible joints/props, not an assumed face/body ratio."""
import numpy as np


def fit_box(cx, cy, height, aspect, sw, sh):
    height = min(float(height), sh, sw / aspect)
    width = height * aspect
    left = float(np.clip(cx - width / 2, 0, sw - width))
    top = float(np.clip(cy - height / 2, 0, sh - height))
    return [left, top, width, height]


def target_boxes(targets, mode, width, height):
    sw, sh = targets['src_size']
    n = targets['frames']
    joints = np.asarray(targets['joints'], dtype=np.float64)
    person = np.asarray(targets['person_boxes'], dtype=np.float64)
    aspect = width / height
    if mode == 'medium wide shot':
        valid = np.min(joints[:, [13, 14], 2], axis=1) >= .4
        if valid.mean() < .8:raise ValueError('Knees are not visible reliably enough for a measured knees-up frame')
        top = max(0, np.quantile(person[valid, 1], .02) - sh * .015)
        knees = np.max(joints[valid][:, [13, 14], 1], axis=1)
        knee_to_hip = np.median(joints[valid][:, [13, 14], 1] - joints[valid][:, [11, 12], 1])
        bottom = min(sh, np.quantile(knees, .98) + knee_to_hip * .10)
        center_x = float(np.median(joints[valid][:, [11, 12], 0]))
        box = fit_box(center_x, (top + bottom) / 2, bottom - top, aspect, sw, sh)
        return np.tile(box, (n, 1))
    props = targets['objects']
    if props.get('name') is None:raise ValueError('No stable visible handheld prop; never invent a macro or insert target')
    boxes = np.asarray(props['boxes'], dtype=np.float64)
    valid = np.isfinite(boxes).all(axis=1)
    if valid.mean() < .8:raise ValueError('Held prop track is not reliable enough')
    left, top = np.quantile(boxes[valid, :2], .02, axis=0)
    right, bottom = np.quantile(boxes[valid, 2:], .98, axis=0)
    prop_w, prop_h = right - left, bottom - top
    if mode == 'insert shot':
        box = fit_box((left + right) / 2, (top + bottom) / 2, max(prop_h * 1.65, prop_w * 1.7 / aspect), aspect, sw, sh)
        return np.tile(box, (n, 1))
    if mode == 'macro shot':
        box = fit_box((left + right) / 2, (top + bottom) / 2, max(prop_h * 1.12, prop_w * 1.18 / aspect), aspect, sw, sh)
        return np.tile(box, (n, 1))
    raise ValueError('Unverified measured framing mode')
