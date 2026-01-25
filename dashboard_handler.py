from utils import calculate_xirr, calculate_ytd, calculate_cagr

def calculate_metrics(investments):
    total_investment = sum(inv.amount for inv in investments)
    current_value = sum(inv.current_value for inv in investments)
    xirr = calculate_xirr(investments)
    ytd = calculate_ytd(investments)
    cagr = calculate_cagr(investments)
    return {
        'total_investment': total_investment,
        'current_value': current_value,
        'xirr': xirr,
        'ytd': ytd,
        'cagr': cagr
    }
