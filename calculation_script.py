#!/usr/bin/env python3
"""Calculate and display the result of (100 * 0.15 + 25) / 2"""

print("Starting calculation task...")
print("Expression: (100 * 0.15 + 25) / 2")
print("-" * 50)

# Step 1: Calculate 100 * 0.15
print("\n[STEP 1] Multiplication")
factor1 = 100
factor2 = 0.15
result1 = factor1 * factor2
print(f"  100 * 0.15 = {result1}")

# Step 2: Add 25 to the result
print("\n[STEP 2] Addition")
addend = 25
result2 = result1 + addend
print(f"  {result1} + 25 = {result2}")

# Step 3: Divide by 2
print("\n[STEP 3] Division")
divisor = 2
final_result = result2 / divisor
print(f"  {result2} / 2 = {final_result}")

print("-" * 50)
print(f"\nFinal result: {final_result}")
print("Calculation complete!")

print("\n=== TASK COMPLETE ===")
print("Done: Performed mathematical calculation (100 * 0.15 + 25) / 2")
print("Output: Final result = 20.0")
print("File: calculation_script.py (created in working directory)")
