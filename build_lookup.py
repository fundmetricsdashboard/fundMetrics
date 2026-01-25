from sqlalchemy import create_engine, text
import pandas as pd

# Load NAV master file (semicolon separated)
df = pd.read_csv("NAVs.txt", sep=";", skip_blank_lines=True, engine="python")
df.columns = [c.strip() for c in df.columns]
df = df[df["Scheme Name"].notna()]

# --- Filter: Only Growth options ---
mask_growth = df["Scheme Name"].str.contains("Growth", case=False, na=False)
mask_exclude = df["Scheme Name"].str.contains(
    "Bonus|Dividend|IDCW|Reinvest|Payout|Income Distribution",
    case=False,
    na=False,
)
df = df[mask_growth & ~mask_exclude]

# --- Classification rules ---
def classify(name: str):
    n = name.lower()

    # Institutional funds → always Other
    if "institutional" in n or "inst" in n:
        return "Other", "Other"

    # Commodity
    if "gold" in n and "etf" in n:
        return "Commodity", "Gold ETF"
    if "silver" in n and "etf" in n:
        return "Commodity", "Silver ETF"

    # --- Debt categorization ---
    if "banking & psu" in n:
        return "Debt", "Banking and PSU Debt"
    if "banking and psu" in n:
        return "Debt", "Banking and PSU Debt"
    if "ultra short" in n:
        return "Debt", "Short Duration"
    if "short duration" in n:
        return "Debt", "Short Duration"
    if "short term" in n:
        return "Debt", "Short Duration"
    if "medium duration" in n:
        return "Debt", "Medium Duration"
    if "medium term" in n:
        return "Debt", "Medium Duration"
    if "long duration" in n:
        return "Debt", "Long Duration"
    if "long term" in n:
        return "Debt", "Long Duration"
    if "low duration" in n:
        return "Debt", "Low Duration"
    if "dynamic bond" in n:
        return "Debt", "Dynamic Bond"
    if "corporate bond" in n:
        return "Debt", "Corporate Bond"
    if "money market" in n:
        return "Debt", "Money Market"
    if "liquid" in n:
        return "Debt", "Liquid"
    if "overnight" in n:
        return "Debt", "Overnight"
    if "gilt" in n:
        return "Debt", "Gilt"
    if "credit risk" in n:
        return "Debt", "Credit Risk"
    if "floating rate" in n:
        return "Debt", "Other"
    if "bond" in n or "securities" in n or "term" in n or "duration" in n:
        return "Debt", "Other"
    if "income fund" in n or "income opportunities" in n or "money manager" in n or "savings fund" in n or "maturity" in n:
        return "Debt", "Other"
    if "debt" in n:
        return "Debt", "Other"

    # Hybrid
    if "aggressive hybrid" in n or "hybrid aggressive" in n:
        return "Hybrid", "Aggressive"
    if "conservative hybrid" in n or "hybrid conservative" in n:
        return "Hybrid", "Conservative"
    if "balanced" in n:
        return "Hybrid", "Balanced"
    if "arbitrage" in n:
        return "Hybrid", "Arbitrage"
    if "dynamic asset" in n:
        return "Hybrid", "Dynamic Asset"
    if "hybrid" in n:
        return "Hybrid", "Other"


    # Equity
    if "large & mid cap" in n or "large and mid cap" in n:
        return "Equity", "Large & Mid Cap"
    if "large cap" in n:
        return "Equity", "Large Cap"
    if "mid cap" in n or "midcap" in n:
        return "Equity", "Mid Cap"
    if "small cap" in n or "smallcap" in n:
        return "Equity", "Small Cap"
    if "flexi" in n or "multi cap" in n or "multicap" in n:
        return "Equity", "Flexi Cap"
    if "elss" in n or "tax saver" in n:
        return "Equity", "ELSS"
    if "dividend yield" in n:
        return "Equity", "Div Yield"
    if "focused" in n:
        return "Equity", "Focused"
    if "value" in n:
        return "Equity", "Value"
    if "thematic" in n or "sector" in n or "banking & financial services" in n or "pharma" in n or "it" in n:
        return "Equity", "Thematic"
    if "equity" in n:
        return "Equity", "Other"

    # Default fallback
    return "Other", "Other"

# Apply classification
df[["Category", "Subcategory"]] = df["Scheme Name"].apply(lambda x: pd.Series(classify(x)))

# --- Extract fund_house ---
def extract_fund_house(row):   
    for col in df.columns:
        if "fund" in col.lower() or "amc" in col.lower():
            return str(row[col]).strip()

    # Otherwise, try to glean from Scheme Name
    name = row["Scheme Name"]
    tokens = name.split()
    if "Mutual Fund" in name:
        idx = name.index("Mutual Fund")
        return name[: idx + len("Mutual Fund")].strip()
    return tokens[0] + " Mutual Fund"

# Apply extraction
df["fund_house"] = df.apply(extract_fund_house, axis=1)


# Build lookup table with clean column names
lookup = df[[
    "Scheme Name",
    "ISIN Div Payout/ ISIN Growth",
    "Category",
    "Subcategory",
    "fund_house"
]].rename(
    columns={
        "Scheme Name": "name",
        "ISIN Div Payout/ ISIN Growth": "isin",
        "Category": "category",
        "Subcategory": "sub_category",
        "fund_house": "fund_house"
    }
)

# Drop rows without ISIN
lookup = lookup[lookup["isin"].notna()]

# Save only to CSV (no DB update)
lookup.to_csv("isin_lookup.csv", index=False)
print("✅ Lookup table created: isin_lookup.csv")
