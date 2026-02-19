import sqlite3

conn = sqlite3.connect('data_breaches.db')
cursor = conn.cursor()

# Поиск номера в базе
cursor.execute('SELECT phone, name, email, platform FROM users WHERE phone LIKE "%9156129531%" OR phone LIKE "%79156129531%"')
results = cursor.fetchall()

print('=== ПРЯМОЙ ПОИСК В БАЗЕ ДАННЫХ ===')
if results:
    for row in results:
        print(f'Phone: {row[0]}, Name: {row[1]}, Email: {row[2]}, Platform: {row[3]}')
else:
    print('Номер не найден в базе данных')

# Вывод всех номеров в базе для проверки
cursor.execute('SELECT phone, name, platform FROM users')
all_results = cursor.fetchall()
print('\n=== ВСЕ НОМЕРА В БАЗЕ ===')
for row in all_results:
    print(f'Phone: {row[0]}, Name: {row[1]}, Platform: {row[2]}')

conn.close()
