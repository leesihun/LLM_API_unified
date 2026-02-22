#!/usr/bin/env python3
"""Calculate and display the result of 1007 * 1007 / 4524753"""

print("Starting calculation task...")
print("Expression: 1007 * 1007 / 4524753")
print("=" * 60)

# Step 1: Multiply 1007 * 1007
print("\n[STEP 1] Multiplication")
numerator1 = 1007
numerator2 = 1007
result1 = numerator1 * numerator2
print(f"  1007 * 1007 = {result1}")

# Step 2: Divide by 4524753
print("\n[STEP 2] Division")
denominator = 4524753
final_result = result1 / denominator
print(f"  {result1} / 4524753 = {final_result}")

# Show precision details
print("\n[PRECISION ANALYSIS]")
print(f"  Numerator: {result1}")
print(f"  Denominator: {denominator}")
print(f"  Exact result: {final_result}")
print(f"  Result rounded to 6 decimal places: {round(final_result, 6)}")
print(f"  Result as fraction: {result1}/{denominator}")

# Show percentage interpretation
print("\n[PERCENTAGE ANALYSIS]")
percentage = final_result * 100
print(f"  Result as percentage: {percentage:.6f}%")

print("=" * 60)
print(f"\nFinal result: {final_result}")
print("Calculation complete!")

print("\n=== TASK COMPLETE ===")
print("Done: Performed mathematical calculation 1007 * 1007 / 4524753")
print(f"Output: Final result = {final_result}")
print("  - Numerator: {result1} (1007 * 1007)")
print("  - Denominator: 4524753")
print("  - Percentage value: {percentage:.6f}%")
print("File: calculation2_script.py (created in working directory)")
