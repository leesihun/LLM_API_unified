population = 14000000
result = population * 0.15
print(f"15% of {population:,} = {result:,.0f}")

# Also show for a range
for pop in [13900000, 14000000, 14100000]:
    print(f"15% of {pop:,} = {pop * 0.15:,.0f}")