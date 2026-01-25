import pandas as pd

def parse_excel(filepath):
    df = pd.read_excel(filepath)
    # Add validation or transformation logic here
    return df
