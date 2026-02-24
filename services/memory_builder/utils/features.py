def safe_div(a, b, default=0.0):
    try:
        if b in (0, None):
            return default
        return float(a) / float(b)
    except Exception:
        return default

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

def fatigue_from_ratios(ctr_ratio: float, roas_ratio: float):
    # Weight CTR more than ROAS for fatigue (thumbstop proxy)
    score = 0.65 * (1 - clamp(ctr_ratio, 0.0, 2.0)) + 0.35 * (1 - clamp(roas_ratio, 0.0, 2.0))
    flag = (ctr_ratio < 0.7) or (score > 0.45)
    return score, flag