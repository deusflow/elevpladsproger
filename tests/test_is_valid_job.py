import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers import is_valid_job

# Test 1: Geo filter bypass
assert is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=True) == True
# Test 2: Geo filter standard (should fail)
assert is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=False) == False
# Test 3: Support with Programming
assert is_valid_job("Datatekniker (Infrastruktur og Programmering)", "8000", "Company", "") == True
# Test 4: Support without Programming (should fail)
assert is_valid_job("Datatekniker (Infrastruktur)", "8000", "Company", "") == False

print("All tests passed!")
