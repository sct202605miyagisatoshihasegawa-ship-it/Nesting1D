from collections import Counter
from .models import CalculationInput, CalculationResult
from .patterns import key, order, changes
from .rules import remaining_length, used_length, remainder_class

def _fill(length, needs, sequence, trim, kerf):
    space = length-trim-kerf; cuts=[]
    total = sum((size + kerf) * needs[size] for size in sequence)
    estimated_stocks = max(1, (total + space - 1) // space)
    for size in sequence:
        balanced = (needs[size] + estimated_stocks - 1) // estimated_stocks
        count=min(needs[size], balanced, space//(size+kerf))
        cuts += [size]*count; needs[size]-=count; space-=count*(size+kerf)
    return tuple(sorted(cuts, reverse=True))

def _plan(data, sequence, remnants=True):
    c=data.cutting_conditions; needs=Counter()
    for p in data.required_parts: needs[p.length_mm]+=p.quantity
    if any(c.left_trim_mm+c.kerf_mm+x+c.kerf_mm>c.new_stock_length_mm for x in needs):
        raise ValueError("新品母材から切り出せない部材があります")
    stocks=[]; unused=[]; inv_done=Counter()
    if data.inventory and not remnants:
        unused=[{"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":r.quantity,"reason_code":"NOT_SELECTED_TO_AVOID_EXTRA_PURCHASE"} for r in sorted(data.inventory.remnants,key=lambda x:x.length_mm)]
    if data.inventory and remnants:
        for r in sorted(data.inventory.remnants,key=lambda x:x.length_mm):
            for index in range(r.quantity):
                if not sum(needs.values()):
                    unused.append({"source_type":"existing_remnant","length_mm":r.length_mm,"quantity":r.quantity-index,"reason_code":"NOT_NEEDED"})
                    break
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

def calculate(data: CalculationInput):
    sizes=tuple(sorted({p.length_mm for p in data.required_parts},reverse=True)); candidates=[]
    for seq in (sizes,tuple(reversed(sizes))):
        for use in ((True,False) if data.inventory else (False,)):
            plan=_plan(data,seq,use); stocks=plan[0]; ks=order(key(x[2]) for x in stocks)
            if data.inventory:
                c=data.cutting_conditions
                remnant_stocks=[x for x in stocks if x[0]=="existing_remnant"]
                remnant_cut_length=sum(sum(x[2]) for x in remnant_stocks)
                remnant_left=sum(remaining_length(x[1],x[2],c.left_trim_mm,c.kerf_mm) for x in remnant_stocks)
                new_left=sorted((remaining_length(x[1],x[2],c.left_trim_mm,c.kerf_mm) for x in stocks if x[0]!="existing_remnant"),reverse=True)
                positive_new_left=[x for x in new_left if x>0]
                score=(sum(x[0]=="additional_new_stock" for x in stocks),-len(remnant_stocks),-remnant_cut_length,remnant_left,len(positive_new_left),tuple(-x for x in positive_new_left),len(set(key(x[2]) for x in stocks)),changes(ks),tuple(stocks))
            else:
                score=(len(stocks),len(set(key(x[2]) for x in stocks)),changes(ks),tuple(stocks))
            candidates.append((score,plan))
    stocks,unused,inv_done=min(candidates,key=lambda x:x[0])[1]; ks=order(key(x[2]) for x in stocks); ids={k:f"P{i:02}" for i,k in enumerate(ks,1)}; counts=Counter(key(x[2]) for x in stocks); c=data.cutting_conditions
    usage=[{"source_type":t,"original_length_mm":s,"cuts":list(cuts),"pattern_id":ids[key(cuts)],"used_length_mm":used_length(cuts,c.left_trim_mm,c.kerf_mm),"remaining_length_mm":remaining_length(s,cuts,c.left_trim_mm,c.kerf_mm),"remainder_class":remainder_class(remaining_length(s,cuts,c.left_trim_mm,c.kerf_mm),c.kerf_mm)} for t,s,cuts in stocks]
    requested=Counter(); [requested.update({p.length_mm:p.quantity}) for p in data.required_parts]
    return CalculationResult(mode=data.mode,required_stock_quantity=len(stocks),additional_new_stock_required=sum(x[0]=="additional_new_stock" for x in stocks),existing_remnant_used=sum(x[0]=="existing_remnant" for x in stocks),inventory_new_stock_used=sum(x[0]=="inventory_new_stock" for x in stocks),patterns=[{"pattern_id":ids[k],"usage_count":counts[k],"parts":[{"length_mm":a,"quantity":b} for a,b in k]} for k in ks],stock_usage=usage,unused_inventory=unused,dimension_change_count=changes(ks),initial_setup_count=int(bool(ks)),machine_setting_count=int(bool(ks))+changes(ks),fulfillment=[{"length_mm":x,"required_quantity":q,"completed_from_inventory_quantity":inv_done[x],"completed_total_quantity":q,"shortage_before_purchase_quantity":q-inv_done[x],"shortage_after_purchase_quantity":0} for x,q in sorted(requested.items(),reverse=True)])
