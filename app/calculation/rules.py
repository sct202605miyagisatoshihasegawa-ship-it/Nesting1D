def used_length(cuts, trim, kerf):
    return trim + kerf + sum(x + kerf for x in cuts)

def remaining_length(stock, cuts, trim, kerf):
    return stock - used_length(cuts, trim, kerf)

def remainder_class(remaining, kerf):
    if remaining == 0:
        return "used_up"
    return "scrap" if remaining <= 50 + kerf else "remnant"
