from collections import Counter

def key(cuts):
    return tuple(sorted(Counter(cuts).items(), reverse=True))

def order(keys):
    remaining = set(keys)
    result = []
    while remaining:
        if not result:
            item = max(remaining)
        else:
            last = result[-1][-1][0]
            item = min(remaining, key=lambda x: (x[0][0] != last, tuple((-a, -b) for a, b in x)))
        result.append(item); remaining.remove(item)
    return result

def changes(keys):
    keys = list(keys)
    return sum(max(0, len(x)-1) for x in keys) + sum(a[-1][0] != b[0][0] for a,b in zip(keys, keys[1:]))
