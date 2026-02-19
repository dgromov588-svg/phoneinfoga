from sherlock_report import SherlockReportGenerator

sherlock = SherlockReportGenerator()

# Тестируем номер которого нет в базе
phone = '+79991234567'
report = sherlock.generate_sherlock_report(phone)

print(f'=== ОТЧЕТ ДЛЯ НОМЕРА {phone} ===')
print(f'Total profiles: {report["total_profiles"]}')
print(f'Total sources: {report["total_sources"]}')
print(f'Sections count: {len(report["sections"])}')

print('\nРазделы:')
for i, section in enumerate(report['sections']):
    print(f'{i+1}. {section["title"]} - {len(section["content"])} элементов')

print('\nОбщая сводка:')
for key, value in report['general_summary'].items():
    if value:
        print(f'{key}: {value}')
