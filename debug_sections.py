from sherlock_report import SherlockReportGenerator

sherlock = SherlockReportGenerator()

# Тестируем номер которого нет в базе
phone = '+79991234567'
report = sherlock.generate_sherlock_report(phone)

print(f'=== ОТЧЕТ ДЛЯ НОМЕРА {phone} ===')
print(f'Total profiles: {report["total_profiles"]}')
print(f'Total sources: {report["total_sources"]}')
print(f'Sections count: {len(report["sections"])}')
print(f'Has profiles: {report["total_profiles"] > 0}')
print(f'Has sections: {len(report["sections"]) > 0}')
print(f'Found condition: {report["total_profiles"] > 0 or len(report["sections"]) > 0}')
