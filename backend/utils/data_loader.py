"""
utils/data_loader.py
This module loads and cleans the dataset for the healthcare transparency system.
"""
import pandas as pd
#YO WWASSUP

# Function to load and clean the dataset
def load_dataset(filepath):
    """
    Loads the Excel/CSV dataset, drops rows with missing prices,
    strips spaces, fills missing locations, and converts test names to lowercase.
    """
    # Read the dataset (supports Excel and CSV)
    if filepath.endswith('.xlsx'):
        df = pd.read_excel(filepath)
    else:
        df = pd.read_csv(filepath)

    # Drop rows where price is missing
    df = df.dropna(subset=['price'])

    # Fill missing locations with 'Hyderabad'
    df['location'] = df['location'].fillna('Hyderabad')

    # Strip spaces from company name and test name
    df['company name'] = df['company name'].str.strip()
    df['test name'] = df['test name'].str.strip().str.lower()

    return df

# Function to get unique test names
def get_unique_tests(df):
    """
    Returns a list of unique test names from the dataset.
    """
    return df['test name'].unique().tolist()
