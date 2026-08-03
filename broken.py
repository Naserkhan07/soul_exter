def calculate_total(prices):
    total = 0
    for p in prices:
        total += p
    return total

print("The total is:", calculate_total([10, 20, 30]))
