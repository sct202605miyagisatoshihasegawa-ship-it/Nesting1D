# Nesting1D - 切断パターン処理
# 役割: 切断パターンの正規化、実施順、および寸法変更回数を計算する。
# 更新日: 2026-08-10

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
