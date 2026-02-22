# Task: Calculate 11.951 divided by 3.751 and return the result with 4 decimal places

print('=== TASK: Calculate 11.951 / 3.751 ===')
print()
print('Starting calculation script...')
print()

# Step 1: Define the input values
print('Step 1: Defining input values')
numerator = 11.951
denominator = 3.751
print(f'  Numerator: {numerator}')
print(f'  Denominator: {denominator}')
print()

# Step 2: Perform the division operation
print('Step 2: Performing division operation')
print('  Operation: numerator / denominator')
result = numerator / denominator
print(f'  Result: {result}')
print()

# Step 3: Format the result to 4 decimal places
print('Step 3: Formatting result to 4 decimal places')
formatted_result = "{:.4f}".format(result)
print(f'  Formatted result: {formatted_result}')
print()

# Step 4: Display the calculation details
print('Step 4: Calculation details')
print('  Original calculation: 11.951 ÷ 3.751')
print(f'  Decimal precision: {len(str(result).split(".")[1])} decimal places')
print(f'  Required precision: 4 decimal places')
print()

# Step 5: Store result for potential further processing
print('Step 5: Storing final result')
final_result = formatted_result
print(f'  Stored in variable: final_result = "{final_result}"')
print()

# Step 6: Display complete summary
print('Step 6: Final summary')
print(f'  ========================================')
print(f'  QUANTITATIVE RESULT: {final_result}')
print(f'  ========================================')
print()

print('=== CALCULATION COMPLETE ===')
print('Done: Performed division of 11.951 by 3.751')
print(f'Output: Result formatted to 4 decimal places = {final_result}')
