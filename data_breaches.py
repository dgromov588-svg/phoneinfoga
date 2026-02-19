#!/usr/bin/env python3
"""
Data Breaches Parser
Parse and search through leaked databases
"""

import re
import json
import requests
import hashlib
import base64
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import sqlite3
import os

class DataBreachesParser:
    def __init__(self):
        self.db_path = 'data_breaches.db'
        self.init_database()
        self.load_sample_data()
    
    def init_database(self):
        """Initialize SQLite database for storing breach data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                email TEXT,
                name TEXT,
                username TEXT,
                password_hash TEXT,
                platform TEXT,
                breach_date TEXT,
                country TEXT,
                city TEXT,
                address TEXT,
                birth_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS breaches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                date TEXT,
                records_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def load_sample_data(self):
        """Load sample leaked data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if data already exists
        cursor.execute('SELECT COUNT(*) FROM users')
        if cursor.fetchone()[0] > 0:
            conn.close()
            return
        
        # Sample leaked data (simulated)
        sample_data = [
            {
                'phone': '+380974221457',
                'email': 'user@example.com',
                'name': 'Иванов Иван Иванович',
                'username': 'ivanov_ivan',
                'password_hash': 'd41d8cd98f00b204e9800998ecf8427e',
                'platform': 'VK',
                'breach_date': '2023-01-15',
                'country': 'Ukraine',
                'city': 'Kyiv',
                'address': 'ул. Хрещатик, 1',
                'birth_date': '1990-01-01'
            },
            {
                'phone': '+79991234567',
                'email': 'petrov@gmail.com',
                'name': 'Петров Петр Петрович',
                'username': 'petr_petrov',
                'password_hash': '5f4dcc3b5aa765d61d8327deb882cf99',
                'platform': 'Telegram',
                'breach_date': '2023-02-20',
                'country': 'Russia',
                'city': 'Moscow',
                'address': 'ул. Тверская, 10',
                'birth_date': '1985-05-15'
            },
            {
                'phone': '+49123456789',
                'email': 'schmidt@yahoo.com',
                'name': 'Schmidt Hans',
                'username': 'hans_schmidt',
                'password_hash': 'e99a18c428cb38d5f260853678922e03',
                'platform': 'Facebook',
                'breach_date': '2023-03-10',
                'country': 'Germany',
                'city': 'Berlin',
                'address': 'Unter den Linden 5',
                'birth_date': '1992-08-20'
            },
            {
                'phone': '+447700900123',
                'email': 'smith@hotmail.com',
                'name': 'Smith John',
                'username': 'john_smith',
                'password_hash': 'c4ca4238a0b923820dcc509a6f75849b',
                'platform': 'Instagram',
                'breach_date': '2023-04-05',
                'country': 'UK',
                'city': 'London',
                'address': 'Baker Street 221B',
                'birth_date': '1988-12-01'
            },
            {
                'phone': '+33612345678',
                'email': 'martin@orange.fr',
                'name': 'Martin Jean',
                'username': 'jean_martin',
                'password_hash': 'eccbc87e4b5ce2fe28308fd9f2a7baf3',
                'platform': 'Twitter',
                'breach_date': '2023-05-12',
                'country': 'France',
                'city': 'Paris',
                'address': 'Champs-Élysées 1',
                'birth_date': '1995-03-25'
            }
        ]
        
        # Insert sample data
        for data in sample_data:
            cursor.execute('''
                INSERT INTO users (phone, email, name, username, password_hash, platform, 
                                 breach_date, country, city, address, birth_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['phone'], data['email'], data['name'], data['username'],
                data['password_hash'], data['platform'], data['breach_date'],
                data['country'], data['city'], data['address'], data['birth_date']
            ))
        
        # Add breach information
        breaches = [
            ('VK Database Leak 2023', 'VK user database with personal information', '2023-01-15', 1000000),
            ('Telegram Breach 2023', 'Telegram user data leak', '2023-02-20', 500000),
            ('Facebook Data Dump', 'Facebook user information leak', '2023-03-10', 2000000),
            ('Instagram Hack 2023', 'Instagram user database breach', '2023-04-05', 1500000),
            ('Twitter Leak 2023', 'Twitter user information exposure', '2023-05-12', 800000)
        ]
        
        for breach in breaches:
            cursor.execute('''
                INSERT INTO breaches (name, description, date, records_count)
                VALUES (?, ?, ?, ?)
            ''', breach)
        
        conn.commit()
        conn.close()
    
    def search_by_phone(self, phone: str) -> Dict[str, Any]:
        """Search for phone number in breach database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Normalize phone number
        normalized_phone = re.sub(r'[^\d+]', '', phone)
        
        # Search for exact match and partial match
        cursor.execute('''
            SELECT phone, email, name, username, password_hash, platform, 
                   breach_date, country, city, address, birth_date
            FROM users 
            WHERE phone = ? OR phone LIKE ? OR ? LIKE phone || '%'
        ''', (normalized_phone, f'%{normalized_phone[-10:]}', normalized_phone))
        
        results = cursor.fetchall()
        
        conn.close()
        
        if not results:
            return {
                'found': False,
                'phone': phone,
                'matches': 0,
                'data': []
            }
        
        formatted_results = []
        for row in results:
            formatted_results.append({
                'phone': row[0],
                'email': row[1],
                'name': row[2],
                'username': row[3],
                'password_hash': row[4],
                'platform': row[5],
                'breach_date': row[6],
                'country': row[7],
                'city': row[8],
                'address': row[9],
                'birth_date': row[10],
                'risk_level': self._calculate_risk_level(row)
            })
        
        return {
            'found': True,
            'phone': phone,
            'matches': len(results),
            'data': formatted_results,
            'summary': self._generate_summary(formatted_results)
        }
    
    def search_by_email(self, email: str) -> Dict[str, Any]:
        """Search for email in breach database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT phone, email, name, username, password_hash, platform, 
                   breach_date, country, city, address, birth_date
            FROM users 
            WHERE email = ? OR email LIKE ?
        ''', (email.lower(), f'%{email.lower()}%'))
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return {
                'found': False,
                'email': email,
                'matches': 0,
                'data': []
            }
        
        formatted_results = []
        for row in results:
            formatted_results.append({
                'phone': row[0],
                'email': row[1],
                'name': row[2],
                'username': row[3],
                'password_hash': row[4],
                'platform': row[5],
                'breach_date': row[6],
                'country': row[7],
                'city': row[8],
                'address': row[9],
                'birth_date': row[10],
                'risk_level': self._calculate_risk_level(row)
            })
        
        return {
            'found': True,
            'email': email,
            'matches': len(results),
            'data': formatted_results,
            'summary': self._generate_summary(formatted_results)
        }
    
    def search_by_name(self, name: str) -> Dict[str, Any]:
        """Search for name in breach database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Split name for better matching
        name_parts = name.split()
        search_conditions = []
        params = []
        
        for part in name_parts:
            search_conditions.append('name LIKE ?')
            params.append(f'%{part}%')
        
        cursor.execute(f'''
            SELECT phone, email, name, username, password_hash, platform, 
                   breach_date, country, city, address, birth_date
            FROM users 
            WHERE {' OR '.join(search_conditions)}
        ''', params)
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return {
                'found': False,
                'name': name,
                'matches': 0,
                'data': []
            }
        
        formatted_results = []
        for row in results:
            formatted_results.append({
                'phone': row[0],
                'email': row[1],
                'name': row[2],
                'username': row[3],
                'password_hash': row[4],
                'platform': row[5],
                'breach_date': row[6],
                'country': row[7],
                'city': row[8],
                'address': row[9],
                'birth_date': row[10],
                'risk_level': self._calculate_risk_level(row)
            })
        
        return {
            'found': True,
            'name': name,
            'matches': len(results),
            'data': formatted_results,
            'summary': self._generate_summary(formatted_results)
        }
    
    def search_by_username(self, username: str) -> Dict[str, Any]:
        """Search for username in breach database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT phone, email, name, username, password_hash, platform, 
                   breach_date, country, city, address, birth_date
            FROM users 
            WHERE username = ? OR username LIKE ?
        ''', (username, f'%{username}%'))
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return {
                'found': False,
                'username': username,
                'matches': 0,
                'data': []
            }
        
        formatted_results = []
        for row in results:
            formatted_results.append({
                'phone': row[0],
                'email': row[1],
                'name': row[2],
                'username': row[3],
                'password_hash': row[4],
                'platform': row[5],
                'breach_date': row[6],
                'country': row[7],
                'city': row[8],
                'address': row[9],
                'birth_date': row[10],
                'risk_level': self._calculate_risk_level(row)
            })
        
        return {
            'found': True,
            'username': username,
            'matches': len(results),
            'data': formatted_results,
            'summary': self._generate_summary(formatted_results)
        }
    
    def _calculate_risk_level(self, row: Tuple) -> str:
        """Calculate risk level based on data exposure"""
        risk_score = 0
        
        # Phone number exposure
        if row[0]:  # phone
            risk_score += 2
        
        # Email exposure
        if row[1]:  # email
            risk_score += 2
        
        # Personal information
        if row[2]:  # name
            risk_score += 1
        
        # Password hash exposure
        if row[4]:  # password_hash
            risk_score += 3
        
        # Address information
        if row[9]:  # address
            risk_score += 2
        
        # Birth date
        if row[10]:  # birth_date
            risk_score += 1
        
        if risk_score >= 8:
            return 'HIGH'
        elif risk_score >= 5:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _generate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary of breach results"""
        platforms = set()
        countries = set()
        risk_levels = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        
        for result in results:
            if result.get('platform'):
                platforms.add(result['platform'])
            if result.get('country'):
                countries.add(result['country'])
            if result.get('risk_level'):
                risk_levels[result['risk_level']] += 1
        
        return {
            'total_records': len(results),
            'platforms_affected': list(platforms),
            'countries_affected': list(countries),
            'risk_distribution': risk_levels,
            'highest_risk': max(risk_levels.keys()) if any(risk_levels.values()) else 'LOW'
        }
    
    def get_breach_statistics(self) -> Dict[str, Any]:
        """Get overall breach statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total records
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        # Platform distribution
        cursor.execute('SELECT platform, COUNT(*) FROM users GROUP BY platform')
        platform_stats = dict(cursor.fetchall())
        
        # Country distribution
        cursor.execute('SELECT country, COUNT(*) FROM users GROUP BY country')
        country_stats = dict(cursor.fetchall())
        
        # Recent breaches
        cursor.execute('SELECT name, date, records_count FROM breaches ORDER BY date DESC LIMIT 5')
        recent_breaches = [
            {'name': row[0], 'date': row[1], 'records_count': row[2]}
            for row in cursor.fetchall()
        ]
        
        conn.close()
        
        return {
            'total_records': total_users,
            'platform_distribution': platform_stats,
            'country_distribution': country_stats,
            'recent_breaches': recent_breaches,
            'database_updated': datetime.now().isoformat()
        }
    
    def add_breach_data(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Add new breach data to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        added_count = 0
        errors = []
        
        for record in data:
            try:
                cursor.execute('''
                    INSERT INTO users (phone, email, name, username, password_hash, platform, 
                                     breach_date, country, city, address, birth_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.get('phone'), record.get('email'), record.get('name'),
                    record.get('username'), record.get('password_hash'), record.get('platform'),
                    record.get('breach_date'), record.get('country'), record.get('city'),
                    record.get('address'), record.get('birth_date')
                ))
                added_count += 1
            except Exception as e:
                errors.append(str(e))
        
        conn.commit()
        conn.close()
        
        return {
            'added': added_count,
            'errors': errors,
            'total_processed': len(data)
        }
