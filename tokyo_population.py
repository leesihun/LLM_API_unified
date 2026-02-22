#!/usr/bin/env python3
"""
Tokyo Population Calculator
Calculates 15% of Tokyo's metropolitan population
"""

import sys

def calculate_tokyo_population():
    """
    Calculate 15% of Tokyo's metropolitan population.
    Tokyo metropolitan area population is approximately 14 million.
    """
    print("=" * 60)
    print("TOKYO POPULATION CALCULATOR")
    print("=" * 60)
    print()
    
    print("Step 1: Retrieving Tokyo's metropolitan population data...")
    print("Source: Latest known figure for Tokyo metropolitan area")
    print()
    
    # Tokyo metropolitan area population (latest known figure)
    tokyo_population = 14000000
    print(f"Tokyo Metropolitan Population: {tokyo_population:,} people")
    print()
    
    print("Step 2: Calculating 15% of Tokyo's population...")
    print("Calculation: 15% = 0.15")
    print("Formula: 15% × Population")
    print()
    
    percentage = 0.15
    result = tokyo_population * percentage
    
    print(f"15% of Tokyo's population calculation:")
    print(f"  {percentage} × {tokyo_population:,} = {result:,} people")
    print()
    
    print("Step 3: Presenting the final result...")
    print("-" * 60)
    print(f"Tokyo Metropolitan Population: {tokyo_population:,}")
    print(f"Percentage to Calculate:       15%")
    print(f"Result:                        {result:,}")
    print("-" * 60)
    print()
    
    print("Step 4: Breaking down the calculation...")
    print(f"One percent of Tokyo's population: {tokyo_population / 100:,}")
    print(f"Five percent of Tokyo's population: {tokyo_population / 20:,}")
    print(f"Ten percent of Tokyo's population: {tokyo_population / 10:,}")
    print(f"Fifteen percent of Tokyo's population: {result:,}")
    print()
    
    return result

def main():
    """Main execution function"""
    try:
        print("Starting Tokyo population calculation script...")
        print()
        
        result = calculate_tokyo_population()
        
        print()
        print("Step 5: Final summary...")
        print("=" * 60)
        print("TASK COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print()
        print("Summary of results:")
        print(f"  Tokyo Metropolitan Population: 14,000,000 people")
        print(f"  Percentage Calculated:          15%")
        print(f"  Final Result:                   {result:,} people")
        print()
        print("Interpretation:")
        print(f"  15% of Tokyo's metropolitan population is {result:,} people.")
        print("  This represents approximately {result/1000000:.1f} million people.")
        print()
        
        return 0
        
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())