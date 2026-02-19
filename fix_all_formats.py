#!/usr/bin/env python3

# Read the file
with open('enhanced_universal_search.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all incorrect NumberFormat references with PhoneNumberFormat
content = content.replace('NumberFormat.INTERNATIONAL', 'PhoneNumberFormat.INTERNATIONAL')
content = content.replace('NumberFormat.NATIONAL', 'PhoneNumberFormat.NATIONAL')
content = content.replace('NumberFormat.E164', 'PhoneNumberFormat.E164')

# Write back to file
with open('enhanced_universal_search.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed all NumberFormat references to PhoneNumberFormat")
