def process_data(data):
    # This will cause an IndexError because the list is too short!
    return data[10]

print("Processing...")
print(process_data([1, 2, 3]))
