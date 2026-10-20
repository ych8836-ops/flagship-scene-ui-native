"""Shared camera-only timing; performer timing stays unchanged."""
import numpy as np


def camera_progress(fraction, speed='slow', easing='linear'):
    scale={'very slow':.5,'slow':1.,'moderate':1.35,'fast':1.75,'very fast':2.3}[speed]
    t=float(np.clip(fraction*scale,0,1))
    if easing=='ease in':return t*t
    if easing=='ease out':return 1-(1-t)**2
    if easing=='ease in out':return t*t*(3-2*t)
    if easing=='snap settle':
        t=min(1.,t*4);return t*t*(3-2*t)
    return t
