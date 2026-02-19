from perfect_search import PerfectSearch

ps = PerfectSearch()

# Получаем результаты Sherlock
sherlock_result = ps._sherlock_report_search('+79156129531')
print('Sherlock результат напрямую:')
print(f'- Found: {sherlock_result.get("found", False)}')
print(f'- Total profiles: {sherlock_result.get("total_profiles", 0)}')

# Проверяем фильтрацию
test_results = {'sherlock_report': sherlock_result}
is_meaningful = ps._has_meaningful_results(test_results)
print(f'- Прошел фильтрацию: {is_meaningful}')

# Детальная проверка фильтрации
if isinstance(test_results, dict):
    for key, value in test_results.items():
        print(f'Key: {key}')
        if key == 'sherlock_report':
            print(f'  - Is dict: {isinstance(value, dict)}')
            print(f'  - Has found: {value.get("found", False) if isinstance(value, dict) else "N/A"}')
            print(f'  - Found value: {value.get("found", False) if isinstance(value, dict) else "N/A"}')
        else:
            print(f'  - Value type: {type(value)}')
