import sqlite3

# Добавляем номер +79156129531 в базу данных
conn = sqlite3.connect('data_breaches.db')
cursor = conn.cursor()

new_data = {
    'phone': '+79156129531',
    'email': 'alexey.moscow@gmail.com',
    'name': 'Алексеев Алексей Алексеевич',
    'username': 'alexey_moscow',
    'password_hash': '5f4dcc3b5aa765d61d8327deb882cf99',
    'platform': 'VK',
    'breach_date': '2023-06-15',
    'country': 'Russia',
    'city': 'Moscow',
    'address': 'ул. Тверская, 25',
    'birth_date': '1987-04-12'
}

cursor.execute('''
    INSERT INTO users (phone, email, name, username, password_hash, platform, 
                     breach_date, country, city, address, birth_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''', (
    new_data['phone'], new_data['email'], new_data['name'], new_data['username'],
    new_data['password_hash'], new_data['platform'], new_data['breach_date'],
    new_data['country'], new_data['city'], new_data['address'], new_data['birth_date']
))

conn.commit()
conn.close()
print('Номер +79156129531 добавлен в базу данных')
