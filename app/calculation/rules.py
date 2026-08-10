# Nesting1D - 切断長と残材分類ルール
# 役割: 使用長、残り長さ、および使い切り・廃棄材・残材の分類を計算する。
# 更新日: 2026-08-10

def used_length(cuts, trim, kerf):
    return trim + kerf + sum(x + kerf for x in cuts)

def remaining_length(stock, cuts, trim, kerf):
    return stock - used_length(cuts, trim, kerf)

def remainder_class(remaining):
    if remaining == 0:
        return "used_up"
    return "scrap" if remaining <= 50 else "remnant"
