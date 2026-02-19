#!/usr/bin/env python3

# Read the file
with open('enhanced_universal_search.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the incorrect class name
content = content.replace('PhonePhoneNumberFormat', 'PhoneNumberFormat')

# Write back to file
with open('enhanced_universal_search.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed PhonePhoneNumberFormat to PhoneNumberFormat")
