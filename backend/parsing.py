import csv
import os

input_file = 'data/media_bias_raw.txt'
output_file = 'data/media_bias.csv'

# Ensure the data directory exists
os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(input_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

header = ["News Source", "Type", "AllSides Bias Rating"]
parsed_data = []

for line in lines:
    line = line.strip()
    if not line:
        continue
    
    # Split by tab
    parts = [p.strip() for p in line.split('\t')]
    
    # Filter out duplicate header rows
    if parts[0] == "News Source" and parts[1] == "Type":
        continue
    
    # Ensure we have exactly 3 parts (sometimes trailing tabs cause empty elements)
    if len(parts) >= 3:
        parsed_data.append([parts[0], parts[1], parts[2]])
    elif len(parts) > 0:
        # Handle cases where there might be a different delimiter or issue
        parsed_data.append(parts)

# Write to CSV
with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(parsed_data)

print(f"Successfully parsed {len(parsed_data)} sources into {output_file}")