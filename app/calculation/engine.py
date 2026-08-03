from collections import Counter
from .models import CalculationInput, CalculationResult
from .patterns import key, order, changes
from .rules import remaining_length, used_length, remainder_class
from .selection import SelectionCandidate, select_candidate

def _fill(length, needs, sequence, trim, kerf):
    space = length-trim-kerf; cuts=[]
    total = sum((size + kerf) * needs[size] for size in sequence)
    estimated_stocks = max(1, (total + space - 1) // space)
    for size in sequence:
        balanced = (needs[size] + estimated_stocks - 1) // estimated_stocks
        count=min(needs[size], balanced, space//(size+kerf))
        cuts += [size]*count; needs[size]-=count; space-=count*(size+kerf)
    return tuple(sorted(cuts, reverse=True))

def _unused_remnant_reason(length, needs, trim, kerf):
    if not sum(needs.values()):
        return "NOT_NEEDED"
    if not any(
        quantity and trim + kerf + size + kerf <= length
        for size, quantity in needs.items()
    ):
        return "NO_REQUIRED_PART_FITS_AFTER_TRIM"
    return None

def _plan(data, sequence, remnants=True):
    c=data.cutting_conditions; needs=Counter()
    for p in data.required_parts: needs[p.length_mm]+=p.quantity
    if any(c.left_trim_mm+c.kerf_mm+x+c.kerf_mm>c.new_stock_length_mm for x in needs):
        raise ValueError("新品母材から切り出せない部材があります")
    stocks=[]; unused=[]; inv_done=Counter()
    if data.inventory and not remnants:
        for r in sorted(data.inventory.remnants,key=lambda x:x.length_mm):
            reason = _unused_remnant_reason(
                r.length_mm, needs, c.left_trim_mm, c.kerf_mm
            ) or "NOT_SELECTED_BY_CANDIDATE_SELECTION"
            unused.append({"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":r.quantity,"reason_code":reason})
    if data.inventory and remnants:
        for r in sorted(data.inventory.remnants,key=lambda x:x.length_mm):
            for index in range(r.quantity):
                reason = _unused_remnant_reason(
                    r.length_mm, needs, c.left_trim_mm, c.kerf_mm
                )
                if reason == "NOT_NEEDED":
                    unused.append({"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":r.quantity-index,"reason_code":reason})
                    break
                if reason:
                    unused.append({"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":1,"reason_code":reason})
                    continue
                cuts=_fill(r.length_mm,needs,sequence,c.left_trim_mm,c.kerf_mm)
                if cuts: stocks.append(("existing_remnant",r.length_mm,cuts))
                else: unused.append({"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":1,"reason_code":"NO_REQUIRED_PART_FITS_AFTER_TRIM"})
    if data.inventory:
        for index in range(data.inventory.new_stock_quantity):
            if not sum(needs.values()):
                unused.append({"source_type":"held_new_stock","length_mm":c.new_stock_length_mm,"quantity":data.inventory.new_stock_quantity-index,"reason_code":"NOT_NEEDED"})
                break
            cuts=_fill(c.new_stock_length_mm,needs,sequence,c.left_trim_mm,c.kerf_mm)
            if cuts: stocks.append(("inventory_new_stock",c.new_stock_length_mm,cuts))
        original=Counter(); [original.update({p.length_mm:p.quantity}) for p in data.required_parts]; inv_done=original-needs
    while sum(needs.values()):
        cuts=_fill(c.new_stock_length_mm,needs,sequence,c.left_trim_mm,c.kerf_mm)
        stocks.append(("additional_new_stock",c.new_stock_length_mm,cuts))
    return stocks,unused,inv_done

def _build_selection_candidate(data: CalculationInput, plan) -> SelectionCandidate:
    raw_stocks, raw_unused, raw_inventory_completed = plan
    conditions = data.cutting_conditions
    stocks = []
    completed = Counter()
    waste_length_mm = 0
    remnant_length_mm = 0
    remnant_count = 0

    for source_type, original_length_mm, raw_cuts in raw_stocks:
        cuts = tuple(raw_cuts)
        remaining = remaining_length(
            original_length_mm,
            cuts,
            conditions.left_trim_mm,
            conditions.kerf_mm,
        )
        classification = remainder_class(remaining)
        if classification == "scrap":
            waste_length_mm += remaining
        elif classification == "remnant":
            remnant_length_mm += remaining
            remnant_count += 1
        stocks.append((source_type, original_length_mm, cuts, remaining))
        completed.update(cuts)

    requested = Counter()
    for part in data.required_parts:
        requested[part.length_mm] += part.quantity
    pattern_keys = tuple(key(stock[2]) for stock in stocks)

    return SelectionCandidate(
        stocks=tuple(stocks),
        unused=tuple(dict(item) for item in raw_unused),
        inventory_completed=tuple(
            sorted(raw_inventory_completed.items(), reverse=True)
        ),
        fully_satisfied=all(
            completed[length_mm] >= quantity
            for length_mm, quantity in requested.items()
        ),
        additional_new_stock_count=sum(
            stock[0] == "additional_new_stock" for stock in stocks
        ),
        waste_length_mm=waste_length_mm,
        remnant_length_mm=remnant_length_mm,
        remnant_count=remnant_count,
        pattern_count=len(set(pattern_keys)),
        dimension_change_count=changes(order(pattern_keys)),
    )

def _build_selection_candidates(
    data: CalculationInput,
) -> tuple[SelectionCandidate, ...]:
    sizes = tuple(
        sorted({part.length_mm for part in data.required_parts}, reverse=True)
    )
    sequences = (sizes, tuple(reversed(sizes)))
    remnant_options = (True, False) if data.inventory else (False,)
    return tuple(
        _build_selection_candidate(data, _plan(data, sequence, use_remnants))
        for sequence in sequences
        for use_remnants in remnant_options
    )

def calculate(data: CalculationInput):
    selected = select_candidate(_build_selection_candidates(data))
    stocks = tuple(
        (source_type, original_length_mm, cuts)
        for source_type, original_length_mm, cuts, _ in selected.stocks
    )
    unused = [dict(item) for item in selected.unused]
    inv_done = Counter(dict(selected.inventory_completed))
    ks=order(key(x[2]) for x in stocks); ids={k:f"P{i:02}" for i,k in enumerate(ks,1)}; counts=Counter(key(x[2]) for x in stocks); c=data.cutting_conditions
    usage=[{"source_type":t,"original_length_mm":s,"cuts":list(cuts),"pattern_id":ids[key(cuts)],"used_length_mm":used_length(cuts,c.left_trim_mm,c.kerf_mm),"remaining_length_mm":remaining,"remainder_class":remainder_class(remaining)} for t,s,cuts,remaining in selected.stocks]
    requested=Counter(); [requested.update({p.length_mm:p.quantity}) for p in data.required_parts]
    return CalculationResult(mode=data.mode,required_stock_quantity=len(stocks),additional_new_stock_required=selected.additional_new_stock_count,existing_remnant_used=sum(x[0]=="existing_remnant" for x in stocks),inventory_new_stock_used=sum(x[0]=="inventory_new_stock" for x in stocks),patterns=[{"pattern_id":ids[k],"usage_count":counts[k],"parts":[{"length_mm":a,"quantity":b} for a,b in k]} for k in ks],stock_usage=usage,unused_inventory=unused,dimension_change_count=selected.dimension_change_count,initial_setup_count=int(bool(ks)),machine_setting_count=int(bool(ks))+selected.dimension_change_count,fulfillment=[{"length_mm":x,"required_quantity":q,"completed_from_inventory_quantity":inv_done[x],"completed_total_quantity":q,"shortage_before_purchase_quantity":q-inv_done[x],"shortage_after_purchase_quantity":0} for x,q in sorted(requested.items(),reverse=True)])
