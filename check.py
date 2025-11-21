import sys
import os

import deps.repo_vdag.src
import deps.repo_vdag.src.utils
import deps.repo_vdag.src.utils.common

print("🔍 Checking sys.path entries...\n")
for i, p in enumerate(sys.path):
    print(f"{i:02d}: {p}")

print("\n📦 Attempting to import 'repo_vdag'...\n")
try:
    import deps.repo_vdag
    res = deps.repo_vdag.src.utils.common.safe_some_function(1)
    print("Result: ", res)
    print("✅ SUCCESS: 'repo_a' is importable!")
    print(f"Module file: {deps.repo_vdag.__file__}")
except ModuleNotFoundError as e:
    print("❌ ERROR: 'repo_vdag' is NOT importable.")
    print(f"Details: {e}")