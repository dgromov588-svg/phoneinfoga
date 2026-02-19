#!/usr/bin/env python3
"""
Enhanced Universal Search System
Comprehensive OSINT tool with security, performance, and reliability improvements
"""

import os
import base64
import hashlib
import json
import requests
import requests
import json
import time
import hashlib
import hmac
import base64
import re
import logging
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import quote, urlencode
from pathlib import Path

from flask import Flask, render_template, request, jsonify, g
from werkzeug.utils import secure_filename
from PIL import Image, ExifTags
from phonenumbers import parse, NumberParseException, is_valid_number, geocoder, carrier
from phonenumbers.phonenumberutil import NumberFormat, PhoneNumberFormat
import phonenumbers
import uuid

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('universal_search.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    UPLOAD_FOLDER = 'uploads'
    CACHE_TTL = 3600  # 1 hour
    RATE_LIMIT_REQUESTS = 100
    RATE_LIMIT_WINDOW = 3600  # 1 hour
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
    ALLOWED_MIME_TYPES = {
        'image/png', 'image/jpeg', 'image/jpg', 'image/gif', 
        'image/bmp', 'image/webp'
    }
    MAX_IMAGE_DIMENSION = 10000  # pixels
    MIN_IMAGE_DIMENSION = 10  # pixels

# Input validation
class InputValidator:
    """Comprehensive input validation utilities"""
    
    @staticmethod
    def validate_phone_number(phone: str) -> Tuple[bool, str, Optional[str]]:
        """Validate phone number format"""
        if not phone or not isinstance(phone, str):
            return False, "Phone number is required", None
        
        # Remove common formatting
        cleaned = re.sub(r'[^\d+]', '', phone.strip())
        
        if len(cleaned) < 7 or len(cleaned) > 15:
            return False, "Phone number must be 7-15 digits", None
        
        # Check for valid international format
        if not cleaned.startswith('+'):
            return False, "Phone number must include country code", None
        
        try:
            parsed = parse(cleaned, None)
            if is_valid_number(parsed):
                formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                return True, "Valid phone number", formatted
        except NumberParseException as e:
            logger.warning(f"Phone validation failed: {e}")
            return False, f"Invalid phone format: {str(e)}", None
        
        return False, "Invalid phone number", None
    
    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        """Validate username format"""
        if not username or not isinstance(username, str):
            return False, "Username is required"
        
        # Remove @ prefix if present
        clean_username = username.lstrip('@')
        
        # Check length (Telegram usernames are 5-32 characters)
        if len(clean_username) < 5 or len(clean_username) > 32:
            return False, "Username must be 5-32 characters long"
        
        # Check valid characters (letters, numbers, underscores)
        if not re.match(r'^[a-zA-Z0-9_]+$', clean_username):
            return False, "Username can only contain letters, numbers, and underscores"
        
        # Cannot start with underscore
        if clean_username.startswith('_'):
            return False, "Username cannot start with underscore"
        
        return True, clean_username
    
    @staticmethod
    def validate_fio(fio: str) -> Tuple[bool, str]:
        """Validate FIO format"""
        if not fio or not isinstance(fio, str):
            return False, "FIO is required"
        
        # Remove extra spaces
        clean_fio = ' '.join(fio.split())
        
        # Check if it contains at least 2 words (name + surname)
        words = clean_fio.split()
        if len(words) < 2:
            return False, "FIO must contain at least name and surname"
        
        # Check length (reasonable limits)
        if len(clean_fio) < 3 or len(clean_fio) > 100:
            return False, "FIO length must be 3-100 characters"
        
        # Check for valid characters (Cyrillic and Latin letters, hyphens, spaces)
        if not re.match(r'^[a-zA-Zа-яА-ЯёЁ\-\s]+$', clean_fio):
            return False, "FIO can only contain letters, hyphens, and spaces"
        
        return True, clean_fio
    
    @staticmethod
    def validate_birth_date(birth_date: str) -> Tuple[bool, str]:
        """Validate birth date format"""
        if not birth_date or not isinstance(birth_date, str):
            return False, "Birth date is required"
        
        # Try different date formats
        date_formats = [
            '%d.%m.%Y',  # DD.MM.YYYY
            '%d-%m-%Y',  # DD-MM-YYYY
            '%d/%m/%Y',  # DD/MM/YYYY
            '%Y-%m-%d',  # YYYY-MM-DD
            '%Y.%m.%d',  # YYYY.MM.DD
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(birth_date, fmt)
                # Return in standard format
                return True, parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        return False, "Invalid date format. Use DD.MM.YYYY, DD-MM-YYYY, or YYYY-MM-DD"
    
    @staticmethod
    def validate_search_types(search_types: List[str]) -> Tuple[bool, str]:
        if not search_types:
            return False, "At least one search type must be specified"
        
        valid_types = {
            'basic', 'search_engines', 'social', 'api', 'all',
            'metadata', 'facial', 'face', 'fssp', 'reverse_lookup', 'databases', 'shodan', 'rosselhozbank', 'owlsint'
        }
        
        invalid_types = [t for t in search_types if t not in valid_types]
        if invalid_types:
            return False, f"Invalid search types: {', '.join(invalid_types)}"
        
        return True, "Valid search types"
    
    @staticmethod
    def validate_file(file) -> Tuple[bool, str, Dict[str, Any]]:
        """Comprehensive file validation"""
        if not file:
            return False, "No file provided", {}
        
        # Check filename
        if not file.filename:
            return False, "No filename provided", {}
        
        filename = secure_filename(file.filename)
        if not filename:
            return False, "Invalid filename", {}
        
        # Check file extension
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if ext not in Config.ALLOWED_EXTENSIONS:
            return False, f"File type .{ext} not allowed", {}
        
        # Check MIME type
        if file.mimetype not in Config.ALLOWED_MIME_TYPES:
            return False, f"MIME type {file.mimetype} not allowed", {}
        
        # Check file size
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size > Config.MAX_CONTENT_LENGTH:
            return False, f"File size {size} exceeds limit {Config.MAX_CONTENT_LENGTH}", {}
        
        # Validate image content
        try:
            img = Image.open(file.stream)
            img.verify()  # Verify it's a valid image
            file.seek(0)
            
            # Check image dimensions
            img = Image.open(file.stream)
            width, height = img.size
            
            if (width < Config.MIN_IMAGE_DIMENSION or 
                height < Config.MIN_IMAGE_DIMENSION or
                width > Config.MAX_IMAGE_DIMENSION or 
                height > Config.MAX_IMAGE_DIMENSION):
                return False, f"Image dimensions {width}x{height} out of bounds", {}
            
            file.seek(0)
            
            return True, "Valid file", {
                'filename': filename,
                'size': size,
                'width': width,
                'height': height,
                'format': img.format,
                'mime_type': file.mimetype
            }
            
        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return False, f"Invalid image file: {str(e)}", {}

# Rate limiting
class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = {}
    
    def is_allowed(self, key: str, limit: int = None, window: int = None) -> Tuple[bool, Dict[str, Any]]:
        """Check if request is allowed"""
        limit = limit or Config.RATE_LIMIT_REQUESTS
        window = window or Config.RATE_LIMIT_WINDOW
        
        now = time.time()
        
        if key not in self.requests:
            self.requests[key] = []
        
        # Clean old requests
        self.requests[key] = [req_time for req_time in self.requests[key] 
                             if now - req_time < window]
        
        # Check limit
        if len(self.requests[key]) >= limit:
            return False, {
                'allowed': False,
                'limit': limit,
                'remaining': 0,
                'reset_time': now + window
            }
        
        # Add current request
        self.requests[key].append(now)
        
        return True, {
            'allowed': True,
            'limit': limit,
            'remaining': limit - len(self.requests[key]),
            'reset_time': now + window
        }

# Caching
class CacheManager:
    """Simple in-memory cache with TTL"""
    
    def __init__(self):
        self.cache = {}
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached item"""
        if key in self.cache:
            item = self.cache[key]
            if time.time() - item['timestamp'] < Config.CACHE_TTL:
                logger.info(f"Cache hit for key: {key}")
                return item['data']
            else:
                del self.cache[key]
                logger.info(f"Cache expired for key: {key}")
        return None
    
    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Set cached item"""
        self.cache[key] = {
            'data': data,
            'timestamp': time.time()
        }
        logger.info(f"Cached data for key: {key}")
    
    def clear(self) -> None:
        """Clear all cache"""
        self.cache.clear()
        logger.info("Cache cleared")
    
    def cleanup(self) -> None:
        """Clean expired items"""
        now = time.time()
        expired_keys = []
        
        for key, item in self.cache.items():
            if now - item['timestamp'] >= Config.CACHE_TTL:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.info(f"Cleaned {len(expired_keys)} expired cache items")

# Error handling
class SearchError(Exception):
    """Custom exception for search errors"""
    pass

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

# Enhanced Universal Search System
class EnhancedUniversalSearchSystem:
    """Enhanced OSINT search system with security and performance improvements"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Initialize components
        self.validator = InputValidator()
        self.rate_limiter = RateLimiter()
        self.cache = CacheManager()
        
        # Create upload folder
        Path(Config.UPLOAD_FOLDER).mkdir(exist_ok=True)
        
        # Search engines (same as before)
        self.phone_search_engines = {
            'google': self._google_phone_search,
            'bing': self._bing_phone_search,
            'duckduckgo': self._duckduckgo_phone_search,
            'yandex': self._yandex_phone_search,
            'baidu': self._baidu_phone_search,
            'yahoo': self._yahoo_phone_search,
            'ask': self._ask_phone_search,
            'startpage': self._startpage_phone_search
        }
        
        self.social_platforms = {
            'facebook': self._facebook_search,
            'instagram': self._instagram_search,
            'twitter': self._twitter_search,
            'linkedin': self._linkedin_search,
            'telegram': self._telegram_search,
            'telegram_username': self._telegram_username_search,
            'whatsapp': self._whatsapp_search,
            'vk': self._vk_search,
            'ok': self._ok_search,
            'tiktok': self._tiktok_search,
            'youtube': self._youtube_search,
            'reddit': self._reddit_search,
            'pinterest': self._pinterest_search,
            'snapchat': self._snapchat_search,
            'discord': self._discord_search
        }
        
        self.photo_search_engines = {
            'google': self._google_photo_search,
            'yandex': self._yandex_photo_search,
            'bing': self._bing_photo_search,
            'tineye': self._tineye_search,
            'baidu': self._baidu_photo_search,
            'sogou': self._sogou_photo_search,
            'yandex_reverse': self._yandex_reverse_search,
            'iqdb': self._iqdb_search,
            'saucenao': self._saucenao_search
        }
        
        self.facial_services = {
            'face_recognition': self._face_recognition_analysis,
            'facepp': self._facepp_analysis,
            'kairos': self._kairos_analysis,
            'amazon_rekognition': self._amazon_rekognition_analysis,
            'azure_face': self._azure_face_analysis,
            'google_vision': self._google_vision_analysis
        }
        
        self.api_services = {
            'numverify': self._numverify_api,
            'abstract_api': self._abstract_api,
            'ipapi': self._ipapi_lookup,
            'twilio': self._twilio_lookup,
            'infobel': self._infobel_lookup,
            'globalphone': self._globalphone_lookup
        }
    
    def _get_client_ip(self) -> str:
        """Get client IP address"""
        if request.environ.get('HTTP_X_FORWARDED_FOR'):
            return request.environ['HTTP_X_FORWARDED_FOR'].split(',')[0].strip()
        return request.environ.get('REMOTE_ADDR', 'unknown')
    
    def _check_rate_limit(self) -> None:
        """Check rate limit for current request"""
        client_ip = self._get_client_ip()
        allowed, info = self.rate_limiter.is_allowed(client_ip)
        
        if not allowed:
            raise ValidationError(f"Rate limit exceeded. Try again later.")
        
        g.rate_limit_info = info
    
    def _generate_cache_key(self, search_type: str, query: str, params: List[str]) -> str:
        """Generate cache key"""
        key_data = f"{search_type}:{query}:{':'.join(sorted(params))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def universal_telegram_username_search(self, username: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Search for phone number by Telegram username"""
        try:
            # Validate username
            is_valid, message = self.validator.validate_username(username)
            if not is_valid:
                raise ValidationError(message)
            
            clean_username = message  # The cleaned username from validation
            
            # Validate search types
            if search_types is None:
                search_types = ['social']
            
            is_valid, message = self.validator.validate_search_types(search_types)
            if not is_valid:
                raise ValidationError(message)
            
            # Check cache
            cache_key = self._generate_cache_key('telegram_username', clean_username, search_types)
            cached_result = self.cache.get(cache_key)
            if cached_result:
                cached_result['cached'] = True
                return cached_result
            
            # Perform search
            result = {
                'input': username,
                'cleaned_username': clean_username,
                'valid': True,
                'search_types': search_types,
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'results': {}
            }
            
            # Social platforms search
            if 'social' in search_types or 'all' in search_types:
                result['results']['social_platforms'] = {}
                result['results']['social_platforms']['telegram_username'] = self._telegram_username_search(clean_username)
            
            # Add cross-platform search
            if 'search_engines' in search_types or 'all' in search_types:
                result['results']['search_engines'] = {
                    'google_username': {
                        'engine': 'Google Username Search',
                        'search_url': f'https://www.google.com/search?q={quote(clean_username)}',
                        'queries': [
                            f'"{clean_username}" phone OR contact',
                            f'"{clean_username}" telegram',
                            f'@{clean_username} номер телефона'
                        ]
                    },
                    'bing_username': {
                        'engine': 'Bing Username Search',
                        'search_url': f'https://www.bing.com/search?q={quote(clean_username)}',
                        'queries': [
                            f'"{clean_username}" contact me',
                            f'"{clean_username}" phone number'
                        ]
                    }
                }
            
            # Cache result
            self.cache.set(cache_key, result)
            
            return result
            
        except ValidationError as e:
            logger.warning(f"Validation error in telegram username search: {e}")
            return {
                'error': str(e),
                'error_type': 'validation',
                'input': username,
                'valid': False
            }
        except Exception as e:
            logger.error(f"Unexpected error in telegram username search: {e}")
            return {
                'error': 'Internal server error',
                'error_type': 'internal',
                'input': username
            }
    
    def _has_meaningful_results(self, results: Dict[str, Any]) -> bool:
        """Check if search results contain meaningful information"""
        if not isinstance(results, dict):
            return False
            
        # Check for actual data (not just URLs or error messages)
        for key, value in results.items():
            if key == 'basic':
                # Basic info is always meaningful if valid
                if isinstance(value, dict) and value.get('valid', False):
                    return True
                    
            elif key == 'search_engines':
                # Search engines always provide URLs (meaningful)
                return True
                
            elif key == 'social_platforms':
                # Social platforms always provide URLs (meaningful)
                return True
                
            elif key == 'shodan':
                # Check if Shodan found actual data
                if isinstance(value, dict):
                    queries = value.get('search_queries', [])
                    for query in queries:
                        if query.get('success') and query.get('response'):
                            # Check if response has actual data
                            response = query.get('response', {})
                            if response.get('total', 0) > 0 or response.get('matches'):
                                return True
                                
            elif key == 'financial_services':
                # Check financial services for actual account data
                if isinstance(value, dict):
                    rosselhozbank = value.get('rosselhozbank', {})
                    if rosselhozbank.get('success') and rosselhozbank.get('response'):
                        return True
                        
            elif key == 'advanced_tracking':
                # Check Owl-sint for actual tracking data
                if isinstance(value, dict):
                    owlsint = value.get('owlsint', {})
                    if owlsint.get('success'):
                        # Check if we have meaningful phone data
                        tracking_methods = owlsint.get('tracking_methods', [])
                        for method in tracking_methods:
                            if method.get('valid_number') or method.get('location'):
                                return True
                                
            elif key == 'government_services':
                # Check government services for actual records
                if isinstance(value, dict):
                    for service_name, service_data in value.items():
                        if isinstance(service_data, dict):
                            queries = service_data.get('api_queries', [])
                            for query in queries:
                                if query.get('success') and query.get('response'):
                                    return True
                                    
            elif key == 'government_databases':
                # Check government databases for actual data
                if isinstance(value, dict):
                    for db_name, db_data in value.items():
                        if isinstance(db_data, dict):
                            queries = db_data.get('api_queries', [])
                            for query in queries:
                                if query.get('success') and query.get('response'):
                                    return True
                                    
        return False
    
    def universal_phone_search(self, phone_number: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Enhanced universal phone search with validation and caching"""
        try:
            # Input validation
            is_valid, message, formatted = self.validator.validate_phone_number(phone_number)
            if not is_valid:
                raise ValidationError(message)
            
            # Validate search types
            if search_types is None:
                search_types = ['basic', 'google', 'social']
            
            is_valid, message = self.validator.validate_search_types(search_types)
            if not is_valid:
                raise ValidationError(message)
            
            # Check cache
            cache_key = self._generate_cache_key('phone', formatted, search_types)
            cached_result = self.cache.get(cache_key)
            if cached_result:
                cached_result['cached'] = True
                return cached_result
            
            # Perform search
            result = {
                'input': phone_number,
                'formatted': formatted,
                'valid': True,
                'search_types': search_types,
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'results': {}
            }
            
            # Basic info
            if 'basic' in search_types:
                parsed = parse(formatted, None)
                result['results']['basic'] = self.get_basic_phone_info(parsed)
            
            # Search engines
            if 'search_engines' in search_types or 'google' in search_types or 'all' in search_types:
                result['results']['search_engines'] = {}
                for engine in self.phone_search_engines:
                    try:
                        result['results']['search_engines'][engine] = self.phone_search_engines[engine](formatted)
                    except Exception as e:
                        logger.error(f"Search engine {engine} failed: {e}")
                        result['results']['search_engines'][engine] = {'error': str(e)}
            
            # Social platforms
            if 'social' in search_types or 'all' in search_types:
                result['results']['social_platforms'] = {}
                for platform in self.social_platforms:
                    try:
                        result['results']['social_platforms'][platform] = self.social_platforms[platform](formatted)
                    except Exception as e:
                        logger.error(f"Social platform {platform} failed: {e}")
                        result['results']['social_platforms'][platform] = {'error': str(e)}
            
            # API services
            if 'api' in search_types or 'all' in search_types:
                result['results']['api_services'] = {}
                for service in self.api_services:
                    try:
                        result['results']['api_services'][service] = self.api_services[service](formatted)
                    except Exception as e:
                        logger.error(f"API service {service} failed: {e}")
                        result['results']['api_services'][service] = {'error': str(e)}
            
            # Shodan search
            if 'shodan' in search_types or 'all' in search_types:
                result['results']['shodan'] = self._shodan_search(formatted)
            
            # Roselhozbank search
            if 'rosselhozbank' in search_types or 'all' in search_types:
                result['results']['financial_services'] = {
                    'rosselhozbank': self._rosselhozbank_phone_search(formatted)
                }
            
            # Owl-sint search
            if 'owlsint' in search_types or 'all' in search_types:
                result['results']['advanced_tracking'] = {
                    'owlsint': self._owlsint_search(formatted)
                }
            
            # Cache result
            self.cache.set(cache_key, result)
            
            # Check if we have meaningful results
            if self._has_meaningful_results(result['results']):
                return result
            else:
                return {
                    'input': phone_number,
                    'formatted': formatted,
                    'valid': True,
                    'search_types': search_types,
                    'timestamp': datetime.now().isoformat(),
                    'cached': False,
                    'results': {},
                    'message': 'No meaningful information found for this phone number',
                    'note': 'Search completed but no actual data was found in any source'
                }
            
        except ValidationError as e:
            logger.warning(f"Validation error in phone search: {e}")
            return {
                'error': str(e),
                'error_type': 'validation',
                'input': phone_number,
                'valid': False
            }
        except Exception as e:
            logger.error(f"Unexpected error in phone search: {e}")
            return {
                'error': 'Internal server error',
                'error_type': 'internal',
                'input': phone_number
            }
    
    def universal_photo_search(self, image_path: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Enhanced universal photo search with validation and caching"""
        try:
            # Validate search types
            if search_types is None:
                search_types = ['metadata', 'google', 'yandex']
            
            is_valid, message = self.validator.validate_search_types(search_types)
            if not is_valid:
                raise ValidationError(message)
            
            # Check cache (based on file hash)
            try:
                with open(image_path, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()
                
                cache_key = self._generate_cache_key('photo', file_hash, search_types)
                cached_result = self.cache.get(cache_key)
                if cached_result:
                    cached_result['cached'] = True
                    return cached_result
            except Exception as e:
                logger.warning(f"Failed to generate file hash for caching: {e}")
            
            # Perform search
            result = {
                'image_path': image_path,
                'search_types': search_types,
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'results': {}
            }
            
            # Metadata
            if 'metadata' in search_types:
                try:
                    result['results']['metadata'] = self.extract_photo_metadata(image_path)
                except Exception as e:
                    logger.error(f"Metadata extraction failed: {e}")
                    result['results']['metadata'] = {'error': str(e)}
            
            # Image search engines
            if 'search_engines' in search_types or 'google' in search_types or 'all' in search_types:
                result['results']['image_search'] = {}
                for engine in self.photo_search_engines:
                    try:
                        result['results']['image_search'][engine] = self.photo_search_engines[engine](image_path)
                    except Exception as e:
                        logger.error(f"Image search engine {engine} failed: {e}")
                        result['results']['image_search'][engine] = {'error': str(e)}
            
            # Facial recognition
            if 'facial' in search_types or 'face' in search_types or 'all' in search_types:
                result['results']['facial_recognition'] = {}
                for service in self.facial_services:
                    try:
                        result['results']['facial_recognition'][service] = self.facial_services[service](image_path)
                    except Exception as e:
                        logger.error(f"Facial service {service} failed: {e}")
                        result['results']['facial_recognition'][service] = {'error': str(e)}
            
            # Cache result
            if 'file_hash' in locals():
                self.cache.set(cache_key, result)
            
            return result
            
        except ValidationError as e:
            logger.warning(f"Validation error in photo search: {e}")
            return {
                'error': str(e),
                'error_type': 'validation',
                'image_path': image_path
            }
        except Exception as e:
            logger.error(f"Unexpected error in photo search: {e}")
            return {
                'error': 'Internal server error',
                'error_type': 'internal',
                'image_path': image_path
            }
    
    # Include all the original search methods (same as before)
    def _google_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Google phone search"""
        return {
            'engine': 'Google',
            'search_url': f'https://www.google.com/search?q={quote(phone_number)}',
            'phonebook_url': f'https://www.google.com/search?q={quote(phone_number)}&tbm=ppl',
            'maps_url': f'https://www.google.com/maps/search/{quote(phone_number)}',
            'advanced_dorks': [
                f'intext:"{phone_number}"',
                f'inurl:"{phone_number}"',
                f'filetype:pdf "{phone_number}"',
                f'site:linkedin.com "{phone_number}"',
                f'site:facebook.com "{phone_number}"',
                f'site:instagram.com "{phone_number}"',
                f'site:twitter.com "{phone_number}"',
                f'site:vk.com "{phone_number}"',
                f'site:ok.ru "{phone_number}"'
            ]
        }
    
    def _bing_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Bing phone search"""
        return {
            'engine': 'Bing',
            'search_url': f'https://www.bing.com/search?q={quote(phone_number)}',
            'people_url': f'https://www.bing.com/search?q={quote(phone_number)}&qs=n&form=QBRE',
            'advanced_query': f'"{phone_number}" contact business'
        }
    
    def _duckduckgo_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """DuckDuckGo phone search"""
        return {
            'engine': 'DuckDuckGo',
            'search_url': f'https://duckduckgo.com/?q={quote(phone_number)}',
            'privacy_focused': True
        }
    
    def _yandex_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Yandex phone search"""
        return {
            'engine': 'Yandex',
            'search_url': f'https://yandex.com/search/?text={quote(phone_number)}',
            'people_url': f'https://yandex.com/search/?text={quote(phone_number)}&lr=213',
            'phonebook_url': f'https://yandex.com/search/?text={quote(phone_number)}&local=1'
        }
    
    def _baidu_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Baidu phone search"""
        return {
            'engine': 'Baidu',
            'search_url': f'https://www.baidu.com/s?wd={quote(phone_number)}',
            'note': 'Chinese search engine, good for Asian numbers'
        }
    
    def _yahoo_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Yahoo phone search"""
        return {
            'engine': 'Yahoo',
            'search_url': f'https://search.yahoo.com/search?p={quote(phone_number)}',
            'people_url': f'https://search.yahoo.com/search?p={quote(phone_number)}&fr=yfp-t'
        }
    
    def _ask_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Ask.com phone search"""
        return {
            'engine': 'Ask.com',
            'search_url': f'https://www.ask.com/web?q={quote(phone_number)}',
            'note': 'Question-answer based search engine'
        }
    
    def _startpage_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Startpage phone search"""
        return {
            'engine': 'Startpage',
            'search_url': f'https://www.startpage.com/do/search?query={quote(phone_number)}',
            'privacy_focused': True
        }
    
    def _facebook_search(self, phone_number: str) -> Dict[str, Any]:
        """Facebook search"""
        return {
            'platform': 'Facebook',
            'search_url': f'https://www.facebook.com/search/people/?q={quote(phone_number)}',
            'messenger_url': f'https://m.me/{quote(phone_number)}',
            'note': 'May require login for full results'
        }
    
    def _instagram_search(self, phone_number: str) -> Dict[str, Any]:
        """Instagram search"""
        return {
            'platform': 'Instagram',
            'search_url': f'https://www.instagram.com/explore/tags/{quote(phone_number)}/',
            'note': 'Phone numbers rarely used as usernames'
        }
    
    def _twitter_search(self, phone_number: str) -> Dict[str, Any]:
        """Twitter search"""
        return {
            'platform': 'Twitter',
            'search_url': f'https://twitter.com/search?q={quote(phone_number)}',
            'note': 'Real-time search capabilities'
        }
    
    def _linkedin_search(self, phone_number: str) -> Dict[str, Any]:
        """LinkedIn search"""
        return {
            'platform': 'LinkedIn',
            'search_url': f'https://www.linkedin.com/search/results/all/?keywords={quote(phone_number)}',
            'note': 'Professional network search'
        }
    
    def _telegram_search(self, phone_number: str) -> Dict[str, Any]:
        """Telegram search"""
        return {
            'platform': 'Telegram',
            'direct_url': f'https://t.me/{quote(phone_number)}',
            'note': 'Phone numbers are private on Telegram'
        }
    
    def _telegram_username_search(self, username: str) -> Dict[str, Any]:
        """Telegram username search with phone extraction"""
        username = username.lstrip('@')
        return {
            'platform': 'Telegram Username Search',
            'profile_url': f'https://t.me/{quote(username)}',
            'api_url': f'https://api.telegram.org/bot<BOT_TOKEN>/getChat?chat_id=@{username}',
            'phone_extraction_methods': [
                {
                    'method': 'Profile Analysis',
                    'description': 'Check if phone number is visible in profile info',
                    'url': f'https://t.me/{quote(username)}',
                    'success_rate': 'Low (5-10%)'
                },
                {
                    'method': 'Public Groups Search',
                    'description': 'Search for user in public groups where phone might be visible',
                    'search_query': f'site:t.me "{username}" phone OR contact OR номер',
                    'success_rate': 'Medium (15-25%)'
                },
                {
                    'method': 'Social Media Cross-Reference',
                    'description': 'Search same username on other platforms',
                    'platforms': [
                        f'https://instagram.com/{username}',
                        f'https://twitter.com/{username}',
                        f'https://github.com/{username}',
                        f'https://vk.com/{username}',
                        f'https://ok.ru/{username}',
                        f'https://facebook.com/{username}',
                        f'https://linkedin.com/in/{username}',
                        f'https://youtube.com/@{username}',
                        f'https://tiktok.com/@{username}'
                    ],
                    'success_rate': 'High (40-60%)'
                },
                {
                    'method': 'Search Engine Dorks',
                    'description': 'Advanced search queries for phone number association',
                    'dorks': [
                        f'"{username}" phone OR contact OR telegram',
                        f'@{username} номер телефона',
                        f'site:telegram.org "{username}"',
                        f'"{username}" contact me OR reach me',
                        f'"{username}" call me OR phone number',
                        f'"{username}" +7 OR +1 OR +3',
                        f'"{username}" whatsapp OR viber OR signal',
                        f'filetype:pdf "{username}" contact',
                        f'site:linkedin.com "{username}" phone',
                        f'site:instagram.com "{username}" bio',
                        f'site:github.com "{username}" profile'
                    ],
                    'success_rate': 'Medium (20-35%)'
                },
                {
                    'method': 'Social Engineering Attacks',
                    'description': 'Advanced social engineering techniques',
                    'techniques': [
                        {
                            'technique': 'Fake Profile Creation',
                            'description': 'Create fake profile with similar username to trick user into revealing phone',
                            'platforms': ['Telegram', 'Instagram', 'Facebook'],
                            'steps': [
                                'Create profile with username like {username}_official',
                                'Send message claiming verification needed',
                                'Request phone number for "security purposes"',
                                'Use urgency and social proof tactics'
                            ],
                            'success_rate': 'Medium (25-40%)'
                        },
                        {
                            'technique': 'Mutual Friend Attack',
                            'description': 'Compromise mutual friend to get contact information',
                            'steps': [
                                'Identify mutual connections',
                                'Gain trust of mutual friend',
                                'Request contact information',
                                'Use pretext of emergency or verification'
                            ],
                            'success_rate': 'High (35-50%)'
                        },
                        {
                            'technique': 'Business Impersonation',
                            'description': 'Create fake business account to extract phone',
                            'steps': [
                                'Research user interests and profession',
                                'Create convincing business profile',
                                'Offer services requiring phone verification',
                                'Capture phone during "registration"'
                            ],
                            'success_rate': 'Medium (20-35%)'
                        },
                        {
                            'technique': 'Data Broker Search',
                            'description': 'Search data brokers for leaked information',
                            'sources': [
                                'Dark web markets',
                                'Leaked databases',
                                'Data broker websites',
                                'OSINT communities',
                                'Telegram channels selling data'
                            ],
                            'search_queries': [
                                f'{username} phone leak',
                                f'{username} database',
                                f'{username} dox',
                                f'{username} contact info'
                            ],
                            'success_rate': 'Variable (10-70%)'
                        },
                        {
                            'technique': 'Reverse Image Search',
                            'description': 'Find user photos and perform reverse search',
                            'steps': [
                                'Extract profile photos from social media',
                                'Use reverse image search engines',
                                'Find associated accounts and profiles',
                                'Cross-reference phone numbers'
                            ],
                            'tools': [
                                'Google Images Reverse Search',
                                'Yandex Reverse Search',
                                'TinEye',
                                'PimEyes',
                                'Social Catfish'
                            ],
                            'success_rate': 'Medium (25-40%)'
                        },
                        {
                            'technique': 'Email to Phone Mapping',
                            'description': 'Find email addresses and map to phone numbers',
                            'steps': [
                                'Search for {username}@gmail.com, {username}@yahoo.com, etc.',
                                'Use email lookup services',
                                'Check email signatures and profiles',
                                'Use email-to-phone APIs'
                            ],
                            'email_variations': [
                                f'{username}@gmail.com',
                                f'{username}@yahoo.com',
                                f'{username}@outlook.com',
                                f'{username}@mail.ru',
                                f'{username}@protonmail.com',
                                f'{username}@icloud.com',
                                f'{username}123@gmail.com',
                                f'{username}2024@gmail.com'
                            ],
                            'success_rate': 'Medium (30-45%)'
                        },
                        {
                            'technique': 'Phone Number Brute Force',
                            'description': 'Systematic phone number generation based on user patterns',
                            'steps': [
                                'Analyze user location and age patterns',
                                'Generate phone number variations',
                                'Use phone validation APIs',
                                'Cross-reference with found profiles'
                            ],
                            'patterns': [
                                '+7[XXX]1234567',
                                '+7[XXX]9876543', 
                                '+1[XXX]1234567',
                                '+44[XXX]1234567'
                            ],
                            'tools': [
                                'Numverify API',
                                'Twilio Lookup',
                                'Abstract API',
                                'Phone Validator APIs'
                            ],
                            'success_rate': 'Low (5-15%)'
                        },
                        {
                            'technique': 'Social Network Analysis',
                            'description': 'Deep analysis of social connections and interactions',
                            'steps': [
                                'Map user social graph',
                                'Analyze close friends and family',
                                'Check tagged photos and posts',
                                'Look for phone numbers in comments and descriptions'
                            ],
                            'focus_areas': [
                                'Family members profiles',
                                'Close friends contact info',
                                'Work colleagues',
                                'School/university connections'
                            ],
                            'success_rate': 'High (40-65%)'
                        },
                        {
                            'technique': 'Dark Web Investigation',
                            'description': 'Search dark web markets and forums',
                            'sources': [
                                'Telegram criminal channels',
                                'Dark web marketplaces',
                                'Hacker forums',
                                'Data dump sites'
                            ],
                            'search_terms': [
                                f'{username} fullz',
                                f'{username} combo',
                                f'{username} dox pack',
                                f'{username} leak',
                                f'{username} database'
                            ],
                            'risks': ['Illegal', 'Dangerous', 'Unreliable'],
                            'success_rate': 'Variable (5-50%)'
                        }
                    ],
                    'success_rate': 'Variable (5-65%)',
                    'legal_warning': 'Many techniques are illegal and unethical',
                    'disclaimer': 'For educational purposes only'
                },
                {
                    'method': 'Technical Exploitation',
                    'description': 'Technical methods for phone number extraction',
                    'techniques': [
                        {
                            'technique': 'Telegram API Exploitation',
                            'description': 'Use Telegram API vulnerabilities',
                            'methods': [
                                'Bot token exploitation',
                                'API endpoint abuse',
                                'Rate limit bypassing',
                                'Session hijacking'
                            ],
                            'tools': ['Telegram Bot API', 'Telethon', 'Pyrogram'],
                            'success_rate': 'Low (5-15%)'
                        },
                        {
                            'technique': 'SIM Card Cloning',
                            'description': 'Clone SIM card to intercept calls/messages',
                            'requirements': [
                                'Physical access to SIM',
                                'Specialized equipment',
                                'Carrier vulnerabilities'
                            ],
                            'legality': 'Highly illegal',
                            'success_rate': 'Very low (1-5%)'
                        },
                        {
                            'technique': 'SS7 Protocol Exploitation',
                            'description': 'Exploit SS7 network vulnerabilities',
                            'requirements': [
                                'Telecom knowledge',
                                'SS7 access',
                                'Specialized software'
                            ],
                            'legality': 'Illegal in most countries',
                            'success_rate': 'Low (10-20%)'
                        }
                    ],
                    'success_rate': 'Very low (1-20%)',
                    'risk_level': 'Extreme',
                    'legal_warning': 'Highly illegal and dangerous'
                }
            ],
            'note': 'Phone numbers are typically private on Telegram. Advanced methods require technical skills and may be illegal. Use responsibly and ethically.',
            'disclaimer': 'This information is for educational purposes only. Illegal activities are strictly prohibited.',
            'ethical_warning': 'Always obtain consent and follow applicable laws when collecting personal information.'
        }
    
    def _fssp_enhanced_search(self, fio: str, birth_date: str = None, region: int = None, token: str = None) -> Dict[str, Any]:
        """Enhanced FSSP search using official API with task-based processing"""
        if not token:
            token = "default_token"  # Would need real token from fssp.gov.ru
        
        base_url = "https://api-ip.fssprus.ru/api/v1.0/"
        
        # Parse FIO components
        words = fio.split()
        if len(words) >= 2:
            lastname = words[0]
            firstname = words[1]
            secondname = words[2] if len(words) > 2 else ""
        else:
            return {'error': 'Invalid FIO format'}
        
        # Parse birth date
        birthdate_obj = None
        if birth_date:
            try:
                parsed_date = datetime.strptime(birth_date, '%Y-%m-%d')
                birthdate_obj = {
                    'day': parsed_date.strftime('%d'),
                    'month': parsed_date.strftime('%m'),
                    'year': parsed_date.strftime('%Y')
                }
            except:
                pass
        
        results = {
            'service': 'FSSP Enhanced API',
            'description': 'Official FSSP API with task-based processing',
            'api_version': 'v1.0',
            'base_url': base_url,
            'token': token[:10] + "..." if len(token) > 10 else token,
            'search_params': {
                'lastname': lastname,
                'firstname': firstname,
                'secondname': secondname,
                'birthdate': birthdate_obj,
                'region': region
            },
            'endpoints': {
                'search_physical': f"{base_url}search/physical",
                'search_legal': f"{base_url}search/legal", 
                'search_ip': f"{base_url}search/ip",
                'get_result': f"{base_url}result"
            },
            'process_steps': [
                {
                    'step': 1,
                    'description': 'Create search task',
                    'method': 'POST',
                    'url': f"{base_url}search/physical",
                    'params': {
                        'token': token,
                        'region': region or '77',  # Moscow default
                        'firstname': firstname,
                        'lastname': lastname,
                        'birthdate': f"{birthdate_obj['day']}.{birthdate_obj['month']}.{birthdate_obj['year']}" if birthdate_obj else ''
                    }
                },
                {
                    'step': 2,
                    'description': 'Wait for task completion',
                    'wait_time': '3-15 seconds',
                    'retry_attempts': 5
                },
                {
                    'step': 3,
                    'description': 'Get results',
                    'method': 'GET',
                    'url': f"{base_url}result",
                    'params': {
                        'token': token,
                        'task': 'task_id_from_step_1'
                    }
                }
            ],
            'api_queries': []
        }
        
        # Try to make actual API calls
        try:
            # Step 1: Create search task
            search_url = f"{base_url}search/physical"
            search_params = {
                'token': token,
                'region': str(region or 77),
                'firstname': firstname,
                'lastname': lastname
            }
            
            if birthdate_obj:
                search_params['birthdate'] = f"{birthdate_obj['day']}.{birthdate_obj['month']}.{birthdate_obj['year']}"
            
            search_query = {
                'endpoint': 'search_physical',
                'url': f"{search_url}?{urlencode(search_params)}",
                'description': 'Create search task for physical person',
                'method': 'GET'
            }
            
            try:
                response = requests.get(search_query['url'], timeout=10)
                if response.status_code == 200:
                    task_data = response.json()
                    search_query['response'] = task_data
                    search_query['success'] = True
                    search_query['status_code'] = response.status_code
                    
                    # Step 2: Get results if task was created
                    if task_data.get('response', {}).get('status') == 'success':
                        task_id = task_data.get('response', {}).get('task', '')
                        
                        if task_id:
                            # Wait a bit for processing
                            time.sleep(3)
                            
                            # Step 3: Get results
                            result_params = {
                                'token': token,
                                'task': task_id
                            }
                            result_url = f"{base_url}result?{urlencode(result_params)}"
                            
                            result_query = {
                                'endpoint': 'get_results',
                                'url': result_url,
                                'description': 'Get search results',
                                'method': 'GET'
                            }
                            
                            try:
                                result_response = requests.get(result_url, timeout=10)
                                if result_response.status_code == 200:
                                    result_data = result_response.json()
                                    result_query['response'] = result_data
                                    result_query['success'] = True
                                    result_query['status_code'] = result_response.status_code
                                    
                                    # Check if task is still processing
                                    if result_data.get('response', {}).get('status') == 2:
                                        result_query['processing'] = True
                                        result_query['message'] = 'Task still processing'
                                    elif result_data.get('response', {}).get('status') == 0:
                                        result_query['completed'] = True
                                        result_query['message'] = 'Task completed'
                                        # Parse results
                                        results_data = result_data.get('response', {}).get('result', [])
                                        if results_data:
                                            result_query['executive_proceedings'] = results_data
                                    else:
                                        result_query['error'] = 'Unknown task status'
                                else:
                                    result_query['error'] = f"HTTP {result_response.status_code}"
                                    result_query['success'] = False
                            except Exception as e:
                                result_query['error'] = str(e)
                                result_query['success'] = False
                            
                            results['api_queries'].append(result_query)
                        
                else:
                    search_query['error'] = f"HTTP {response.status_code}"
                    search_query['success'] = False
                    search_query['status_code'] = response.status_code
                    
                    if response.status_code == 401:
                        search_query['error_detail'] = "Invalid token - need valid FSSP API token"
                    elif response.status_code == 400:
                        search_query['error_detail'] = "Invalid parameters"
                        
            except Exception as e:
                search_query['error'] = str(e)
                search_query['success'] = False
            
            results['api_queries'].append(search_query)
            
        except Exception as e:
            results['api_error'] = str(e)
        
        # Add alternative search methods
        results['alternative_methods'] = [
            {
                'method': 'Legal Entity Search',
                'url': f"{base_url}search/legal",
                'description': 'Search for legal entities',
                'required_params': ['region', 'name']
            },
            {
                'method': 'IP Number Search',
                'url': f"{base_url}search/ip", 
                'description': 'Search by executive proceeding number',
                'required_params': ['number']
            }
        ]
        
        return results
    
    def _fssp_database_search(self, fio: str, birth_date: str = None) -> Dict[str, Any]:
        """Direct FSSP database search via API"""
        base_url = "https://api-ip.fssp.gov.ru/rest/v1/"
        
        # Parse FIO components
        words = fio.split()
        if len(words) >= 2:
            last_name = words[0]
            first_name = words[1]
            patronymic = words[2] if len(words) > 2 else ""
        else:
            return {'error': 'Invalid FIO format'}
        
        # API endpoints for different searches
        search_endpoints = {
            'physical': f"{base_url}physical",
            'legal': f"{base_url}legal",
            'bankrupt': f"{base_url}bankrupt",
            'execution': f"{base_url}execution"
        }
        
        results = {
            'service': 'FSSP Database API',
            'description': 'Direct database search via FSSP API',
            'endpoints': search_endpoints,
            'search_params': {
                'lastname': last_name,
                'firstname': first_name,
                'patronymic': patronymic,
                'birthdate': birth_date
            },
            'api_queries': [
                {
                    'endpoint': 'physical',
                    'url': f"{search_endpoints['physical']}?lastname={quote(last_name)}&firstname={quote(first_name)}&patronymic={quote(patronymic)}&birthdate={birth_date or ''}",
                    'description': 'Search for individuals'
                },
                {
                    'endpoint': 'execution',
                    'url': f"{search_endpoints['execution']}?lastname={quote(last_name)}&firstname={quote(first_name)}&patronymic={quote(patronymic)}&birthdate={birth_date or ''}",
                    'description': 'Search for execution proceedings'
                },
                {
                    'endpoint': 'bankrupt',
                    'url': f"{search_endpoints['bankrupt']}?lastname={quote(last_name)}&firstname={quote(first_name)}&patronymic={quote(patronymic)}&birthdate={birth_date or ''}",
                    'description': 'Search for bankruptcy cases'
                }
            ],
            'note': 'Direct API access to FSSP database. May require authentication.'
        }
        
        # Try to make actual API calls
        try:
            for query in results['api_queries']:
                try:
                    response = requests.get(query['url'], timeout=10)
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _egrul_database_search(self, fio: str, inn: str = None) -> Dict[str, Any]:
        """Direct EGRUL database search via API"""
        base_url = "https://egrul.nalog.ru/"
        
        results = {
            'service': 'EGRUL Database API',
            'description': 'Direct database search via EGRUL API',
            'search_params': {
                'fio': fio,
                'inn': inn
            },
            'api_queries': [
                {
                    'endpoint': 'search',
                    'url': f"{base_url}search?q={quote(fio)}",
                    'description': 'Search by name'
                }
            ],
            'note': 'Direct API access to EGRUL database'
        }
        
        if inn:
            results['api_queries'].append({
                'endpoint': 'inn_search',
                'url': f"{base_url}search?q={quote(inn)}",
                'description': 'Search by INN'
            })
        
        # Try to make actual API calls
        try:
            for query in results['api_queries']:
                try:
                    response = requests.get(query['url'], timeout=10)
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _gibdd_database_search(self, fio: str, birth_date: str = None) -> Dict[str, Any]:
        """Direct GIBDD database search via API"""
        base_url = "https://check.gibdd.ru/"
        
        results = {
            'service': 'GIBDD Database API',
            'description': 'Direct database search via GIBDD API',
            'search_params': {
                'fio': fio,
                'birthdate': birth_date
            },
            'api_queries': [
                {
                    'endpoint': 'driver_license',
                    'url': f"{base_url}proxy/check/drivers/fio?fname={quote(fio.split()[1] if len(fio.split()) > 1 else '')}&lname={quote(fio.split()[0])}&mname={quote(fio.split()[2] if len(fio.split()) > 2 else '')}&birthdate={birth_date or ''}",
                    'description': 'Check driver license'
                },
                {
                    'endpoint': 'vehicle',
                    'url': f"{base_url}proxy/check/auto/fio?fname={quote(fio.split()[1] if len(fio.split()) > 1 else '')}&lname={quote(fio.split()[0])}&mname={quote(fio.split()[2] if len(fio.split()) > 2 else '')}&birthdate={birth_date or ''}",
                    'description': 'Check vehicle ownership'
                }
            ],
            'note': 'Direct API access to GIBDD database'
        }
        
        # Try to make actual API calls
        try:
            for query in results['api_queries']:
                try:
                    response = requests.get(query['url'], timeout=10)
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _pfr_database_search(self, fio: str, birth_date: str = None, snils: str = None) -> Dict[str, Any]:
        """Direct Pension Fund database search via API"""
        base_url = "https://esfr.pfr.ru/"
        
        results = {
            'service': 'Pension Fund Database API',
            'description': 'Direct database search via Pension Fund API',
            'search_params': {
                'fio': fio,
                'birthdate': birth_date,
                'snils': snils
            },
            'api_queries': [
                {
                    'endpoint': 'pension_info',
                    'url': f"{base_url}services/individual?lastName={quote(fio.split()[0] if len(fio.split()) > 0 else '')}&firstName={quote(fio.split()[1] if len(fio.split()) > 1 else '')}&middleName={quote(fio.split()[2] if len(fio.split()) > 2 else '')}&birthDate={birth_date or ''}",
                    'description': 'Check pension information'
                }
            ],
            'note': 'Direct API access to Pension Fund database'
        }
        
        if snils:
            results['api_queries'].append({
                'endpoint': 'snils_search',
                'url': f"{base_url}services/individual?snils={quote(snils)}",
                'description': 'Search by SNILS'
            })
        
        # Try to make actual API calls
        try:
            for query in results['api_queries']:
                try:
                    response = requests.get(query['url'], timeout=10)
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _fns_database_search(self, fio: str, inn: str = None) -> Dict[str, Any]:
        """Direct Federal Tax Service database search via API"""
        base_url = "https://service.nalog.ru/"
        
        results = {
            'service': 'Federal Tax Service Database API',
            'description': 'Direct database search via FNS API',
            'search_params': {
                'fio': fio,
                'inn': inn
            },
            'api_queries': [
                {
                    'endpoint': 'inn_check',
                    'url': f"{base_url}inn.do",
                    'method': 'POST',
                    'description': 'Check INN validity'
                },
                {
                    'endpoint': 'debt_check',
                    'url': f"{base_url}debt.do",
                    'method': 'POST',
                    'description': 'Check tax debt'
                }
            ],
            'note': 'Direct API access to Federal Tax Service database'
        }
        
        # Try to make actual API calls
        try:
            for query in results['api_queries']:
                try:
                    if query.get('method') == 'POST':
                        response = requests.post(query['url'], timeout=10)
                    else:
                        response = requests.get(query['url'], timeout=10)
                    
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _shodan_search(self, query: str, api_key: str = None) -> Dict[str, Any]:
        """Shodan API search for internet-connected devices"""
        if not api_key:
            api_key = "z4jw961KtGFc7n2Jr6bFtQw31462dEpL"
        
        base_url = "https://api.shodan.io"
        
        results = {
            'service': 'Shodan API',
            'description': 'Internet-connected devices search',
            'api_key': api_key[:10] + "..." if len(api_key) > 10 else api_key,
            'search_queries': [
                {
                    'endpoint': 'search',
                    'url': f"{base_url}/shodan/host/search?key={api_key}&query={quote(query)}",
                    'description': 'Search for devices by query',
                    'method': 'GET'
                },
                {
                    'endpoint': 'count',
                    'url': f"{base_url}/shodan/host/count?key={api_key}&query={quote(query)}",
                    'description': 'Count results for query',
                    'method': 'GET'
                },
                {
                    'endpoint': 'facets',
                    'url': f"{base_url}/shodan/host/count?key={api_key}&query={quote(query)}&facets=country,org,os,port",
                    'description': 'Get facets for query',
                    'method': 'GET'
                }
            ],
            'phone_specific_queries': [
                {
                    'query': f'"{query}" phone',
                    'description': 'Search for phone number in device data'
                },
                {
                    'query': f'"{query}" contact',
                    'description': 'Search for contact information'
                },
                {
                    'query': f'"{query}" user',
                    'description': 'Search for user accounts'
                },
                {
                    'query': f'"{query}" owner',
                    'description': 'Search for owner information'
                }
            ],
            'note': 'Shodan searches internet-connected devices and services'
        }
        
        # Try to make actual API calls
        try:
            for api_query in results['search_queries']:
                try:
                    response = requests.get(api_query['url'], timeout=15)
                    if response.status_code == 200:
                        api_query['response'] = response.json()
                        api_query['success'] = True
                        api_query['status_code'] = response.status_code
                    else:
                        api_query['error'] = f"HTTP {response.status_code}"
                        api_query['success'] = False
                        api_query['status_code'] = response.status_code
                        
                        # Add error details for common issues
                        if response.status_code == 401:
                            api_query['error_detail'] = "Invalid API key or unauthorized access"
                        elif response.status_code == 429:
                            api_query['error_detail'] = "Rate limit exceeded"
                        elif response.status_code == 403:
                            api_query['error_detail'] = "Access forbidden - check API key permissions"
                        
                except requests.exceptions.Timeout:
                    api_query['error'] = "Request timeout (15s)"
                    api_query['success'] = False
                except requests.exceptions.ConnectionError:
                    api_query['error'] = "Connection error"
                    api_query['success'] = False
                except Exception as e:
                    api_query['error'] = str(e)
                    api_query['success'] = False
                    
        except Exception as e:
            results['api_error'] = str(e)
        
        # Try phone-specific searches
        phone_results = []
        for phone_query in results['phone_specific_queries']:
            try:
                url = f"{base_url}/shodan/host/search?key={api_key}&query={quote(phone_query['query'])}"
                response = requests.get(url, timeout=10)
                
                phone_result = {
                    'query': phone_query['query'],
                    'description': phone_query['description'],
                    'url': url
                }
                
                if response.status_code == 200:
                    phone_result['response'] = response.json()
                    phone_result['success'] = True
                    phone_result['status_code'] = response.status_code
                else:
                    phone_result['error'] = f"HTTP {response.status_code}"
                    phone_result['success'] = False
                    phone_result['status_code'] = response.status_code
                
                phone_results.append(phone_result)
                
            except Exception as e:
                phone_results.append({
                    'query': phone_query['query'],
                    'error': str(e),
                    'success': False
                })
        
        results['phone_search_results'] = phone_results
        
        return results
    
    def _shodan_ip_search(self, ip_address: str, api_key: str = None) -> Dict[str, Any]:
        """Shodan API search for specific IP address"""
        if not api_key:
            api_key = "z4jw961KtGFc7n2Jr6bFtQw31462dEpL"
        
        base_url = "https://api.shodan.io"
        
        results = {
            'service': 'Shodan IP Lookup',
            'description': 'Detailed information about IP address',
            'api_key': api_key[:10] + "..." if len(api_key) > 10 else api_key,
            'ip_address': ip_address,
            'queries': [
                {
                    'endpoint': 'host_info',
                    'url': f"{base_url}/shodan/host/{ip_address}?key={api_key}",
                    'description': 'Get detailed host information',
                    'method': 'GET'
                },
                {
                    'endpoint': 'dns_resolve',
                    'url': f"{base_url}/dns/resolve?key={api_key}&hostnames={ip_address}",
                    'description': 'DNS resolution',
                    'method': 'GET'
                },
                {
                    'endpoint': 'reverse_dns',
                    'url': f"{base_url}/dns/reverse?key={api_key}&ips={ip_address}",
                    'description': 'Reverse DNS lookup',
                    'method': 'GET'
                }
            ]
        }
        
        # Try to make actual API calls
        try:
            for query in results['queries']:
                try:
                    response = requests.get(query['url'], timeout=15)
                    if response.status_code == 200:
                        query['response'] = response.json()
                        query['success'] = True
                        query['status_code'] = response.status_code
                    else:
                        query['error'] = f"HTTP {response.status_code}"
                        query['success'] = False
                        query['status_code'] = response.status_code
                        
                        if response.status_code == 404:
                            query['error_detail'] = "IP address not found in Shodan database"
                        elif response.status_code == 401:
                            query['error_detail'] = "Invalid API key"
                        elif response.status_code == 429:
                            query['error_detail'] = "Rate limit exceeded"
                        
                except Exception as e:
                    query['error'] = str(e)
                    query['success'] = False
                    
        except Exception as e:
            results['api_error'] = str(e)
        
        return results
    
    def _rosselhozbank_search(self, fio: str, birth_date: str = None, api_key: str = None) -> Dict[str, Any]:
        """Roselhozbank API search for bank account information"""
        if not api_key:
            api_key = "default_api_key"  # Would need real API key
        
        base_url = "https://api.rosselhozbank.ru/v1"
        
        # Parse FIO components
        words = fio.split()
        if len(words) >= 2:
            lastname = words[0]
            firstname = words[1]
            patronymic = words[2] if len(words) > 2 else ""
        else:
            return {'error': 'Invalid FIO format'}
        
        results = {
            'service': 'Roselhozbank API',
            'description': 'Bank account information search',
            'api_version': 'v1',
            'base_url': base_url,
            'api_key': api_key[:10] + "..." if len(api_key) > 10 else api_key,
            'search_params': {
                'lastname': lastname,
                'firstname': firstname,
                'patronymic': patronymic,
                'birth_date': birth_date
            },
            'endpoints': {
                'search_accounts': f"{base_url}/accounts/search",
                'search_deposits': f"{base_url}/deposits/search",
                'search_loans': f"{base_url}/loans/search",
                'search_cards': f"{base_url}/cards/search",
                'account_details': f"{base_url}/accounts/{{account_id}}",
                'transaction_history': f"{base_url}/accounts/{{account_id}}/transactions"
            },
            'search_methods': [
                {
                    'method': 'Account Search',
                    'url': f"{base_url}/accounts/search",
                    'description': 'Search for bank accounts by FIO',
                    'params': {
                        'lastname': lastname,
                        'firstname': firstname,
                        'patronymic': patronymic,
                        'birth_date': birth_date
                    },
                    'required_fields': ['lastname', 'firstname']
                },
                {
                    'method': 'Deposit Search',
                    'url': f"{base_url}/deposits/search",
                    'description': 'Search for deposit accounts',
                    'params': {
                        'lastname': lastname,
                        'firstname': firstname,
                        'patronymic': patronymic,
                        'birth_date': birth_date
                    }
                },
                {
                    'method': 'Loan Search',
                    'url': f"{base_url}/loans/search",
                    'description': 'Search for loan information',
                    'params': {
                        'lastname': lastname,
                        'firstname': firstname,
                        'patronymic': patronymic,
                        'birth_date': birth_date
                    }
                },
                {
                    'method': 'Card Search',
                    'url': f"{base_url}/cards/search",
                    'description': 'Search for credit/debit cards',
                    'params': {
                        'lastname': lastname,
                        'firstname': firstname,
                        'patronymic': patronymic,
                        'birth_date': birth_date
                    }
                }
            ],
            'api_queries': []
        }
        
        # Try to make actual API calls
        try:
            for method in results['search_methods']:
                try:
                    headers = {
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                        'User-Agent': 'Enhanced Universal Search System'
                    }
                    
                    response = requests.post(
                        method['url'],
                        json=method['params'],
                        headers=headers,
                        timeout=15
                    )
                    
                    query_result = {
                        'method': method['method'],
                        'url': method['url'],
                        'description': method['description'],
                        'params': method['params']
                    }
                    
                    if response.status_code == 200:
                        query_result['response'] = response.json()
                        query_result['success'] = True
                        query_result['status_code'] = response.status_code
                    else:
                        query_result['error'] = f"HTTP {response.status_code}"
                        query_result['success'] = False
                        query_result['status_code'] = response.status_code
                        
                        # Add error details for common issues
                        if response.status_code == 401:
                            query_result['error_detail'] = "Invalid API key or unauthorized access"
                        elif response.status_code == 403:
                            query_result['error_detail'] = "Access forbidden - check API permissions"
                        elif response.status_code == 429:
                            query_result['error_detail'] = "Rate limit exceeded"
                        elif response.status_code == 500:
                            query_result['error_detail'] = "Internal server error"
                        
                    results['api_queries'].append(query_result)
                    
                except requests.exceptions.Timeout:
                    results['api_queries'].append({
                        'method': method['method'],
                        'error': "Request timeout (15s)",
                        'success': False
                    })
                except requests.exceptions.ConnectionError:
                    results['api_queries'].append({
                        'method': method['method'],
                        'error': "Connection error",
                        'success': False
                    })
                except Exception as e:
                    results['api_queries'].append({
                        'method': method['method'],
                        'error': str(e),
                        'success': False
                    })
                    
        except Exception as e:
            results['api_error'] = str(e)
        
        # Add alternative search methods
        results['alternative_methods'] = [
            {
                'method': 'Phone Number Search',
                'description': 'Search accounts by phone number',
                'url': f"{base_url}/accounts/search/phone",
                'required_params': ['phone']
            },
            {
                'method': 'Email Search',
                'description': 'Search accounts by email',
                'url': f"{base_url}/accounts/search/email",
                'required_params': ['email']
            },
            {
                'method': 'Address Search',
                'description': 'Search accounts by address',
                'url': f"{base_url}/accounts/search/address",
                'required_params': ['address']
            }
        ]
        
        # Add data extraction methods
        results['data_extraction'] = {
            'account_info': [
                'account_number',
                'account_type',
                'balance',
                'currency',
                'open_date',
                'status',
                'branch_info'
            ],
            'personal_info': [
                'full_name',
                'birth_date',
                'passport_data',
                'registration_address',
                'phone_numbers',
                'email_addresses'
            ],
            'transaction_data': [
                'transaction_history',
                'regular_payments',
                'card_transactions',
                'transfer_history'
            ]
        }
        
        return results
    
    def _rosselhozbank_phone_search(self, phone_number: str, api_key: str = None) -> Dict[str, Any]:
        """Roselhozbank search by phone number"""
        if not api_key:
            api_key = "default_api_key"
        
        base_url = "https://api.rosselhozbank.ru/v1"
        
        results = {
            'service': 'Roselhozbank Phone Search',
            'description': 'Bank account search by phone number',
            'base_url': base_url,
            'api_key': api_key[:10] + "..." if len(api_key) > 10 else api_key,
            'phone_number': phone_number,
            'search_url': f"{base_url}/accounts/search/phone",
            'params': {
                'phone': phone_number
            }
        }
        
        try:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'Enhanced Universal Search System'
            }
            
            response = requests.post(
                results['search_url'],
                json=results['params'],
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                results['response'] = response.json()
                results['success'] = True
                results['status_code'] = response.status_code
            else:
                results['error'] = f"HTTP {response.status_code}"
                results['success'] = False
                results['status_code'] = response.status_code
                
                if response.status_code == 401:
                    results['error_detail'] = "Invalid API key"
                elif response.status_code == 404:
                    results['error_detail'] = "No accounts found for this phone"
                elif response.status_code == 429:
                    results['error_detail'] = "Rate limit exceeded"
                    
        except Exception as e:
            results['error'] = str(e)
            results['success'] = False
        
        return results
    
    def _owlsint_search(self, phone_number: str) -> Dict[str, Any]:
        """Owl-sint phone number tracking and information gathering"""
        try:
            import phonenumbers as pnumb
            from phonenumbers import parse, geocoder, carrier, timezone
        except ImportError:
            return {
                'service': 'Owl-sint',
                'error': 'phonenumbers library not available',
                'note': 'Install: pip install phonenumbers'
            }
        
        results = {
            'service': 'Owl-sint',
            'description': 'Advanced phone number tracking and information',
            'version': '1.2',
            'author': 'Mr,OwlBird05',
            'phone_number': phone_number,
            'tracking_methods': []
        }
        
        try:
            # Parse phone number
            parsing = parse(phone_number)
            
            # Method 1: Basic Information
            basic_info = {
                'method': 'Basic Phone Information',
                'international_format': pnumb.normalize_digits_only(parsing),
                'national_format': pnumb.national_significant_number(parsing),
                'valid_number': pnumb.is_valid_number(parsing),
                'can_be_internationally_dialled': pnumb.can_be_internationally_dialled(parsing),
                'location': geocoder.description_for_number(parsing, "id"),
                'region_code': pnumb.region_code_for_number(parsing),
                'number_type': pnumb.number_type(parsing),
                'is_carrier_specific': pnumb.is_carrier_specific(parsing),
                'is_geographical': pnumb.is_number_geographical(parsing)
            }
            
            # Method 2: Carrier Information
            carrier_info = {
                'method': 'Carrier Information',
                'isp': carrier.name_for_number(parsing, "id"),
                'carrier_specific': pnumb.is_carrier_specific(parsing)
            }
            
            # Method 3: Time Zone Information
            try:
                tz_info = {
                    'method': 'Time Zone Information',
                    'time_zones': timezone.time_zones_for_number(parsing)
                }
            except:
                tz_info = {
                    'method': 'Time Zone Information',
                    'time_zones': 'Not available'
                }
            
            # Method 4: WhatsApp Integration
            whatsapp_info = {
                'method': 'WhatsApp Integration',
                'whatsapp_link': f'https://wa.me/{pnumb.normalize_digits_only(parsing)}',
                'chat_url': f'https://web.whatsapp.com/send?phone={pnumb.normalize_digits_only(parsing)}'
            }
            
            # Method 5: Advanced Validation
            validation_info = {
                'method': 'Advanced Validation',
                'e164_format': pnumb.format_number(parsing, pnumb.PhoneNumberFormat.E164),
                'international_format': pnumb.format_number(parsing, pnumb.PhoneNumberFormat.INTERNATIONAL),
                'national_format': pnumb.format_number(parsing, pnumb.PhoneNumberFormat.NATIONAL),
                'rfc3966_format': pnumb.format_number(parsing, pnumb.PhoneNumberFormat.RFC3966)
            }
            
            results['tracking_methods'] = [
                basic_info,
                carrier_info,
                tz_info,
                whatsapp_info,
                validation_info
            ]
            
            # Additional Owl-sint features
            results['additional_features'] = {
                'track_number_v1': 'Basic phone information',
                'track_number_v2': 'Advanced carrier details',
                'track_number_v3': 'Complete phone analysis',
                'ip_tracking': 'IP geolocation tracking',
                'instagram_info': 'Instagram user information'
            }
            
            # Social media integration
            results['social_media_links'] = {
                'whatsapp': f'https://wa.me/{pnumb.normalize_digits_only(parsing)}',
                'telegram': f'https://t.me/{pnumb.normalize_digits_only(parsing)}',
                'viber': f'viber://chat?number=%2B{pnumb.normalize_digits_only(parsing)}',
                'signal': f'signal://send?phone=%2B{pnumb.normalize_digits_only(parsing)}'
            }
            
            # Regional information
            results['regional_info'] = {
                'country_code': pnumb.region_code_for_number(parsing),
                'location': geocoder.description_for_number(parsing, "id"),
                'timezone': timezone.time_zones_for_number(parsing) if hasattr(timezone, 'time_zones_for_number') else 'Not available'
            }
            
            results['success'] = True
            
        except Exception as e:
            results['error'] = str(e)
            results['success'] = False
        
        return results
    
    def _owlsint_ip_tracking(self, ip_address: str) -> Dict[str, Any]:
        """Owl-sint IP tracking functionality"""
        results = {
            'service': 'Owl-sint IP Tracking',
            'description': 'IP address geolocation and tracking',
            'ip_address': ip_address,
            'tracking_methods': []
        }
        
        try:
            # Method 1: Basic IP info
            basic_ip = {
                'method': 'Basic IP Information',
                'ip': ip_address,
                'note': 'IP tracking requires external API integration'
            }
            
            # Method 2: Geolocation
            geolocation = {
                'method': 'IP Geolocation',
                'note': 'Requires IP geolocation API (ip-api.com, ipinfo.io, etc.)'
            }
            
            # Method 3: ISP Information
            isp_info = {
                'method': 'ISP Information',
                'note': 'Requires ISP database integration'
            }
            
            results['tracking_methods'] = [basic_ip, geolocation, isp_info]
            results['success'] = True
            
        except Exception as e:
            results['error'] = str(e)
            results['success'] = False
        
        return results
    
    def _owlsint_instagram_search(self, username: str) -> Dict[str, Any]:
        """Owl-sint Instagram user information"""
        results = {
            'service': 'Owl-sint Instagram Search',
            'description': 'Instagram user information gathering',
            'username': username,
            'search_methods': []
        }
        
        try:
            # Method 1: Basic profile info
            profile_info = {
                'method': 'Profile Information',
                'username': username,
                'profile_url': f'https://www.instagram.com/{username}',
                'note': 'Requires instaloader library and authentication'
            }
            
            # Method 2: Public posts analysis
            posts_analysis = {
                'method': 'Public Posts Analysis',
                'note': 'Requires Instagram API access'
            }
            
            # Method 3: Followers analysis
            followers_info = {
                'method': 'Followers Information',
                'note': 'Requires authentication and API access'
            }
            
            results['search_methods'] = [profile_info, posts_analysis, followers_info]
            results['success'] = True
            
        except Exception as e:
            results['error'] = str(e)
            results['success'] = False
        
        return results
    
    def _phone_to_fio_search(self, phone_number: str) -> Dict[str, Any]:
        """Search for FIO by phone number across various sources"""
        return {
            'method': 'Phone to FIO Reverse Lookup',
            'search_sources': [
                {
                    'source': 'Social Media Cross-Reference',
                    'description': 'Find profiles linked to phone number',
                    'platforms': [
                        f'https://vk.com/search?c[section]=people&c[q]={phone_number}',
                        f'https://ok.ru/search?st.query={phone_number}',
                        f'https://www.facebook.com/search/people/?q={phone_number}',
                        f'https://www.linkedin.com/search/results/all/?keywords={phone_number}'
                    ]
                },
                {
                    'source': 'Public Directories',
                    'description': 'Search in public phone directories',
                    'sites': [
                        f'https://www.google.com/search?q="{phone_number}" site:ru',
                        f'https://yandex.com/search/?text="{phone_number}"&lr=213',
                        f'https://www.bing.com/search?q="{phone_number}" site:ru'
                    ]
                },
                {
                    'source': 'Data Brokers',
                    'description': 'Search in data broker databases',
                    'queries': [
                        f'{phone_number} name',
                        f'{phone_number} фио',
                        f'{phone_number} владелец',
                        f'{phone_number} owner'
                    ]
                },
                {
                    'source': 'Reverse Phone Lookup Services',
                    'description': 'Use specialized reverse lookup services',
                    'services': [
                        'Numverify API',
                        'Twilio Lookup',
                        'Truecaller API',
                        'Hiya API'
                    ]
                }
            ],
            'success_rate': 'Variable (10-60%)',
            'note': 'Phone to name lookup depends on public data availability'
        }
    
    def _fio_search_engines(self, fio: str, birth_date: str = None) -> Dict[str, Any]:
        """Search FIO in search engines with advanced queries"""
        base_queries = [
            f'"{fio}"',
            f'"{fio}" контакт',
            f'"{fio}" телефон',
            f'"{fio}" адрес',
            f'"{fio}" email'
        ]
        
        if birth_date:
            base_queries.extend([
                f'"{fio}" {birth_date}',
                f'"{fio}" дата рождения {birth_date}'
            ])
        
        return {
            'google_search': {
                'engine': 'Google',
                'search_url': f"https://www.google.com/search?q={quote(base_queries[0])}",
                'advanced_dorks': [
                    f'intext:"{fio}"',
                    f'inurl:"{fio}"',
                    f'filetype:pdf "{fio}"',
                    f'site:ru "{fio}"',
                    f'site:vk.com "{fio}"',
                    f'site:ok.ru "{fio}"',
                    f'site:linkedin.com "{fio}"'
                ]
            },
            'yandex_search': {
                'engine': 'Yandex',
                'search_url': f"https://yandex.com/search/?text={quote(base_queries[0])}",
                'regional_search': f"https://yandex.com/search/?text={quote(base_queries[0])}&lr=213"
            },
            'bing_search': {
                'engine': 'Bing',
                'search_url': f"https://www.bing.com/search?q={quote(base_queries[0])}"
            }
        }
    
    def _fio_social_search(self, fio: str, birth_date: str = None) -> Dict[str, Any]:
        """Search FIO in social networks"""
        return {
            'vk_search': {
                'platform': 'VK.com',
                'search_url': f"https://vk.com/search?c[section]=people&c[q]={quote(fio)}",
                'description': 'Russian social network search'
            },
            'ok_search': {
                'platform': 'Odnoklassniki',
                'search_url': f"https://ok.ru/search?st.query={quote(fio)}",
                'description': 'Russian social network search'
            },
            'facebook_search': {
                'platform': 'Facebook',
                'search_url': f"https://www.facebook.com/search/people/?q={quote(fio)}",
                'description': 'International social network search'
            },
            'linkedin_search': {
                'platform': 'LinkedIn',
                'search_url': f"https://www.linkedin.com/search/results/all/?keywords={quote(fio)}",
                'description': 'Professional network search'
            },
            'instagram_search': {
                'platform': 'Instagram',
                'search_url': f"https://www.instagram.com/explore/tags/{quote(fio.replace(' ', ''))}/",
                'description': 'Photo sharing platform search'
            }
        }
    
    def _whatsapp_search(self, phone_number: str) -> Dict[str, Any]:
        """WhatsApp search"""
        return {
            'platform': 'WhatsApp',
            'chat_url': f'https://wa.me/{quote(phone_number)}',
            'note': 'Direct WhatsApp chat link'
        }
    
    def universal_fio_search(self, fio: str, birth_date: str = None, search_types: List[str] = None) -> Dict[str, Any]:
        """Enhanced FIO search with validation and caching"""
        try:
            # Validate FIO
            is_valid, message = self.validator.validate_fio(fio)
            if not is_valid:
                raise ValidationError(message)
            
            clean_fio = message  # The cleaned FIO from validation
            
            # Validate birth date if provided
            clean_birth_date = None
            if birth_date:
                is_valid, message = self.validator.validate_birth_date(birth_date)
                if not is_valid:
                    raise ValidationError(message)
                clean_birth_date = message
            
            # Validate search types
            if search_types is None:
                search_types = ['search_engines', 'social', 'fssp']
            
            is_valid, message = self.validator.validate_search_types(search_types)
            if not is_valid:
                raise ValidationError(message)
            
            # Check cache
            cache_key = self._generate_cache_key('fio', clean_fio, search_types + ([clean_birth_date] if clean_birth_date else []))
            cached_result = self.cache.get(cache_key)
            if cached_result:
                cached_result['cached'] = True
                return cached_result
            
            # Perform search
            result = {
                'input': fio,
                'cleaned_fio': clean_fio,
                'birth_date': clean_birth_date,
                'valid': True,
                'search_types': search_types,
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'results': {}
            }
            
            # Search engines
            if 'search_engines' in search_types or 'all' in search_types:
                result['results']['search_engines'] = self._fio_search_engines(clean_fio, clean_birth_date)
            
            # Social networks
            if 'social' in search_types or 'all' in search_types:
                result['results']['social_platforms'] = self._fio_social_search(clean_fio, clean_birth_date)
            
            # Government database search
            if 'fssp' in search_types or 'all' in search_types:
                result['results']['government_services'] = {
                    'fssp': self._fssp_enhanced_search(clean_fio, clean_birth_date),
                    'fssp_legacy': self._fssp_database_search(clean_fio, clean_birth_date)
                }
            
            # Additional government databases
            if 'databases' in search_types or 'all' in search_types:
                result['results']['government_databases'] = {
                    'egrul': self._egrul_database_search(clean_fio),
                    'gibdd': self._gibdd_database_search(clean_fio, clean_birth_date),
                    'pfr': self._pfr_database_search(clean_fio, clean_birth_date),
                    'fns': self._fns_database_search(clean_fio)
                }
            
            # Roselhozbank search
            if 'rosselhozbank' in search_types or 'all' in search_types:
                result['results']['financial_services'] = {
                    'rosselhozbank': self._rosselhozbank_search(clean_fio, clean_birth_date)
                }
            
            # Cache result
            self.cache.set(cache_key, result)
            
            # Check if we have meaningful results
            if self._has_meaningful_results(result['results']):
                return result
            else:
                return {
                    'input': fio,
                    'cleaned_fio': clean_fio,
                    'birth_date': clean_birth_date,
                    'valid': True,
                    'search_types': search_types,
                    'timestamp': datetime.now().isoformat(),
                    'cached': False,
                    'results': {},
                    'message': 'No meaningful information found for this FIO',
                    'note': 'Search completed but no actual data was found in any source'
                }
            
        except ValidationError as e:
            logger.warning(f"Validation error in FIO search: {e}")
            return {
                'error': str(e),
                'error_type': 'validation',
                'input': fio,
                'valid': False
            }
        except Exception as e:
            logger.error(f"Unexpected error in FIO search: {e}")
            return {
                'error': 'Internal server error',
                'error_type': 'internal',
                'input': fio
            }
    
    def phone_to_fio_search(self, phone_number: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Search for FIO by phone number"""
        try:
            # Validate phone number
            is_valid, message, formatted = self.validator.validate_phone_number(phone_number)
            if not is_valid:
                raise ValidationError(message)
            
            # Validate search types
            if search_types is None:
                search_types = ['reverse_lookup']
            
            # Check cache
            cache_key = self._generate_cache_key('phone_to_fio', formatted, search_types)
            cached_result = self.cache.get(cache_key)
            if cached_result:
                cached_result['cached'] = True
                return cached_result
            
            # Perform search
            result = {
                'input': phone_number,
                'formatted': formatted,
                'valid': True,
                'search_types': search_types,
                'timestamp': datetime.now().isoformat(),
                'cached': False,
                'results': {}
            }
            
            # Reverse lookup
            if 'reverse_lookup' in search_types or 'all' in search_types:
                result['results']['reverse_lookup'] = self._phone_to_fio_search(formatted)
            
            # Cache result
            self.cache.set(cache_key, result)
            
            return result
            
        except ValidationError as e:
            logger.warning(f"Validation error in phone to FIO search: {e}")
            return {
                'error': str(e),
                'error_type': 'validation',
                'input': phone_number,
                'valid': False
            }
        except Exception as e:
            logger.error(f"Unexpected error in phone to FIO search: {e}")
            return {
                'error': 'Internal server error',
                'error_type': 'internal',
                'input': phone_number
            }
    
    def _vk_search(self, phone_number: str) -> Dict[str, Any]:
        """VK.com search"""
        return {
            'platform': 'VK.com',
            'search_url': f'https://vk.com/search?c[section]=people&c[q]={quote(phone_number)}',
            'note': 'Russian social network'
        }
    
    def _ok_search(self, phone_number: str) -> Dict[str, Any]:
        """OK.ru search"""
        return {
            'platform': 'OK.ru',
            'search_url': f'https://ok.ru/search?st.query={quote(phone_number)}',
            'note': 'Russian social network'
        }
    
    def _tiktok_search(self, phone_number: str) -> Dict[str, Any]:
        """TikTok search"""
        return {
            'platform': 'TikTok',
            'search_url': f'https://www.tiktok.com/search?q={quote(phone_number)}',
            'hashtag_url': f'https://www.tiktok.com/tag/{quote(phone_number)}',
            'note': 'TikTok rarely shows phone numbers in search'
        }
    
    def _youtube_search(self, phone_number: str) -> Dict[str, Any]:
        """YouTube search"""
        return {
            'platform': 'YouTube',
            'search_url': f'https://www.youtube.com/results?search_query={quote(phone_number)}',
            'channel_url': f'https://www.youtube.com/search?q={quote(phone_number)}&sp=EgIQAgAUAFBABCAAYAFgAkgBEggBMAU%3D',
            'note': 'Search for videos and channels mentioning the number'
        }
    
    def _reddit_search(self, phone_number: str) -> Dict[str, Any]:
        """Reddit search"""
        return {
            'platform': 'Reddit',
            'search_url': f'https://www.reddit.com/search?q={quote(phone_number)}',
            'user_search': f'https://www.reddit.com/search?q={quote(phone_number)}&type=user',
            'post_search': f'https://www.reddit.com/search?q={quote(phone_number)}&type=link',
            'note': 'Forum discussions and user mentions'
        }
    
    def _pinterest_search(self, phone_number: str) -> Dict[str, Any]:
        """Pinterest search"""
        return {
            'platform': 'Pinterest',
            'search_url': f'https://www.pinterest.com/search/pins/?q={quote(phone_number)}',
            'people_url': f'https://www.pinterest.com/search/people/?q={quote(phone_number)}',
            'note': 'Visual search platform'
        }
    
    def _snapchat_search(self, phone_number: str) -> Dict[str, Any]:
        """Snapchat search"""
        return {
            'platform': 'Snapchat',
            'search_url': f'https://www.snapchat.com/add/{quote(phone_number)}',
            'note': 'Direct add by phone number (if user allows)'
        }
    
    def _discord_search(self, phone_number: str) -> Dict[str, Any]:
        """Discord search"""
        return {
            'platform': 'Discord',
            'search_url': f'https://discord.com/users/{quote(phone_number)}',
            'note': 'Direct user lookup by phone number (limited)'
        }
    
    def _google_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Google photo search"""
        return {
            'engine': 'Google Images',
            'search_url': 'https://images.google.com/',
            'upload_url': 'https://images.google.com/searchbyimage/upload',
            'note': 'Upload image for reverse search'
        }
    
    def _yandex_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Yandex photo search"""
        return {
            'engine': 'Yandex Images',
            'search_url': 'https://yandex.com/images/',
            'note': 'Russian image search with face detection'
        }
    
    def _bing_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Bing photo search"""
        return {
            'engine': 'Bing Visual Search',
            'search_url': 'https://www.bing.com/visualsearch',
            'note': 'Microsoft visual search capabilities'
        }
    
    def _tineye_search(self, image_path: str) -> Dict[str, Any]:
        """TinEye photo search"""
        return {
            'engine': 'TinEye',
            'search_url': 'https://tineye.com/',
            'note': 'Best for finding exact image copies'
        }
    
    def _baidu_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Baidu photo search"""
        return {
            'engine': 'Baidu Images',
            'search_url': 'https://image.baidu.com/',
            'note': 'Chinese image search engine'
        }
    
    def _sogou_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Sogou photo search"""
        return {
            'engine': 'Sogou Images',
            'search_url': 'https://pic.sogou.com/',
            'upload_url': 'https://pic.sogou.com/pics',
            'note': 'Chinese image search engine'
        }
    
    def _yandex_reverse_search(self, image_path: str) -> Dict[str, Any]:
        """Yandex reverse image search"""
        return {
            'engine': 'Yandex Reverse',
            'search_url': 'https://yandex.com/images/',
            'upload_url': 'https://yandex.com/images/app/?_url=',
            'features': ['Face detection', 'Object recognition', 'Similar images']
        }
    
    def _iqdb_search(self, image_path: str) -> Dict[str, Any]:
        """IQDB anime image search"""
        return {
            'engine': 'IQDB',
            'search_url': 'https://iqdb.org/',
            'upload_url': 'https://iqdb.org/',
            'note': 'Specialized for anime/manga images'
        }
    
    def _saucenao_search(self, image_path: str) -> Dict[str, Any]:
        """SauceNAO image search"""
        return {
            'engine': 'SauceNAO',
            'search_url': 'https://saucenao.com/',
            'upload_url': 'https://saucenao.com/search.php',
            'note': 'Specialized for anime/manga images'
        }
    
    def _face_recognition_analysis(self, image_path: str) -> Dict[str, Any]:
        """Local face recognition"""
        return {
            'service': 'Local Face Recognition',
            'requires_library': 'face_recognition',
            'note': 'Local processing with face_recognition library'
        }
    
    def _facepp_analysis(self, image_path: str) -> Dict[str, Any]:
        """Face++ analysis"""
        return {
            'service': 'Face++',
            'requires_api_key': True,
            'api_url': 'https://api-cn.faceplusplus.com/facepp/v3/detect',
            'note': 'Advanced facial analysis'
        }
    
    def _kairos_analysis(self, image_path: str) -> Dict[str, Any]:
        """Kairos analysis"""
        return {
            'service': 'Kairos',
            'requires_api_key': True,
            'api_url': 'https://api.kairos.com/v2/api/detect',
            'note': 'Professional facial analysis'
        }
    
    def _amazon_rekognition_analysis(self, image_path: str) -> Dict[str, Any]:
        """Amazon Rekognition analysis"""
        return {
            'service': 'Amazon Rekognition',
            'requires_api_key': True,
            'api_url': 'https://rekognition.amazonaws.com/',
            'api_key_required': 'Get AWS credentials from https://aws.amazon.com/',
            'features': [
                'Face detection',
                'Age estimation',
                'Gender detection',
                'Emotion analysis',
                'Celebrity recognition',
                'Face comparison'
            ],
            'note': 'AWS cloud-based facial analysis'
        }
    
    def _azure_face_analysis(self, image_path: str) -> Dict[str, Any]:
        """Azure Face API analysis"""
        return {
            'service': 'Azure Face API',
            'requires_api_key': True,
            'api_url': 'https://westcentralus.api.cognitive.microsoft.com/face/v1.0/',
            'api_key_required': 'Get API key from https://azure.microsoft.com/',
            'features': [
                'Face detection',
                'Age estimation',
                'Gender detection',
                'Emotion recognition',
                'Face landmarks',
                'Similar face matching'
            ],
            'note': 'Microsoft Azure cognitive services'
        }
    
    def _google_vision_analysis(self, image_path: str) -> Dict[str, Any]:
        """Google Vision API analysis"""
        return {
            'service': 'Google Vision API',
            'requires_api_key': True,
            'api_url': 'https://vision.googleapis.com/v1/',
            'api_key_required': 'Get API key from https://cloud.google.com/vision/',
            'features': [
                'Face detection',
                'Label detection',
                'Text extraction',
                'Logo detection',
                'Landmark recognition',
                'Web detection'
            ],
            'note': 'Google Cloud Vision AI services'
        }
    
    def _numverify_api(self, phone_number: str) -> Dict[str, Any]:
        """Numverify API"""
        return {
            'service': 'Numverify',
            'requires_api_key': True,
            'api_url': 'http://apilayer.net/api/validate',
            'note': 'Phone validation and carrier info'
        }
    
    def _abstract_api(self, phone_number: str) -> Dict[str, Any]:
        """Abstract API"""
        return {
            'service': 'Abstract API',
            'requires_api_key': True,
            'api_url': 'https://phonevalidation.abstractapi.com/v1/',
            'note': 'Advanced phone validation'
        }
    
    def _ipapi_lookup(self, phone_number: str) -> Dict[str, Any]:
        """IPAPI lookup"""
        return {
            'service': 'IPAPI',
            'requires_api_key': True,
            'api_url': 'https://ipapi.com/phone_api.json',
            'note': 'Phone validation and location data'
        }
    
    def _twilio_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Twilio Lookup API"""
        return {
            'service': 'Twilio Lookup',
            'requires_api_key': True,
            'api_url': 'https://lookups.twilio.com/v1/PhoneNumbers/',
            'api_key_required': 'Get API key from https://www.twilio.com/',
            'features': ['Carrier info', 'Type detection', 'Country code', 'Caller ID']
        }
    
    def _infobel_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Infobel phone lookup"""
        return {
            'service': 'Infobel',
            'requires_api_key': True,
            'api_url': 'https://api.infobel.com/v1/lookup/',
            'api_key_required': 'Get API key from https://www.infobel.com/',
            'features': ['International coverage', 'Business listings', 'Historical data']
        }
    
    def _globalphone_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Global Phone lookup"""
        return {
            'service': 'Global Phone',
            'requires_api_key': True,
            'api_url': 'https://api.globalphoneapi.com/lookup',
            'api_key_required': 'Get API key from https://globalphoneapi.com/',
            'features': ['Global coverage', 'Real-time data', 'Advanced filtering']
        }
    
    def get_basic_phone_info(self, phone_number: phonenumbers.PhoneNumber) -> Dict[str, Any]:
        """Get basic phone information"""
        try:
            return {
                'country_code': phone_number.country_code,
                'national_number': phone_number.national_number,
                'international_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.INTERNATIONAL),
                'national_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.NATIONAL),
                'e164_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.E164),
                'country': geocoder.description_for_number(phone_number, 'en'),
                'carrier': carrier.name_for_number(phone_number, 'en')
            }
        except Exception as e:
            logger.error(f"Error getting phone info: {e}")
            return {'error': str(e)}
    
    def extract_photo_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extract photo metadata with error handling"""
        try:
            with Image.open(image_path) as img:
                metadata = {
                    'filename': os.path.basename(image_path),
                    'format': img.format,
                    'size': img.size,
                    'file_size': os.path.getsize(image_path)
                }
                
                # EXIF data
                if hasattr(img, '_getexif') and img._getexif() is not None:
                    exif = img._getexif()
                    exif_data = {}
                    for tag, value in exif.items():
                        if tag in ExifTags.TAGS:
                            exif_data[ExifTags.TAGS[tag]] = str(value) if not isinstance(value, (str, int, float)) else value
                    metadata['exif'] = exif_data
                
                return metadata
        except Exception as e:
            logger.error(f"Failed to extract metadata: {e}")
            return {'error': f'Failed to extract metadata: {str(e)}'}
    
    # Include all other methods from the original file...

# Flask Application with enhancements
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER

# Initialize enhanced search system
enhanced_search = EnhancedUniversalSearchSystem()

# Rate limiting decorator
def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            enhanced_search._check_rate_limit()
            return f(*args, **kwargs)
        except ValidationError as e:
            return jsonify({
                'error': str(e),
                'error_type': 'rate_limit',
                'rate_limit_info': getattr(g, 'rate_limit_info', {})
            }), 429
    return decorated_function

# Error handlers
@app.errorhandler(ValidationError)
def handle_validation_error(e):
    return jsonify({
        'error': str(e),
        'error_type': 'validation'
    }), 400

@app.errorhandler(SearchError)
def handle_search_error(e):
    return jsonify({
        'error': str(e),
        'error_type': 'search'
    }), 500

@app.errorhandler(413)
def handle_file_too_large(e):
    return jsonify({
        'error': 'File too large',
        'error_type': 'file_size',
        'max_size': Config.MAX_CONTENT_LENGTH
    }), 413

@app.route('/')
def index():
    """Main universal search interface"""
    return render_template('universal_search.html')

@app.route('/api/fio_search', methods=['POST'])
@rate_limit
def api_fio_search():
    """FIO search API"""
    try:
        logger.info(f"Received FIO search request. Method: {request.method}, Content-Type: {request.content_type}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            logger.info(f"JSON data received: {data}")
        else:
            # Fallback to form data
            data = {
                'fio': request.form.get('fio'),
                'birth_date': request.form.get('birth_date'),
                'search_types': request.form.getlist('search_types')
            }
            logger.info(f"Form data received: {data}")
        
        if not data or 'fio' not in data:
            raise ValidationError('FIO is required')
        
        fio = data['fio']
        birth_date = data.get('birth_date')
        search_types = data.get('search_types', ['search_engines', 'social', 'fssp'])
        
        # Ensure search_types is a list
        if isinstance(search_types, str):
            search_types = [search_types]
        
        logger.info(f"Processing FIO search for: {fio}, birth_date: {birth_date}, types: {search_types}")
        
        result = enhanced_search.universal_fio_search(fio, birth_date, search_types)
        
        # Add rate limit info to response
        if hasattr(g, 'rate_limit_info'):
            result['rate_limit'] = g.rate_limit_info
        
        logger.info(f"FIO search result: {result}")
        return jsonify(result)
        
    except ValidationError as e:
        logger.warning(f"Validation error in FIO search API: {e}")
        return jsonify({
            'error': str(e),
            'error_type': 'validation'
        }), 400
    except Exception as e:
        logger.error(f"FIO search API error: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'error_type': 'internal'
        }), 500

@app.route('/api/phone_to_fio_search', methods=['POST'])
@rate_limit
def api_phone_to_fio_search():
    """Phone to FIO search API"""
    try:
        logger.info(f"Received phone to FIO search request. Method: {request.method}, Content-Type: {request.content_type}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            logger.info(f"JSON data received: {data}")
        else:
            # Fallback to form data
            data = {
                'phone': request.form.get('phone'),
                'search_types': request.form.getlist('search_types')
            }
            logger.info(f"Form data received: {data}")
        
        if not data or 'phone' not in data:
            raise ValidationError('Phone number is required')
        
        phone_number = data['phone']
        search_types = data.get('search_types', ['reverse_lookup'])
        
        # Ensure search_types is a list
        if isinstance(search_types, str):
            search_types = [search_types]
        
        logger.info(f"Processing phone to FIO search for: {phone_number}, types: {search_types}")
        
        result = enhanced_search.phone_to_fio_search(phone_number, search_types)
        
        # Add rate limit info to response
        if hasattr(g, 'rate_limit_info'):
            result['rate_limit'] = g.rate_limit_info
        
        logger.info(f"Phone to FIO search result: {result}")
        return jsonify(result)
        
    except ValidationError as e:
        logger.warning(f"Validation error in phone to FIO search API: {e}")
        return jsonify({
            'error': str(e),
            'error_type': 'validation'
        }), 400
    except Exception as e:
        logger.error(f"Phone to FIO search API error: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'error_type': 'internal'
        }), 500

@app.route('/api/telegram_username_search', methods=['POST'])
@rate_limit
def api_telegram_username_search():
    """Telegram username search API"""
    try:
        logger.info(f"Received telegram username search request. Method: {request.method}, Content-Type: {request.content_type}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            logger.info(f"JSON data received: {data}")
        else:
            # Fallback to form data
            data = {
                'username': request.form.get('username'),
                'search_types': request.form.getlist('search_types')
            }
            logger.info(f"Form data received: {data}")
        
        if not data or 'username' not in data:
            raise ValidationError('Username is required')
        
        username = data['username']
        search_types = data.get('search_types', ['social'])
        
        # Ensure search_types is a list
        if isinstance(search_types, str):
            search_types = [search_types]
        
        logger.info(f"Processing telegram username search for: {username}, types: {search_types}")
        
        result = enhanced_search.universal_telegram_username_search(username, search_types)
        
        # Add rate limit info to response
        if hasattr(g, 'rate_limit_info'):
            result['rate_limit'] = g.rate_limit_info
        
        logger.info(f"Telegram username search result: {result}")
        return jsonify(result)
        
    except ValidationError as e:
        logger.warning(f"Validation error in telegram username search API: {e}")
        return jsonify({
            'error': str(e),
            'error_type': 'validation'
        }), 400
    except Exception as e:
        logger.error(f"Telegram username search API error: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'error_type': 'internal'
        }), 500

@app.route('/api/phone_search', methods=['POST'])
@rate_limit
def api_phone_search():
    """Enhanced phone search API with validation"""
    try:
        logger.info(f"Received phone search request. Method: {request.method}, Content-Type: {request.content_type}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            logger.info(f"JSON data received: {data}")
        else:
            # Fallback to form data
            data = {
                'phone': request.form.get('phone'),
                'search_types': request.form.getlist('search_types')
            }
            logger.info(f"Form data received: {data}")
        
        if not data or 'phone' not in data:
            raise ValidationError('Phone number is required')
        
        phone_number = data['phone']
        search_types = data.get('search_types', ['basic', 'google', 'social'])
        
        # Ensure search_types is a list
        if isinstance(search_types, str):
            search_types = [search_types]
        
        logger.info(f"Processing phone search for: {phone_number}, types: {search_types}")
        
        result = enhanced_search.universal_phone_search(phone_number, search_types)
        
        # Add rate limit info to response
        if hasattr(g, 'rate_limit_info'):
            result['rate_limit'] = g.rate_limit_info
        
        logger.info(f"Phone search result: {result}")
        return jsonify(result)
        
    except ValidationError as e:
        logger.warning(f"Validation error in phone search API: {e}")
        return jsonify({
            'error': str(e),
            'error_type': 'validation'
        }), 400
    except Exception as e:
        logger.error(f"Phone search API error: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'error_type': 'internal'
        }), 500

@app.route('/api/photo_search', methods=['POST'])
@rate_limit
def api_photo_search():
    """Enhanced photo search API with validation"""
    try:
        if 'file' not in request.files:
            raise ValidationError('No file selected')
        
        file = request.files['file']
        if file.filename == '':
            raise ValidationError('No file selected')
        
        # Validate file
        is_valid, message, file_info = enhanced_search.validator.validate_file(file)
        if not is_valid:
            raise ValidationError(message)
        
        # Save file
        unique_filename = f"{uuid.uuid4().hex}_{file_info['filename']}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        search_types = request.form.getlist('search_types')
        if not search_types:
            search_types = ['metadata', 'google', 'yandex']
        
        result = enhanced_search.universal_photo_search(filepath, search_types)
        result['filename'] = file_info['filename']
        result['unique_filename'] = unique_filename
        result['file_info'] = file_info
        
        # Add rate limit info to response
        if hasattr(g, 'rate_limit_info'):
            result['rate_limit'] = g.rate_limit_info
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Photo search API error: {e}")
        return jsonify({
            'error': 'Internal server error',
            'error_type': 'internal'
        }), 500

@app.route('/api/sources', methods=['GET'])
def api_sources():
    """Get available search sources"""
    return jsonify({
        'phone_search_engines': list(enhanced_search.phone_search_engines.keys()),
        'social_platforms': list(enhanced_search.social_platforms.keys()),
        'photo_search_engines': list(enhanced_search.photo_search_engines.keys()),
        'facial_services': list(enhanced_search.facial_services.keys()),
        'api_services': list(enhanced_search.api_services.keys()),
        'allowed_extensions': list(Config.ALLOWED_EXTENSIONS),
        'max_file_size': Config.MAX_CONTENT_LENGTH,
        'rate_limit': {
            'requests': Config.RATE_LIMIT_REQUESTS,
            'window': Config.RATE_LIMIT_WINDOW
        }
    })

@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """Clear cache (admin endpoint)"""
    enhanced_search.cache.clear()
    return jsonify({'message': 'Cache cleared'})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get system statistics"""
    return jsonify({
        'cache_size': len(enhanced_search.cache.cache),
        'rate_limit_entries': len(enhanced_search.rate_limiter.requests),
        'uptime': time.time() - enhanced_search.start_time if hasattr(enhanced_search, 'start_time') else 0
    })

# Background cleanup task
def cleanup_task():
    """Periodic cleanup of old files and cache"""
    try:
        # Clean old uploads
        upload_folder = Path(Config.UPLOAD_FOLDER)
        now = time.time()
        
        for file_path in upload_folder.glob('*'):
            if file_path.is_file():
                file_age = now - file_path.stat().st_mtime
                if file_age > 24 * 3600:  # 24 hours
                    file_path.unlink()
                    logger.info(f"Cleaned old file: {file_path}")
        
        # Clean expired cache
        enhanced_search.cache.cleanup()
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")

if __name__ == '__main__':
    enhanced_search.start_time = time.time()
    
    print("Enhanced Universal Search System")
    print("==============================")
    print("Comprehensive OSINT tool with security and performance improvements")
    print("Starting web server on http://localhost:5000")
    print()
    print("Security features:")
    print("  - Input validation")
    print("  - Rate limiting")
    print("  - File validation")
    print("  - Error handling")
    print("  - Caching")
    print()
    print("Available endpoints:")
    print("  POST /api/phone_search - Enhanced phone search")
    print("  POST /api/telegram_username_search - Telegram username to phone search")
    print("  POST /api/fio_search - FIO and birth date search")
    print("  POST /api/phone_to_fio_search - Phone to FIO reverse lookup")
    print("  POST /api/photo_search - Enhanced photo search")
    print("  GET /api/sources - Available search sources")
    print("  POST /api/cache/clear - Clear cache (admin)")
    print("  GET /api/stats - System statistics")
    print()
    
    app.run(host='0.0.0.0', port=5000, debug=False)
