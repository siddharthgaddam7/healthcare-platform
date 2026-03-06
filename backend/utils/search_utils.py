"""
utils/search_utils.py
This module handles fuzzy matching for user queries using RapidFuzz.
"""
from rapidfuzz import process

# Function to find the best matching test name
def fuzzy_match(query, test_names):
    """
    Uses RapidFuzz to find the closest test name to the user's query.
    Returns the best match and its score.
    """
    # Convert query to lowercase for matching
    query = query.lower()
    # Use RapidFuzz to get the best match
    match, score, _ = process.extractOne(query, test_names)
    return match, score
