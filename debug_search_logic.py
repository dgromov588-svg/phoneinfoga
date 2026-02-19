from perfect_search import PerfectSearch

ps = PerfectSearch()

# Тестируем номер которого нет в базе
phone = '+79991234567'
result = ps._sherlock_report_search(phone)

print(f'=== РЕЗУЛЬТАТ ПОИСКА ДЛЯ {phone} ===')
print(f'Found: {result.get("found", False)}')
print(f'Total profiles: {result.get("total_profiles", 0)}')
print(f'Sections count: {result.get("sections_count", 0)}')

# Проверяем логику
sherlock_report = result.get('report', {})
has_profiles = sherlock_report.get('total_profiles', 0) > 0
has_sections = len(sherlock_report.get('sections', [])) > 0
expected_found = has_profiles or has_sections

print(f'Has profiles: {has_profiles}')
print(f'Has sections: {has_sections}')
print(f'Expected found: {expected_found}')
