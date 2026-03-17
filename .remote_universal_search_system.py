#!/usr/bin/env python3
"""
Universal Search System
Comprehensive OSINT tool for phone numbers and photos with all possible sources
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
import sqlite3
import requests
from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
from PIL import ExifTags, Image, ImageEnhance, ImageFilter, ImageOps
from phonenumbers import parse, NumberParseException, is_valid_number, geocoder, carrier
from phonenumbers.phonenumberutil import PhoneNumberFormat
import phonenumbers
from typing import Dict, Any, List, Optional, Set, Tuple
import logging
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qsl, quote, urlencode

# Local data-breaches database (redacted output only)
from data_breaches import DataBreachesParser
from directory_db import search_records, stats_by_city_and_category

# Optional .env support (do not hard-require python-dotenv)
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = None  # type: ignore

def _load_env_safe() -> None:
    if not load_dotenv:
        return

    try:
        # If python-dotenv is installed, automatically load local .env.
        load_dotenv()
        return
    except UnicodeEncodeError:
        # Some hosting environments expose ASCII-only process env.
        # Fall back to a minimal parser and ignore invalid variable names.
        pass

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return

    with open(env_path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
                value = value[1:-1]
            try:
                os.environ[key] = value
            except UnicodeEncodeError:
                # Skip values that cannot be represented in process locale.
                continue


_load_env_safe()

# Safe subset of X-osint-like utilities
from xosint_toolkit import XOsintToolkit

try:
    from tg_catalog_db import catalog_stats, random_catalog, search_catalog, top_catalog
    _TG_CATALOG_AVAILABLE = True
except ImportError:
    _TG_CATALOG_AVAILABLE = False

try:
    from telethon import TelegramClient
    from telethon.errors import RPCError
    _TELETHON_AVAILABLE = True
except ImportError:
    TelegramClient = None  # type: ignore[assignment]
    RPCError = Exception  # type: ignore[assignment]
    _TELETHON_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UniversalSearchSystem:
    """Universal OSINT search system for phones and photos"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # File upload settings
        self.upload_folder = 'uploads'
        self.allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
        self.max_file_size = 16 * 1024 * 1024  # 16MB
        
        if not os.path.exists(self.upload_folder):
            os.makedirs(self.upload_folder)
        
        # Phone search engines
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
        
        # Social platforms (extended)
        self.social_platforms = {
            'facebook': self._facebook_search,
            'instagram': self._instagram_search,
            'twitter': self._twitter_search,
            'linkedin': self._linkedin_search,
            'telegram': self._telegram_search,
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
        
        # Photo search engines
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
        
        # API services
        self.api_services = {
            'numverify': self._numverify_api,
            'abstract_api': self._abstract_api,
            'ipapi': self._ipapi_lookup,
            'twilio': self._twilio_lookup,
            'infobel': self._infobel_lookup,
            'globalphone': self._globalphone_lookup
        }
        
        # Facial recognition services
        self.facial_services = {
            'face_recognition': self._face_recognition_analysis,
            'facepp': self._facepp_analysis,
            'kairos': self._kairos_analysis,
            'amazon_rekognition': self._amazon_rekognition_analysis,
            'azure_face': self._azure_face_analysis,
            'google_vision': self._google_vision_analysis
        }

        # Local breach database (NOTE: we return redacted/aggregated info only)
        self.data_breaches = DataBreachesParser()

        # Optional X-osint-style toolkit (safe subset)
        self.xosint = XOsintToolkit(self.session)

    def data_breaches_search(self, phone: str) -> Dict[str, Any]:
        """Search phone number in local breach database.

        Security/privacy: this method intentionally does NOT return raw leaked records (PII).
        It returns only aggregated summary and counts.
        """
        try:
            breach_results = self.data_breaches.search_by_phone(phone)

            if breach_results.get('found'):
                summary = breach_results.get('summary', {}) or {}
                return {
                    'service': 'Data Breaches Database',
                    'description': 'Search through local breach databases (redacted output)',
                    'found': True,
                    'matches': int(breach_results.get('matches', 0) or 0),
                    'data': [],
                    'data_redacted': True,
                    'redaction_note': 'Sensitive personal data has been redacted',
                    'summary': summary,
                    'risk_assessment': {
                        'highest_risk': summary.get('highest_risk', 'LOW'),
                        'total_exposed': int(breach_results.get('matches', 0) or 0),
                        'platforms_affected': summary.get('platforms_affected', [])
                    }
                }

            return {
                'service': 'Data Breaches Database',
                'description': 'Search through local breach databases (redacted output)',
                'found': False,
                'matches': 0,
                'message': 'No records found in breach databases'
            }
        except (ValueError, TypeError, sqlite3.Error) as e:
            return {
                'service': 'Data Breaches Database',
                'found': False,
                'error': str(e)
            }

    def _data_breaches_search(self, phone: str) -> Dict[str, Any]:
        """Backward-compatible alias for internal/external callers."""
        return self.data_breaches_search(phone)
    
    # Phone search methods
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
    
    def _yandex_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """Yandex phone search"""
        return {
            'engine': 'Yandex',
            'search_url': f'https://yandex.com/search/?text={quote(phone_number)}',
            'people_url': f'https://yandex.com/search/?text={quote(phone_number)}&lr=213',  # Moscow region
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
    
    def _duckduckgo_phone_search(self, phone_number: str) -> Dict[str, Any]:
        """DuckDuckGo phone search"""
        return {
            'engine': 'DuckDuckGo',
            'search_url': f'https://duckduckgo.com/?q={quote(phone_number)}',
            'privacy_focused': True
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
    
    # Extended social media search
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
    
    # Photo search methods
    def _sogou_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Sogou photo search"""
        _ = image_path
        return {
            'engine': 'Sogou Images',
            'search_url': 'https://pic.sogou.com/',
            'upload_url': 'https://pic.sogou.com/pics',
            'note': 'Chinese image search engine'
        }
    
    def _yandex_reverse_search(self, image_path: str) -> Dict[str, Any]:
        """Yandex reverse image search"""
        _ = image_path
        return {
            'engine': 'Yandex Reverse',
            'search_url': 'https://yandex.com/images/',
            'upload_url': 'https://yandex.com/images/app/?_url=',
            'features': ['Face detection', 'Object recognition', 'Similar images']
        }
    
    def _iqdb_search(self, image_path: str) -> Dict[str, Any]:
        """IQDB anime image search"""
        _ = image_path
        return {
            'engine': 'IQDB',
            'search_url': 'https://iqdb.org/',
            'upload_url': 'https://iqdb.org/',
            'note': 'Specialized for anime/manga images'
        }
    
    def _saucenao_search(self, image_path: str) -> Dict[str, Any]:
        """SauceNAO image search"""
        _ = image_path
        return {
            'engine': 'SauceNAO',
            'search_url': 'https://saucenao.com/',
            'upload_url': 'https://saucenao.com/search.php',
            'note': 'Specialized for anime/manga images'
        }
    
    # API services
    def _twilio_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Twilio Lookup API"""
        _ = phone_number
        return {
            'service': 'Twilio Lookup',
            'requires_api_key': True,
            'api_url': 'https://lookups.twilio.com/v1/PhoneNumbers/',
            'api_key_required': 'Get API key from https://www.twilio.com/',
            'features': ['Carrier info', 'Type detection', 'Country code', 'Caller ID']
        }
    
    def _infobel_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Infobel phone lookup"""
        _ = phone_number
        return {
            'service': 'Infobel',
            'requires_api_key': True,
            'api_url': 'https://api.infobel.com/v1/lookup/',
            'api_key_required': 'Get API key from https://www.infobel.com/',
            'features': ['International coverage', 'Business listings', 'Historical data']
        }
    
    def _globalphone_lookup(self, phone_number: str) -> Dict[str, Any]:
        """Global Phone lookup"""
        _ = phone_number
        return {
            'service': 'Global Phone',
            'requires_api_key': True,
            'api_url': 'https://api.globalphoneapi.com/lookup',
            'api_key_required': 'Get API key from https://globalphoneapi.com/',
            'features': ['Global coverage', 'Real-time data', 'Advanced filtering']
        }
    
    # Facial recognition services
    def _amazon_rekognition_analysis(self, image_path: str) -> Dict[str, Any]:
        """Amazon Rekognition analysis"""
        _ = image_path
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
        _ = image_path
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
        _ = image_path
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
    
    # Include previous methods (simplified versions)
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
    
    def _whatsapp_search(self, phone_number: str) -> Dict[str, Any]:
        """WhatsApp search"""
        return {
            'platform': 'WhatsApp',
            'chat_url': f'https://wa.me/{quote(phone_number)}',
            'note': 'Direct WhatsApp chat link'
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
    
    def _google_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Google photo search"""
        _ = image_path
        return {
            'engine': 'Google Images',
            'search_url': 'https://images.google.com/',
            'upload_url': 'https://images.google.com/searchbyimage/upload',
            'note': 'Upload image for reverse search'
        }
    
    def _bing_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Bing photo search"""
        _ = image_path
        return {
            'engine': 'Bing Visual Search',
            'search_url': 'https://www.bing.com/visualsearch',
            'note': 'Microsoft visual search capabilities'
        }
    
    def _tineye_search(self, image_path: str) -> Dict[str, Any]:
        """TinEye photo search"""
        _ = image_path
        return {
            'engine': 'TinEye',
            'search_url': 'https://tineye.com/',
            'note': 'Best for finding exact image copies'
        }
    
    def _baidu_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Baidu photo search"""
        _ = image_path
        return {
            'engine': 'Baidu Images',
            'search_url': 'https://image.baidu.com/',
            'note': 'Chinese image search engine'
        }
    
    def _yandex_photo_search(self, image_path: str) -> Dict[str, Any]:
        """Yandex photo search"""
        _ = image_path
        return {
            'engine': 'Yandex Images',
            'search_url': 'https://yandex.com/images/',
            'note': 'Russian image search with face detection'
        }
    
    def _numverify_api(self, phone_number: str) -> Dict[str, Any]:
        """Numverify API"""
        _ = phone_number
        return {
            'service': 'Numverify',
            'requires_api_key': True,
            'api_url': 'http://apilayer.net/api/validate',
            'note': 'Phone validation and carrier info'
        }
    
    def _abstract_api(self, phone_number: str) -> Dict[str, Any]:
        """Abstract API"""
        _ = phone_number
        return {
            'service': 'Abstract API',
            'requires_api_key': True,
            'api_url': 'https://phonevalidation.abstractapi.com/v1/',
            'note': 'Advanced phone validation'
        }
    
    def _ipapi_lookup(self, phone_number: str) -> Dict[str, Any]:
        """IPAPI lookup"""
        _ = phone_number
        return {
            'service': 'IPAPI',
            'requires_api_key': True,
            'api_url': 'https://ipapi.com/phone_api.json',
            'note': 'Phone validation and location data'
        }
    
    def _face_recognition_analysis(self, image_path: str) -> Dict[str, Any]:
        """Local face recognition"""
        _ = image_path
        return {
            'service': 'Local Face Recognition',
            'requires_library': 'face_recognition',
            'note': 'Local processing with face_recognition library'
        }
    
    def _facepp_analysis(self, image_path: str) -> Dict[str, Any]:
        """Face++ analysis"""
        _ = image_path
        return {
            'service': 'Face++',
            'requires_api_key': True,
            'api_url': 'https://api-cn.faceplusplus.com/facepp/v3/detect',
            'note': 'Advanced facial analysis'
        }
    
    def _kairos_analysis(self, image_path: str) -> Dict[str, Any]:
        """Kairos analysis"""
        _ = image_path
        return {
            'service': 'Kairos',
            'requires_api_key': True,
            'api_url': 'https://api.kairos.com/v2/api/detect',
            'note': 'Professional facial analysis'
        }
    
    # Phone validation
    def validate_and_parse(self, phone_number: str) -> Optional[phonenumbers.PhoneNumber]:
        """Validate and parse phone number"""
        phone_number = phone_number.replace(' ', '').replace('-', '')
        
        try:
            parsed = parse(phone_number, None)
            if is_valid_number(parsed):
                return parsed
        except NumberParseException:
            pass
        
        for region in ['US', 'GB', 'FR', 'DE', 'RU', 'IN', 'BR', 'CN', 'JP']:
            try:
                parsed = parse(phone_number, region)
                if is_valid_number(parsed):
                    return parsed
            except NumberParseException:
                continue
        
        return None
    
    def get_basic_phone_info(self, phone_number: phonenumbers.PhoneNumber) -> Dict[str, Any]:
        """Get basic phone information"""
        # `geocoder.description_for_number` returns a human-friendly location (region/city),
        # not necessarily the country name. We expose both for convenience.
        location_en = geocoder.description_for_number(phone_number, 'en')
        # Russian localization for UI/CLI users in this workspace.
        location_ru = geocoder.description_for_number(phone_number, 'ru')

        return {
            'country_code': phone_number.country_code,
            'national_number': phone_number.national_number,
            'international_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.INTERNATIONAL),
            'national_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.NATIONAL),
            'e164_format': phonenumbers.format_number(phone_number, PhoneNumberFormat.E164),
            # Backward compatible keys:
            'country': location_en,
            'carrier': carrier.name_for_number(phone_number, 'en'),
            # New fields:
            'region_code': phonenumbers.region_code_for_number(phone_number),
            'location_en': location_en,
            'location_ru': location_ru,
        }

    def _owner_lookup_local(self, phone_e164: str, limit: int = 5) -> Dict[str, Any]:
        """Try to find an owner/name for a phone using local, user-provided datasets.

        IMPORTANT:
        - We do NOT attempt any network scraping here.
        - This relies only on `business_directory.db` (see `directory_db.py`).
        - Returned values are "candidates" because directory datasets may contain
          organizations, departments, call-centers, etc. It's not always a private owner.
        """
        try:
            result = search_records(query=phone_e164, field='phone', limit=limit, offset=0)
            items = result.get('items') or []

            candidates = []
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    {
                        'name': item.get('name') or '',
                        'legal_form': item.get('legal_form') or '',
                        'category': item.get('category') or '',
                        'city': item.get('city') or '',
                        'dataset_name': item.get('dataset_name') or '',
                        # Keep the phone itself for traceability; other fields are available
                        # via /api/directory/search if needed.
                        'phones': item.get('phones') or '',
                    }
                )

            return {
                'service': 'Local Directory (business_directory.db)',
                'found': bool(candidates),
                'matches': int(result.get('total') or 0),
                'candidates': candidates,
                'note': 'Owner/name is derived from local directory datasets; it may be an organization, not a private individual.'
            }
        except (sqlite3.Error, OSError, ValueError, TypeError) as e:
            return {
                'service': 'Local Directory (business_directory.db)',
                'found': False,
                'error': str(e),
            }
    
    def extract_photo_metadata(self, image_path: str) -> Dict[str, Any]:
        """Extract photo metadata"""
        try:
            with Image.open(image_path) as img:
                metadata = {
                    'filename': os.path.basename(image_path),
                    'format': img.format,
                    'size': img.size,
                    'file_size': os.path.getsize(image_path)
                }
                
                # EXIF data (use public Pillow API)
                try:
                    exif = img.getexif()
                except (AttributeError, OSError, ValueError):
                    exif = None

                if exif:
                    exif_data = {}
                    for tag, value in exif.items():
                        if tag in ExifTags.TAGS:
                            exif_data[ExifTags.TAGS[tag]] = str(value) if not isinstance(value, (str, int, float)) else value
                    metadata['exif'] = exif_data
                
                return metadata
        except (OSError, ValueError) as e:
            return {'error': f'Failed to extract metadata: {str(e)}'}
    
    def allowed_file(self, filename: str) -> bool:
        """Check if file is allowed"""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in self.allowed_extensions
    
    def universal_phone_search(self, phone_number: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Universal phone search across all sources"""
        if search_types is None:
            search_types = ['basic', 'google', 'social']
        
        parsed = self.validate_and_parse(phone_number)
        if not parsed:
            return {
                'error': 'Invalid phone number',
                'input': phone_number,
                'valid': False
            }
        
        formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        results = {
            'input': phone_number,
            'formatted': formatted,
            'valid': True,
            'search_types': search_types,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': {}
        }
        
        # Basic info
        if 'basic' in search_types:
            results['results']['basic'] = self.get_basic_phone_info(parsed)

        # Local owner/name lookup (offline, from directory DB only)
        if 'owner' in search_types or 'all' in search_types:
            results['results']['owner'] = self._owner_lookup_local(formatted)
        
        # Search engines
        if 'search_engines' in search_types or 'google' in search_types or 'all' in search_types:
            results['results']['search_engines'] = {}
            for engine in self.phone_search_engines:
                results['results']['search_engines'][engine] = self.phone_search_engines[engine](formatted)
        
        # Social platforms
        if 'social' in search_types or 'all' in search_types:
            results['results']['social_platforms'] = {}
            for platform in self.social_platforms:
                results['results']['social_platforms'][platform] = self.social_platforms[platform](formatted)
        
        # API services
        if 'api' in search_types or 'all' in search_types:
            results['results']['api_services'] = {}
            for service in self.api_services:
                results['results']['api_services'][service] = self.api_services[service](formatted)

        # Local breach databases (redacted)
        if 'data_breaches' in search_types or 'all' in search_types:
            results['results']['data_breaches'] = self.data_breaches_search(formatted)

        # Optional external vendor lookups (requires user-supplied API keys)
        if 'xosint_phone' in search_types:
            results['results']['xosint_phone'] = self.xosint.phone_external_lookup(formatted)
        
        return results
    
    def universal_photo_search(self, image_path: str, search_types: List[str] = None) -> Dict[str, Any]:
        """Universal photo search across all sources"""
        if search_types is None:
            search_types = ['metadata', 'google', 'yandex']
        
        results = {
            'image_path': image_path,
            'search_types': search_types,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': {}
        }
        
        # Metadata
        if 'metadata' in search_types:
            results['results']['metadata'] = self.extract_photo_metadata(image_path)
        
        # Image search engines
        if 'search_engines' in search_types or 'google' in search_types or 'all' in search_types:
            results['results']['image_search'] = {}
            for engine in self.photo_search_engines:
                results['results']['image_search'][engine] = self.photo_search_engines[engine](image_path)
        
        # Facial recognition
        if 'facial' in search_types or 'face' in search_types or 'all' in search_types:
            results['results']['facial_recognition'] = {}
            for service in self.facial_services:
                results['results']['facial_recognition'][service] = self.facial_services[service](image_path)
        
        return results


MINI_APP_DEFAULT_GROUP_SCAN_LIMIT = 500
MINI_APP_MAX_GROUP_SCAN_LIMIT = 3000
MINI_APP_MAX_FILTER_KEYWORD_LEN = 64
MINI_APP_BOT_DB_PATH = os.getenv('TELEGRAM_BOT_DB_PATH', 'telegram_bot.db').strip() or 'telegram_bot.db'
MINI_APP_REPORT_767_DB_PATH = os.getenv('REPORT_767_DB_PATH', 'reports_767.db').strip() or 'reports_767.db'
MINI_APP_PROCESS_STARTED = int(time.time())
_TG_USERNAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{4,31}$')


def _parse_int_set(raw: str) -> Set[int]:
    values: Set[int] = set()
    for part in (raw or '').split(','):
        item = part.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError:
            logger.warning('Invalid integer in env list ignored: %s', item)
    return values


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _clean_telegram_username(value: str) -> str:
    username = (value or '').strip()
    if not username:
        return ''

    username = re.sub(r'^https?://', '', username, flags=re.IGNORECASE)
    username = re.sub(r'^(www\.)?(t\.me|telegram\.me)/', '', username, flags=re.IGNORECASE)
    username = username.lstrip('@').strip()
    return username


def _telegram_username_search(username: str, search_types: List[str]) -> Dict[str, Any]:
    cleaned = _clean_telegram_username(username)
    is_valid = bool(re.fullmatch(r'[A-Za-z0-9_]{5,32}', cleaned))
    if not is_valid:
        return {
            'input': username,
            'cleaned_username': cleaned,
            'valid': False,
            'error': 'Некорректный Telegram username. Допустимо: 5-32 символа A-Z, a-z, 0-9, _',
            'search_types': search_types,
            'results': {},
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    query = f'@{cleaned}'
    results: Dict[str, Any] = {}

    if 'social' in search_types or 'all' in search_types:
        results['social_platforms'] = {
            'telegram_profile': {
                'platform': 'Telegram',
                'profile_url': f'https://t.me/{cleaned}',
                'web_url': f'https://web.telegram.org/k/#{cleaned}',
            },
            'telegram_channels_search': {
                'platform': 'Telegram channels/groups',
                'search_url': f'https://t.me/s/{cleaned}',
                'note': 'Публичные каналы и группы, если существуют.',
            },
        }

    if 'search_engines' in search_types or 'all' in search_types:
        results['search_engines'] = {
            'google': {
                'engine': 'Google',
                'search_url': f'https://www.google.com/search?q={quote(f"{query} site:t.me")}',
            },
            'bing': {
                'engine': 'Bing',
                'search_url': f'https://www.bing.com/search?q={quote(f"{query} site:t.me")}',
            },
            'yandex': {
                'engine': 'Yandex',
                'search_url': f'https://yandex.com/search/?text={quote(f"{query} site:t.me")}',
            },
            'duckduckgo': {
                'engine': 'DuckDuckGo',
                'search_url': f'https://duckduckgo.com/?q={quote(f"{query} site:t.me")}',
            },
        }

    return {
        'input': username,
        'cleaned_username': cleaned,
        'valid': True,
        'search_types': search_types,
        'results': results,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }


def _parse_optional_int(raw: Any) -> Optional[int]:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value


MINI_APP_SMS_PROVIDER_BASE_URL = (
    os.getenv('SMS_ACTIVATE_BASE_URL', 'https://api.sms-activate.org/stubs/handler_api.php').strip()
    or 'https://api.sms-activate.org/stubs/handler_api.php'
)
MINI_APP_SMS_MIN_RETRY_SECONDS = max(10, _parse_optional_int(os.getenv('SMS_ACTIVATE_MIN_RETRY_SECONDS', '')) or 60)
MINI_APP_SMS_REQUEST_TIMEOUT = max(5, _parse_optional_int(os.getenv('SMS_ACTIVATE_TIMEOUT_SECONDS', '')) or 20)
MINI_APP_SMS_DEFAULT_COUNTRY = str(os.getenv('SMS_ACTIVATE_COUNTRY', '0') or '0').strip()
MINI_APP_SMS_DEFAULT_OPERATOR = str(os.getenv('SMS_ACTIVATE_OPERATOR', '') or '').strip()
MINI_APP_SMS_SERVICE_CODES = {
    'telegram': str(os.getenv('SMS_ACTIVATE_SERVICE_TELEGRAM', 'tg') or 'tg').strip(),
    'max': str(os.getenv('SMS_ACTIVATE_SERVICE_MAX', 'ot') or 'ot').strip(),
    'whatsapp': str(os.getenv('SMS_ACTIVATE_SERVICE_WHATSAPP', 'wa') or 'wa').strip(),
}


def _normalize_tg_username(raw: str) -> str:
    value = (raw or '').strip()
    if not value:
        raise ValueError('Укажи Telegram-ник.')

    lowered = value.lower()
    for prefix in (
        'https://t.me/',
        'http://t.me/',
        't.me/',
        'https://telegram.me/',
        'http://telegram.me/',
        'telegram.me/',
    ):
        if lowered.startswith(prefix):
            value = value[len(prefix):]
            break

    value = value.split('?', 1)[0].split('/', 1)[0].strip()
    if value.startswith('@'):
        value = value[1:]

    if not _TG_USERNAME_RE.fullmatch(value):
        raise ValueError('Некорректный ник. Используй 5-32 символа: латиница, цифры, _.')

    return value


def _build_tg_nick_links(username: str) -> Dict[str, str]:
    query = f'site:t.me {username}'
    return {
        'profile': f'https://t.me/{quote(username)}',
        'tgstat': f'https://tgstat.com/search?query={quote(username)}',
        'google_site_tme': 'https://www.google.com/search?q=' + quote(query),
        'yandex_site_tme': 'https://yandex.ru/search/?text=' + quote(query),
        'bing_site_tme': 'https://www.bing.com/search?q=' + quote(query),
        'duckduckgo_site_tme': 'https://duckduckgo.com/?q=' + quote(query),
    }


def _lookup_breach_phones_by_username(username: str) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()
    parser = getattr(universal_search, 'data_breaches', None)
    if parser is None or not hasattr(parser, 'search_by_username'):
        return candidates

    for variant in (username, username.lower()):
        result = parser.search_by_username(variant)
        if not isinstance(result, dict) or not result.get('found'):
            continue
        for item in result.get('data', []):
            if not isinstance(item, dict):
                continue
            phone = str(item.get('phone') or '').strip()
            if not phone:
                continue
            uname = str(item.get('username') or '').strip()
            platform = str(item.get('platform') or '').strip()
            key = (phone, uname.lower(), platform.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append({'phone': phone, 'username': uname, 'platform': platform})
    return candidates[:10]


def _ensure_report767_table() -> None:
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS report767_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                author TEXT,
                team TEXT NOT NULL,
                reports_done INTEGER NOT NULL,
                reports_plan INTEGER NOT NULL,
                numbers_to_check INTEGER NOT NULL,
                positives INTEGER NOT NULL,
                active INTEGER NOT NULL,
                vbros INTEGER NOT NULL,
                predlog INTEGER NOT NULL,
                soglasiy INTEGER NOT NULL
            )
            """
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_report767_team_created ON report767_entries(team, created_at)')
        conn.commit()
    finally:
        conn.close()


def _insert_report767_entry(entry: Dict[str, Any]) -> None:
    _ensure_report767_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO report767_entries (
                created_at, chat_id, user_id, username, author, team, reports_done, reports_plan,
                numbers_to_check, positives, active, vbros, predlog, soglasiy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get('created_at') or datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                entry.get('chat_id'),
                entry.get('user_id'),
                entry.get('username'),
                entry.get('author'),
                entry.get('team'),
                int(entry.get('reports_done', 0)),
                int(entry.get('reports_plan', 0)),
                int(entry.get('numbers_to_check', 0)),
                int(entry.get('positives', 0)),
                int(entry.get('active', 0)),
                int(entry.get('vbros', 0)),
                int(entry.get('predlog', 0)),
                int(entry.get('soglasiy', 0)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_report767_totals(team: Optional[str] = None) -> Dict[str, int]:
    _ensure_report767_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        query = (
            'SELECT COUNT(*), '
            'COALESCE(SUM(reports_done), 0), COALESCE(SUM(reports_plan), 0), '
            'COALESCE(SUM(numbers_to_check), 0), '
            'COALESCE(SUM(positives), 0), COALESCE(SUM(active), 0), '
            'COALESCE(SUM(vbros), 0), COALESCE(SUM(predlog), 0), COALESCE(SUM(soglasiy), 0) '
            'FROM report767_entries'
        )
        args: Tuple[Any, ...] = ()
        if team:
            query += ' WHERE team = ?'
            args = (team,)
        row = cur.execute(query, args).fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0)
    finally:
        conn.close()
    return {
        'entries': int(row[0] or 0),
        'reports_done': int(row[1] or 0),
        'reports_plan': int(row[2] or 0),
        'numbers_to_check': int(row[3] or 0),
        'positives': int(row[4] or 0),
        'active': int(row[5] or 0),
        'vbros': int(row[6] or 0),
        'predlog': int(row[7] or 0),
        'soglasiy': int(row[8] or 0),
    }


def _get_report767_team_rows() -> List[Dict[str, Any]]:
    _ensure_report767_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT
                team,
                COUNT(*) AS entries,
                COALESCE(SUM(reports_done), 0) AS reports_done,
                COALESCE(SUM(reports_plan), 0) AS reports_plan,
                COALESCE(SUM(numbers_to_check), 0) AS numbers_to_check,
                COALESCE(SUM(positives), 0) AS positives,
                COALESCE(SUM(active), 0) AS active,
                COALESCE(SUM(vbros), 0) AS vbros,
                COALESCE(SUM(predlog), 0) AS predlog,
                COALESCE(SUM(soglasiy), 0) AS soglasiy
            FROM report767_entries
            GROUP BY team
            ORDER BY team
            """
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                'team': str(row[0] or ''),
                'entries': int(row[1] or 0),
                'reports_done': int(row[2] or 0),
                'reports_plan': int(row[3] or 0),
                'numbers_to_check': int(row[4] or 0),
                'positives': int(row[5] or 0),
                'active': int(row[6] or 0),
                'vbros': int(row[7] or 0),
                'predlog': int(row[8] or 0),
                'soglasiy': int(row[9] or 0),
            }
        )
    return out


def _ensure_sources_table() -> None:
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                added_by_chat INTEGER,
                added_by_user INTEGER,
                added_by_username TEXT
            )
            """
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_source_items_name ON source_items(name)')
        conn.commit()
    finally:
        conn.close()


def _sources_list(limit: int = 200) -> List[Dict[str, Any]]:
    _ensure_sources_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT id, name, value, created_at FROM source_items ORDER BY id DESC LIMIT ?',
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {'id': int(row[0]), 'name': str(row[1] or ''), 'value': str(row[2] or ''), 'created_at': str(row[3] or '')}
        for row in rows
    ]


def _sources_add(name: str, value: str, user_id: int, username: str) -> None:
    _ensure_sources_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO source_items (name, value, created_at, added_by_chat, added_by_user, added_by_username)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                value.strip(),
                datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                0,
                int(user_id),
                username,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _sources_remove(source_id: int) -> int:
    _ensure_sources_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM source_items WHERE id = ?', (int(source_id),))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _ensure_source_orders_table() -> None:
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS source_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                donor_link TEXT NOT NULL,
                full_name TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                count INTEGER NOT NULL,
                vk_source TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_green_order(entry: Dict[str, Any]) -> None:
    _ensure_source_orders_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO source_orders (
                created_at, chat_id, user_id, username,
                donor_link, full_name, birth_date, count, vk_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get('created_at') or datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                entry.get('chat_id'),
                entry.get('user_id'),
                entry.get('username'),
                entry.get('donor_link'),
                entry.get('full_name'),
                entry.get('birth_date'),
                int(entry.get('count', 0)),
                entry.get('vk_source'),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _green_orders_list(limit: int = 100) -> List[Dict[str, Any]]:
    _ensure_source_orders_table()
    conn = sqlite3.connect(MINI_APP_REPORT_767_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, created_at, username, donor_link, full_name, birth_date, count, vk_source
            FROM source_orders
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            'id': int(row[0]),
            'created_at': str(row[1] or ''),
            'username': str(row[2] or ''),
            'donor_link': str(row[3] or ''),
            'full_name': str(row[4] or ''),
            'birth_date': str(row[5] or ''),
            'count': int(row[6] or 0),
            'vk_source': str(row[7] or ''),
        }
        for row in rows
    ]


def _enhance_photo_file(input_path: str, output_path: str) -> None:
    with Image.open(input_path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = ImageEnhance.Color(img).enhance(1.05)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=150, threshold=3))
        img.save(output_path, format='JPEG', quality=92, optimize=True)


def _normalize_phone_for_my_chats(raw: str) -> str:
    value = (raw or '').strip()
    if not value:
        raise ValueError('Укажи номер телефона.')
    digits = re.sub(r'\D', '', value)
    if len(digits) < 10:
        raise ValueError('Номер слишком короткий.')
    if len(digits) > 15:
        raise ValueError('Номер слишком длинный.')
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    return f'+{digits}'


def _format_telethon_sender(sender: Any, sender_id: int = 0) -> str:
    if sender is None:
        return f'id:{sender_id}' if sender_id else 'неизвестно'
    username = str(getattr(sender, 'username', '') or '').strip()
    if username:
        return f'@{username}'
    title = str(getattr(sender, 'title', '') or '').strip()
    if title:
        return title
    first_name = str(getattr(sender, 'first_name', '') or '').strip()
    last_name = str(getattr(sender, 'last_name', '') or '').strip()
    full_name = ' '.join(part for part in [first_name, last_name] if part).strip()
    if full_name:
        return full_name
    fallback_id = int(getattr(sender, 'id', 0) or 0)
    if fallback_id:
        return f'id:{fallback_id}'
    if sender_id:
        return f'id:{sender_id}'
    return 'неизвестно'


def _build_my_chats_phone_tokens(phone: str) -> List[str]:
    digits = re.sub(r'\D', '', phone)
    tokens: Set[str] = {phone, digits}
    if len(digits) == 11 and digits.startswith('7'):
        local = digits[1:]
        tokens.add('8' + local)
        tokens.add(f'+7{local}')
        tokens.add(f'+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}')
        tokens.add(f'8 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}')
    return sorted((t for t in tokens if t), key=len, reverse=True)


def _normalize_target_chat_link(raw: str) -> str:
    value = (raw or '').strip()
    if not value:
        raise ValueError('Укажи ссылку на чат или @username.')
    if value.startswith('@'):
        return value
    lowered = value.lower()
    for prefix in ('https://t.me/', 'http://t.me/', 't.me/', 'https://telegram.me/', 'http://telegram.me/', 'telegram.me/'):
        if lowered.startswith(prefix):
            suffix = value[len(prefix):].strip().split('?', 1)[0].strip('/')
            if not suffix:
                raise ValueError('Некорректная ссылка чата.')
            return f'https://t.me/{suffix}'
    raise ValueError('Нужна ссылка вида https://t.me/... или @username.')


async def _check_phone_in_my_chats_and_send_if_missing(phone: str, target_chat_link: str) -> Dict[str, Any]:
    if not _TELETHON_AVAILABLE:
        return {'ok': False, 'error': 'Модуль telethon не установлен.'}

    api_id = _parse_optional_int(os.getenv('TG_USER_API_ID', ''))
    api_hash = os.getenv('TG_USER_API_HASH', '').strip()
    session = os.getenv('TG_USER_SESSION', '').strip() or 'tg_user_session'
    if not api_id or not api_hash:
        return {'ok': False, 'error': 'Не настроены TG_USER_API_ID/TG_USER_API_HASH.'}

    dialogs_limit = _parse_optional_int(os.getenv('TG_USER_DIALOGS_LIMIT', '')) or 150
    found_limit = _parse_optional_int(os.getenv('TG_USER_FOUND_LIMIT', '')) or 8
    tokens = _build_my_chats_phone_tokens(phone)
    template = os.getenv('TG_USER_SEND_TEMPLATE', 'Номер {phone} не найден в моих чатах.').strip()
    try:
        message_text = template.format(phone=phone)
    except (KeyError, ValueError):
        message_text = template.replace('{phone}', phone)

    client = TelegramClient(session, int(api_id), api_hash)  # type: ignore[misc]
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {'ok': False, 'error': 'Telethon-сессия не авторизована.'}

        found: List[Dict[str, Any]] = []
        checked_dialogs = 0
        async for dialog in client.iter_dialogs(limit=dialogs_limit):
            checked_dialogs += 1
            title = (dialog.title or '').strip() or str(getattr(dialog.entity, 'id', '—'))
            username = str(getattr(dialog.entity, 'username', '') or '').strip()
            chat_ref = f'https://t.me/{username}' if username else 'приватный чат'
            for token in tokens:
                try:
                    items = await client.get_messages(dialog.entity, limit=1, search=token)
                except RPCError:
                    continue
                if not items:
                    continue
                msg = items[0]
                msg_date = getattr(msg, 'date', None)
                msg_date_str = msg_date.strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '—'
                sender_id = int(getattr(msg, 'sender_id', 0) or 0)
                sender_display = f'id:{sender_id}' if sender_id else 'неизвестно'
                with contextlib.suppress(RPCError, ValueError, TypeError):
                    sender = await msg.get_sender()
                    sender_display = _format_telethon_sender(sender, sender_id)
                found.append(
                    {
                        'title': title,
                        'chat_ref': chat_ref,
                        'message_id': int(getattr(msg, 'id', 0) or 0),
                        'token': token,
                        'message_date': msg_date_str,
                        'sender': sender_display,
                    }
                )
                break
            if len(found) >= found_limit:
                break

        if found:
            return {'ok': True, 'found': True, 'checked_dialogs': checked_dialogs, 'matches': found}

        entity = await client.get_entity(target_chat_link)
        sent = await client.send_message(entity, message_text)
        return {
            'ok': True,
            'found': False,
            'checked_dialogs': checked_dialogs,
            'sent': True,
            'target_chat_link': target_chat_link,
            'sent_message_id': int(getattr(sent, 'id', 0) or 0),
            'sent_text': message_text,
        }
    except RPCError as exc:
        return {'ok': False, 'error': f'Ошибка Telegram API: {exc}'}
    except Exception as exc:  # pragma: no cover
        return {'ok': False, 'error': f'Ошибка проверки чатов: {exc}'}
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


def _ensure_keyword_filters_table() -> None:
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS keyword_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                created_by_chat_id INTEGER NOT NULL,
                created_by_user_id INTEGER NOT NULL,
                created_by_username TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _normalize_filter_keyword(raw: str) -> str:
    value = (raw or '').strip().casefold()
    value = re.sub(r'\s+', ' ', value)
    if not value:
        raise ValueError('Пустое значение фильтра')
    if len(value) > MINI_APP_MAX_FILTER_KEYWORD_LEN:
        raise ValueError(f'Фильтр слишком длинный (макс. {MINI_APP_MAX_FILTER_KEYWORD_LEN} символов)')
    return value


def _keyword_filters_list() -> List[Dict[str, Any]]:
    _ensure_keyword_filters_table()
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            'SELECT id, keyword, created_at FROM keyword_filters ORDER BY id ASC'
        ).fetchall()
        return [{'id': row[0], 'keyword': row[1], 'created_at': row[2]} for row in rows]
    finally:
        conn.close()


def _keyword_filter_add(keyword: str, user_id: int, username: str) -> str:
    normalized = _normalize_filter_keyword(keyword)
    _ensure_keyword_filters_table()
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO keyword_filters (
                keyword, created_at, created_by_chat_id, created_by_user_id, created_by_username
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized,
                datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                0,
                int(user_id),
                username,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return normalized


def _keyword_filter_remove(raw: str) -> int:
    _ensure_keyword_filters_table()
    key = (raw or '').strip()
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    try:
        cur = conn.cursor()
        if key.isdigit():
            cur.execute('DELETE FROM keyword_filters WHERE id = ?', (int(key),))
        else:
            cur.execute('DELETE FROM keyword_filters WHERE keyword = ?', (_normalize_filter_keyword(key),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _ensure_sms_activation_table() -> None:
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sms_activations (
                local_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT,
                messenger TEXT NOT NULL,
                service_code TEXT NOT NULL,
                phone_number TEXT,
                provider_activation_id TEXT NOT NULL,
                provider_status TEXT,
                sms_code TEXT,
                state TEXT NOT NULL,
                next_sms_request_at INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                raw_last TEXT
            )
            """
        )
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_sms_activations_user_created ON sms_activations(user_id, created_at DESC)'
        )
        conn.commit()
    finally:
        conn.close()


def _sms_now_ts() -> int:
    return int(time.time())


def _sms_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def _sms_service_code(messenger_raw: str) -> Tuple[str, str]:
    messenger = str(messenger_raw or '').strip().lower()
    if messenger not in MINI_APP_SMS_SERVICE_CODES:
        raise ValueError('messenger must be one of: telegram, max, whatsapp')
    code = MINI_APP_SMS_SERVICE_CODES.get(messenger, '').strip()
    if not code:
        raise RuntimeError(f'Не задан код сервиса для {messenger}. Проверь SMS_ACTIVATE_SERVICE_* в .env')
    return messenger, code


def _sms_provider_error_text(raw: str) -> str:
    text = str(raw or '').strip()
    mapping = {
        'NO_NUMBERS': 'Нет доступных номеров у провайдера для выбранного сервиса.',
        'NO_BALANCE': 'Недостаточно баланса у провайдера виртуальных номеров.',
        'BAD_KEY': 'Неверный API-ключ провайдера SMS.',
        'ERROR_SQL': 'Внутренняя ошибка провайдера (ERROR_SQL).',
        'BAD_SERVICE': 'Провайдер не поддерживает выбранный сервис.',
        'BAD_ACTION': 'Провайдер не поддерживает запрошенное действие.',
        'NO_ACTIVATION': 'Активация не найдена у провайдера.',
    }
    if text in mapping:
        return mapping[text]
    if text.startswith('ERROR'):
        return f'Ошибка провайдера: {text}'
    return text or 'Неизвестная ошибка провайдера.'


def _sms_provider_request(action: str, **params: Any) -> str:
    api_key = (os.getenv('SMS_ACTIVATE_API_KEY') or '').strip()
    if not api_key:
        raise RuntimeError('SMS_ACTIVATE_API_KEY не настроен на сервере.')

    query: Dict[str, Any] = {'api_key': api_key, 'action': action}
    for key, value in params.items():
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        query[key] = value_str

    response = requests.get(MINI_APP_SMS_PROVIDER_BASE_URL, params=query, timeout=MINI_APP_SMS_REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f'HTTP {response.status_code} от провайдера SMS.')
    return (response.text or '').strip()


def _sms_provider_start_activation(service_code: str) -> Dict[str, Any]:
    raw = _sms_provider_request(
        'getNumber',
        service=service_code,
        country=MINI_APP_SMS_DEFAULT_COUNTRY,
        operator=MINI_APP_SMS_DEFAULT_OPERATOR or None,
    )
    if raw.startswith('ACCESS_NUMBER:'):
        parts = raw.split(':', 2)
        if len(parts) != 3:
            raise RuntimeError(f'Некорректный ответ провайдера: {raw}')
        return {'provider_activation_id': parts[1], 'phone_number': parts[2], 'raw': raw}
    raise RuntimeError(_sms_provider_error_text(raw))


def _sms_provider_get_status(provider_activation_id: str) -> Dict[str, Any]:
    raw = _sms_provider_request('getStatus', id=provider_activation_id)
    if raw.startswith('STATUS_OK:'):
        return {'provider_status': 'STATUS_OK', 'sms_code': raw.split(':', 1)[1], 'raw': raw}
    return {'provider_status': raw, 'sms_code': '', 'raw': raw}


def _sms_provider_set_status(provider_activation_id: str, status_code: int) -> Dict[str, Any]:
    raw = _sms_provider_request('setStatus', id=provider_activation_id, status=status_code)
    return {'provider_status': raw, 'raw': raw}


def _sms_activation_state(provider_status: str, has_code: bool, fallback: str = 'waiting_sms') -> str:
    status = str(provider_status or '').strip().upper()
    if has_code or status == 'STATUS_OK':
        return 'code_received'
    if status in {'STATUS_WAIT_CODE', 'STATUS_WAIT_RETRY', 'STATUS_WAIT_RESEND'}:
        return 'waiting_sms'
    if status in {'ACCESS_CANCEL', 'STATUS_CANCEL', 'CANCEL'}:
        return 'invalid'
    if status in {'ACCESS_ACTIVATION', 'STATUS_FINISH', 'FINISH'}:
        return 'success'
    return fallback


def _sms_activation_row_to_payload(row: sqlite3.Row) -> Dict[str, Any]:
    now = _sms_now_ts()
    next_request_at = int(row['next_sms_request_at'] or 0)
    retry_in = max(0, next_request_at - now)
    return {
        'local_id': row['local_id'],
        'messenger': row['messenger'],
        'service_code': row['service_code'],
        'phone_number': row['phone_number'],
        'provider_activation_id': row['provider_activation_id'],
        'provider_status': row['provider_status'] or '',
        'sms_code': row['sms_code'] or '',
        'state': row['state'],
        'can_request_more': retry_in <= 0,
        'retry_in_seconds': retry_in,
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def _sms_activation_get(local_id: str, user_id: int) -> Optional[sqlite3.Row]:
    _ensure_sms_activation_table()
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT local_id, user_id, username, messenger, service_code, phone_number,
                   provider_activation_id, provider_status, sms_code, state,
                   next_sms_request_at, created_at, updated_at, raw_last
            FROM sms_activations
            WHERE local_id = ? AND user_id = ?
            """,
            (local_id, int(user_id)),
        ).fetchone()
        return row
    finally:
        conn.close()


def _sms_activation_insert(
    user_id: int,
    username: str,
    messenger: str,
    service_code: str,
    phone_number: str,
    provider_activation_id: str,
    provider_status: str,
    raw_last: str,
) -> sqlite3.Row:
    _ensure_sms_activation_table()
    local_id = uuid.uuid4().hex
    now_iso = _sms_now_iso()
    next_sms_request_at = _sms_now_ts() + MINI_APP_SMS_MIN_RETRY_SECONDS
    state = _sms_activation_state(provider_status, has_code=False, fallback='number_acquired')
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sms_activations (
                local_id, user_id, username, messenger, service_code, phone_number,
                provider_activation_id, provider_status, sms_code, state,
                next_sms_request_at, created_at, updated_at, raw_last
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                local_id,
                int(user_id),
                username,
                messenger,
                service_code,
                phone_number,
                provider_activation_id,
                provider_status,
                '',
                state,
                int(next_sms_request_at),
                now_iso,
                now_iso,
                raw_last,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    row = _sms_activation_get(local_id, int(user_id))
    if row is None:
        raise RuntimeError('Не удалось создать запись активации SMS.')
    return row


def _sms_activation_update(
    local_id: str,
    user_id: int,
    *,
    provider_status: Optional[str] = None,
    sms_code: Optional[str] = None,
    state: Optional[str] = None,
    next_sms_request_at: Optional[int] = None,
    raw_last: Optional[str] = None,
) -> Optional[sqlite3.Row]:
    _ensure_sms_activation_table()
    conn = sqlite3.connect(MINI_APP_BOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        row = cur.execute(
            'SELECT * FROM sms_activations WHERE local_id = ? AND user_id = ?',
            (local_id, int(user_id)),
        ).fetchone()
        if not row:
            return None

        payload = {
            'provider_status': provider_status if provider_status is not None else row['provider_status'],
            'sms_code': sms_code if sms_code is not None else row['sms_code'],
            'state': state if state is not None else row['state'],
            'next_sms_request_at': int(next_sms_request_at) if next_sms_request_at is not None else int(row['next_sms_request_at'] or 0),
            'updated_at': _sms_now_iso(),
            'raw_last': raw_last if raw_last is not None else row['raw_last'],
        }
        cur.execute(
            """
            UPDATE sms_activations
            SET provider_status = ?, sms_code = ?, state = ?, next_sms_request_at = ?, updated_at = ?, raw_last = ?
            WHERE local_id = ? AND user_id = ?
            """,
            (
                payload['provider_status'],
                payload['sms_code'],
                payload['state'],
                payload['next_sms_request_at'],
                payload['updated_at'],
                payload['raw_last'],
                local_id,
                int(user_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return _sms_activation_get(local_id, int(user_id))


def _extract_telegram_init_data() -> str:
    init_data = (request.headers.get('X-Telegram-Init-Data') or '').strip()
    if init_data:
        return init_data

    init_data = (request.args.get('init_data') or '').strip()
    if init_data:
        return init_data

    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        return str(payload.get('init_data') or '').strip()
    return ''


def _is_local_address(value: str) -> bool:
    addr = (value or '').strip().lower()
    if not addr:
        return False
    if ',' in addr:
        addr = addr.split(',', 1)[0].strip()
    if addr in {'127.0.0.1', '::1', 'localhost'}:
        return True
    if addr.startswith('127.'):
        return True
    if addr.startswith('::ffff:127.'):
        return True
    return False


def _is_local_request() -> bool:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # If proxy provides client chain, require all hops to be local in dev mode.
        hops = [x.strip() for x in forwarded.split(',') if x.strip()]
        if not hops:
            return False
        return all(_is_local_address(h) for h in hops)
    return _is_local_address(request.remote_addr or '')


def _verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> Tuple[bool, Dict[str, Any], str]:
    if not init_data:
        return False, {}, 'init_data is missing'
    if not bot_token:
        return False, {}, 'TELEGRAM_BOT_TOKEN is not configured on server'

    items = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_value = items.pop('hash', '')
    if not hash_value:
        return False, {}, 'init_data hash is missing'

    data_check_string = '\n'.join(f'{k}={items[k]}' for k in sorted(items.keys()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, hash_value):
        return False, {}, 'init_data signature mismatch'

    auth_date_raw = items.get('auth_date', '')
    if auth_date_raw.isdigit():
        if int(time.time()) - int(auth_date_raw) > max_age_seconds:
            return False, {}, 'init_data is too old'

    parsed: Dict[str, Any] = dict(items)
    user_raw = parsed.get('user')
    if user_raw:
        try:
            parsed['user'] = json.loads(user_raw)
        except json.JSONDecodeError:
            parsed['user'] = {}
    return True, parsed, ''


def _mini_app_session() -> Dict[str, Any]:
    if _bool_env('MINI_APP_DEV_MODE', False):
        if not _bool_env('MINI_APP_DEV_ALLOW_REMOTE', False) and not _is_local_request():
            return {
                'authorized': False,
                'is_admin': False,
                'user_id': 0,
                'username': '',
                'first_name': '',
                'error': 'MINI_APP_DEV_MODE is allowed only for localhost requests',
            }
        dev_user_id = int(os.getenv('MINI_APP_DEV_USER_ID', '1') or '1')
        return {
            'authorized': True,
            'is_admin': _bool_env('MINI_APP_DEV_ADMIN', True),
            'user_id': dev_user_id,
            'username': os.getenv('MINI_APP_DEV_USERNAME', 'dev'),
            'first_name': os.getenv('MINI_APP_DEV_FIRST_NAME', 'Developer'),
            'error': '',
        }

    bot_token = (os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()
    init_data = _extract_telegram_init_data()
    ok, payload, error = _verify_telegram_init_data(init_data, bot_token)
    if not ok:
        # Optional public fallback mode: allow Mini App access for everyone
        # even without Telegram init-data. Useful for open web access.
        if _bool_env('MINI_APP_PUBLIC_ACCESS', False):
            return {
                'authorized': True,
                'is_admin': False,
                'user_id': 0,
                'username': 'guest',
                'first_name': 'Guest',
                'error': '',
            }
        return {
            'authorized': False,
            'is_admin': False,
            'user_id': 0,
            'username': '',
            'first_name': '',
            'error': error,
        }

    user_payload = payload.get('user') if isinstance(payload.get('user'), dict) else {}
    user_id = int(user_payload.get('id') or 0)
    username = str(user_payload.get('username') or '')
    first_name = str(user_payload.get('first_name') or '')

    admin_ids = _parse_int_set(os.getenv('TELEGRAM_ADMIN_USER_IDS', ''))
    if not admin_ids:
        admin_ids = {x for x in _parse_int_set(os.getenv('TELEGRAM_ADMIN_CHAT_IDS', '')) if x > 0}

    return {
        'authorized': True,
        'is_admin': user_id in admin_ids if admin_ids else False,
        'user_id': user_id,
        'username': username,
        'first_name': first_name,
        'error': '',
    }


def _require_mini_app_admin() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    session = _mini_app_session()
    if not session.get('authorized'):
        return None, (jsonify({'error': 'Unauthorized mini app session', 'details': session.get('error', '')}), 401)
    if not session.get('is_admin'):
        return None, (jsonify({'error': 'Admin access required'}), 403)
    return session, None


def _require_mini_app_auth() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    session = _mini_app_session()
    if not session.get('authorized'):
        return None, (jsonify({'error': 'Unauthorized mini app session', 'details': session.get('error', '')}), 401)
    return session, None


def _parse_fssp_input(raw: str) -> Dict[str, str]:
    parts = [p.strip() for p in (raw or '').split(';')]
    fio = parts[0] if parts else ''
    birth_date = parts[1] if len(parts) > 1 and parts[1] else ''
    region = parts[2] if len(parts) > 2 and parts[2] else '77'

    words = [w for w in fio.split() if w]
    if len(words) < 2:
        raise ValueError('Нужны минимум фамилия и имя')

    return {
        'fio': fio,
        'lastname': words[0],
        'firstname': words[1],
        'secondname': words[2] if len(words) > 2 else '',
        'birth_date': birth_date,
        'region': region,
    }


def _fssp_official_search(parsed: Dict[str, str], token: str) -> Dict[str, Any]:
    base_url = 'https://api-ip.fssprus.ru/api/v1.0'
    params = {
        'token': token,
        'region': parsed['region'],
        'lastname': parsed['lastname'],
        'firstname': parsed['firstname'],
    }
    if parsed.get('secondname'):
        params['secondname'] = parsed['secondname']

    birth = parsed.get('birth_date', '')
    if birth:
        if len(birth) == 10 and birth[4] == '-' and birth[7] == '-':
            y, m, d = birth.split('-')
            params['birthdate'] = f'{d}.{m}.{y}'
        else:
            params['birthdate'] = birth

    search_url = f'{base_url}/search/physical?{urlencode(params)}'
    search_resp = requests.get(search_url, timeout=15)
    if search_resp.status_code != 200:
        raise RuntimeError(f'FSSP API HTTP {search_resp.status_code}')

    search_data = search_resp.json()
    task_id = (search_data.get('response') or {}).get('task')
    if not task_id:
        return {'raw': search_data, 'items': []}

    result_params = {'token': token, 'task': task_id}
    result_url = f'{base_url}/result?{urlencode(result_params)}'
    last_data: Dict[str, Any] = {}
    for _ in range(6):
        result_resp = requests.get(result_url, timeout=15)
        if result_resp.status_code != 200:
            raise RuntimeError(f'FSSP result HTTP {result_resp.status_code}')
        last_data = result_resp.json()
        status = (last_data.get('response') or {}).get('status')
        if status == 0:
            break
        time.sleep(2)
    result = (last_data.get('response') or {}).get('result') or []
    return {'raw': last_data, 'items': result}


def _format_sender_label(sender: Any, sender_id: int) -> str:
    if sender is None:
        return f'user:{sender_id}'
    first_name = (getattr(sender, 'first_name', '') or '').strip()
    last_name = (getattr(sender, 'last_name', '') or '').strip()
    full_name = ' '.join([p for p in [first_name, last_name] if p]).strip()
    username = (getattr(sender, 'username', '') or '').strip()
    if full_name and username:
        return f'{full_name} (@{username})'
    if username:
        return f'@{username}'
    if full_name:
        return full_name
    return f'user:{sender_id}'


async def _analyze_telegram_group(chat_ref: str, limit: int, filters_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not _TELETHON_AVAILABLE:
        raise RuntimeError('Не установлен telethon. Установите зависимость и перезапустите сервис.')

    api_id_raw = os.getenv('TG_USER_API_ID', '').strip()
    api_hash = os.getenv('TG_USER_API_HASH', '').strip()
    session = os.getenv('TG_USER_SESSION', 'phoneinfoga_user').strip() or 'phoneinfoga_user'
    if not api_id_raw or not api_hash:
        raise RuntimeError('Не заданы TG_USER_API_ID и TG_USER_API_HASH в .env')

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError('TG_USER_API_ID должен быть целым числом') from exc

    filters_normalized = [str(item.get('keyword', '')).casefold() for item in filters_data if item.get('keyword')]
    keyword_hits = {kw: 0 for kw in filters_normalized}
    sender_stats: Dict[int, Dict[str, Any]] = {}
    scanned = 0
    text_messages = 0

    client = TelegramClient(session, api_id, api_hash)  # type: ignore[misc]
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError('Telethon-сессия не авторизована для TG_USER_SESSION.')

        entity = await client.get_entity(chat_ref)
        chat_title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or str(chat_ref)

        async for message in client.iter_messages(entity, limit=limit):
            scanned += 1
            sender_id = getattr(message, 'sender_id', None)
            if isinstance(sender_id, int):
                if sender_id not in sender_stats:
                    sender = await message.get_sender()
                    sender_stats[sender_id] = {'label': _format_sender_label(sender, sender_id), 'count': 0}
                sender_stats[sender_id]['count'] += 1

            text = (getattr(message, 'message', '') or '').strip()
            if not text:
                continue
            text_messages += 1
            text_cf = text.casefold()
            for keyword in filters_normalized:
                keyword_hits[keyword] += text_cf.count(keyword)
    except RPCError as exc:
        raise RuntimeError(f'Ошибка Telegram API: {exc}') from exc
    finally:
        await client.disconnect()

    top_senders = sorted(sender_stats.values(), key=lambda item: int(item.get('count', 0)), reverse=True)
    return {
        'chat': str(chat_title),
        'chat_ref': chat_ref,
        'scanned': scanned,
        'text_messages': text_messages,
        'top_senders': top_senders,
        'keyword_hits': keyword_hits,
    }


def _run_group_scan(chat_ref: str, limit: int, filters_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    return asyncio.run(_analyze_telegram_group(chat_ref, limit, filters_data))

# Flask Application
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'

universal_search = UniversalSearchSystem()

@app.route('/')
def index():
    """Main universal search interface"""
    return render_template('universal_search.html')


@app.route('/miniapp', strict_slashes=False)
def miniapp_index():
    """Telegram Mini App interface."""
    return render_template('mini_app.html')


@app.route('/api/telegram_username_search', methods=['POST'])
def api_telegram_username_search():
    """Telegram username search helper endpoint."""
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'username is required'}), 400

    search_types = data.get('search_types') or ['social', 'search_engines']
    if not isinstance(search_types, list):
        return jsonify({'error': 'search_types must be a list'}), 400

    result = _telegram_username_search(username, [str(item) for item in search_types])
    status = 200 if result.get('valid') else 400
    return jsonify(result), status


@app.route('/api/miniapp/session', methods=['GET'])
def api_miniapp_session():
    """Returns current mini app auth/admin state."""
    session = _mini_app_session()
    return jsonify({
        'authorized': bool(session.get('authorized')),
        'is_admin': bool(session.get('is_admin')),
        'user': {
            'id': int(session.get('user_id') or 0),
            'username': session.get('username') or '',
            'first_name': session.get('first_name') or '',
        },
        'error': session.get('error') or '',
    })


@app.route('/api/miniapp/me', methods=['GET'])
def api_miniapp_me():
    """Mini app identity + uptime (analog of /id and /uptime)."""
    session, error = _require_mini_app_auth()
    if error:
        return error
    now = int(time.time())
    return jsonify(
        {
            'authorized': True,
            'is_admin': bool(session.get('is_admin')),
            'user': {
                'id': int(session.get('user_id') or 0),
                'username': session.get('username') or '',
                'first_name': session.get('first_name') or '',
            },
            'uptime_seconds': max(0, now - MINI_APP_PROCESS_STARTED),
            'server_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )


@app.route('/api/miniapp/tg_search', methods=['POST'])
def api_miniapp_tg_search():
    """Search by Telegram username (analog of /tg)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    raw = str(data.get('username') or '').strip()
    if not raw:
        return jsonify({'error': 'username is required'}), 400
    try:
        username = _normalize_tg_username(raw)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(
        {
            'ok': True,
            'username': username,
            'links': _build_tg_nick_links(username),
            'phone_candidates': _lookup_breach_phones_by_username(username),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )


@app.route('/api/miniapp/tg_catalog/search', methods=['POST'])
def api_miniapp_tg_catalog_search():
    """Search in tg_catalog DB (analog of /tgcat)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if not _TG_CATALOG_AVAILABLE:
        return jsonify({'error': 'tg_catalog_db module is unavailable on server'}), 400

    data = request.get_json(silent=True) or {}
    query = str(data.get('query') or '').strip()
    source_type = str(data.get('source_type') or 'all').strip().lower()
    limit = _parse_optional_int(data.get('limit')) or 8
    offset = _parse_optional_int(data.get('offset')) or 0
    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        result = search_catalog(query=query, source_type=source_type, limit=limit, offset=offset)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(result)


@app.route('/api/miniapp/tg_catalog/stats', methods=['GET'])
def api_miniapp_tg_catalog_stats():
    """Catalog stats (analog of admin DB status for tg catalog)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if not _TG_CATALOG_AVAILABLE:
        return jsonify({'error': 'tg_catalog_db module is unavailable on server'}), 400
    return jsonify(catalog_stats())


@app.route('/api/miniapp/tg_catalog/top', methods=['GET'])
def api_miniapp_tg_catalog_top():
    """Top chats/channels (analog of /topchannels and /topchats)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if not _TG_CATALOG_AVAILABLE:
        return jsonify({'error': 'tg_catalog_db module is unavailable on server'}), 400

    source_type = (request.args.get('source_type') or 'all').strip().lower()
    limit = _parse_optional_int(request.args.get('limit')) or 8
    try:
        items = top_catalog(source_type=source_type, limit=limit)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'source_type': source_type, 'items': items})


@app.route('/api/miniapp/tg_catalog/random', methods=['GET'])
def api_miniapp_tg_catalog_random():
    """Random chat/channel (analog of /randomtg)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if not _TG_CATALOG_AVAILABLE:
        return jsonify({'error': 'tg_catalog_db module is unavailable on server'}), 400

    source_type = (request.args.get('source_type') or 'all').strip().lower()
    try:
        item = random_catalog(source_type=source_type)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'source_type': source_type, 'item': item or {}})


@app.route('/api/miniapp/my_chats_phone', methods=['POST'])
def api_miniapp_my_chats_phone():
    """Check number in own Telegram dialogs and optionally send to target chat."""
    _, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    phone_raw = str(data.get('phone') or '').strip()
    if not phone_raw:
        return jsonify({'error': 'phone is required'}), 400

    try:
        phone = _normalize_phone_for_my_chats(phone_raw)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    target_chat = str(data.get('target_chat') or os.getenv('TG_USER_TARGET_CHAT', '')).strip()
    if not target_chat:
        return jsonify({'error': 'target_chat is required (or set TG_USER_TARGET_CHAT)'}), 400
    try:
        target_chat = _normalize_target_chat_link(target_chat)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    result = asyncio.run(_check_phone_in_my_chats_and_send_if_missing(phone=phone, target_chat_link=target_chat))
    status = 200 if result.get('ok') else 400
    return jsonify(result), status


@app.route('/api/miniapp/sms_activation/start', methods=['POST'])
def api_miniapp_sms_activation_start():
    """Start virtual number activation for messenger registration."""
    session, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    messenger_raw = str(data.get('messenger') or '').strip()
    try:
        messenger, service_code = _sms_service_code(messenger_raw)
        provider = _sms_provider_start_activation(service_code=service_code)
        row = _sms_activation_insert(
            user_id=int(session.get('user_id') or 0),
            username=str(session.get('username') or ''),
            messenger=messenger,
            service_code=service_code,
            phone_number=str(provider.get('phone_number') or ''),
            provider_activation_id=str(provider.get('provider_activation_id') or ''),
            provider_status='STATUS_WAIT_CODE',
            raw_last=str(provider.get('raw') or ''),
        )
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify(
        {
            'ok': True,
            'action': 'start',
            'message': 'Номер получен. Можно ожидать SMS или нажать "Получить SMS".',
            'activation': _sms_activation_row_to_payload(row),
        }
    )


@app.route('/api/miniapp/sms_activation/poll', methods=['POST'])
def api_miniapp_sms_activation_poll():
    """Poll provider for SMS code."""
    session, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    local_id = str(data.get('activation_id') or '').strip()
    if not local_id:
        return jsonify({'error': 'activation_id is required'}), 400

    user_id = int(session.get('user_id') or 0)
    row = _sms_activation_get(local_id, user_id)
    if row is None:
        return jsonify({'error': 'Активация не найдена.'}), 404

    try:
        status_data = _sms_provider_get_status(str(row['provider_activation_id']))
    except (RuntimeError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    provider_status = str(status_data.get('provider_status') or '')
    sms_code = str(status_data.get('sms_code') or '').strip()
    updated = _sms_activation_update(
        local_id,
        user_id,
        provider_status=provider_status,
        sms_code=sms_code if sms_code else None,
        state=_sms_activation_state(provider_status, has_code=bool(sms_code), fallback='waiting_sms'),
        raw_last=str(status_data.get('raw') or provider_status),
    )
    if updated is None:
        return jsonify({'error': 'Активация не найдена после обновления.'}), 404

    message = 'Код пока не поступил.'
    if sms_code:
        message = 'Код SMS получен.'
    return jsonify({'ok': True, 'action': 'poll', 'message': message, 'activation': _sms_activation_row_to_payload(updated)})


@app.route('/api/miniapp/sms_activation/request_more', methods=['POST'])
def api_miniapp_sms_activation_request_more():
    """Request one more SMS for existing activation (with cooldown)."""
    session, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    local_id = str(data.get('activation_id') or '').strip()
    if not local_id:
        return jsonify({'error': 'activation_id is required'}), 400

    user_id = int(session.get('user_id') or 0)
    row = _sms_activation_get(local_id, user_id)
    if row is None:
        return jsonify({'error': 'Активация не найдена.'}), 404

    now_ts = _sms_now_ts()
    next_ts = int(row['next_sms_request_at'] or 0)
    if now_ts < next_ts:
        retry_in = next_ts - now_ts
        return jsonify({'error': f'Повторный запрос доступен через {retry_in} сек.', 'retry_in_seconds': retry_in}), 429

    try:
        provider = _sms_provider_set_status(str(row['provider_activation_id']), status_code=3)
    except (RuntimeError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    provider_status = str(provider.get('provider_status') or '')
    updated = _sms_activation_update(
        local_id,
        user_id,
        provider_status=provider_status,
        state='request_more_sent',
        next_sms_request_at=now_ts + MINI_APP_SMS_MIN_RETRY_SECONDS,
        raw_last=str(provider.get('raw') or provider_status),
    )
    if updated is None:
        return jsonify({'error': 'Активация не найдена после обновления.'}), 404

    return jsonify(
        {
            'ok': True,
            'action': 'request_more',
            'message': 'Запрос на повторное SMS отправлен провайдеру.',
            'activation': _sms_activation_row_to_payload(updated),
        }
    )


@app.route('/api/miniapp/sms_activation/success', methods=['POST'])
def api_miniapp_sms_activation_success():
    """Mark activation as successful."""
    session, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    local_id = str(data.get('activation_id') or '').strip()
    if not local_id:
        return jsonify({'error': 'activation_id is required'}), 400

    user_id = int(session.get('user_id') or 0)
    row = _sms_activation_get(local_id, user_id)
    if row is None:
        return jsonify({'error': 'Активация не найдена.'}), 404

    try:
        provider = _sms_provider_set_status(str(row['provider_activation_id']), status_code=6)
    except (RuntimeError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    provider_status = str(provider.get('provider_status') or '')
    updated = _sms_activation_update(
        local_id,
        user_id,
        provider_status=provider_status,
        state='success',
        raw_last=str(provider.get('raw') or provider_status),
    )
    if updated is None:
        return jsonify({'error': 'Активация не найдена после обновления.'}), 404

    return jsonify(
        {
            'ok': True,
            'action': 'success',
            'message': 'Активация завершена успешно.',
            'activation': _sms_activation_row_to_payload(updated),
        }
    )


@app.route('/api/miniapp/sms_activation/invalid', methods=['POST'])
def api_miniapp_sms_activation_invalid():
    """Mark purchased number as invalid and cancel activation."""
    session, error = _require_mini_app_auth()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    local_id = str(data.get('activation_id') or '').strip()
    if not local_id:
        return jsonify({'error': 'activation_id is required'}), 400

    user_id = int(session.get('user_id') or 0)
    row = _sms_activation_get(local_id, user_id)
    if row is None:
        return jsonify({'error': 'Активация не найдена.'}), 404

    try:
        provider = _sms_provider_set_status(str(row['provider_activation_id']), status_code=8)
    except (RuntimeError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    provider_status = str(provider.get('provider_status') or '')
    updated = _sms_activation_update(
        local_id,
        user_id,
        provider_status=provider_status,
        state='invalid',
        raw_last=str(provider.get('raw') or provider_status),
    )
    if updated is None:
        return jsonify({'error': 'Активация не найдена после обновления.'}), 404

    return jsonify(
        {
            'ok': True,
            'action': 'invalid',
            'message': 'Номер отмечен как невалидный.',
            'activation': _sms_activation_row_to_payload(updated),
        }
    )


TARGET_SEARCH_TYPES: List[Dict[str, str]] = [
    {'type': 'phone', 'label_ru': 'Телефон'},
    {'type': 'full_name', 'label_ru': 'ФИО'},
    {'type': 'username', 'label_ru': 'Никнейм'},
    {'type': 'email', 'label_ru': 'Email'},
    {'type': 'telegram', 'label_ru': 'Telegram'},
    {'type': 'whatsapp', 'label_ru': 'WhatsApp'},
    {'type': 'instagram', 'label_ru': 'Instagram'},
    {'type': 'vk', 'label_ru': 'ВКонтакте'},
    {'type': 'tiktok', 'label_ru': 'TikTok'},
    {'type': 'facebook', 'label_ru': 'Facebook'},
    {'type': 'car_plate', 'label_ru': 'Госномер авто'},
    {'type': 'passport', 'label_ru': 'Паспорт'},
    {'type': 'inn', 'label_ru': 'ИНН'},
    {'type': 'ip_address', 'label_ru': 'IP-адрес'},
]


TARGET_API_TYPE_MAP: Dict[str, str] = {
    'phone': 'phone',
    'full_name': 'name',
    'username': 'username',
    'email': 'email',
    'telegram': 'telegram_id',
    'whatsapp': 'full_text',
    'instagram': 'full_text',
    'vk': 'full_text',
    'tiktok': 'full_text',
    'facebook': 'full_text',
    'car_plate': 'plate_number',
    'passport': 'passport',
    'inn': 'inn',
    'ip_address': 'full_text',
}

TARGET_API_ALLOWED_TYPES: Set[str] = {
    'full_text',
    'phone',
    'name',
    'address',
    'email',
    'plate_number',
    'vin',
    'passport',
    'snils',
    'inn',
    'username',
    'password',
    'telegram_id',
    'tg_msg',
}


def _target_type_label(search_type: str) -> str:
    normalized = str(search_type or '').strip().lower()
    for row in TARGET_SEARCH_TYPES:
        if row.get('type') == normalized:
            return str(row.get('label_ru') or normalized)
    return normalized or 'Поиск'


def _target_to_api_type(search_type: str) -> str:
    normalized = str(search_type or '').strip().lower()
    mapped = TARGET_API_TYPE_MAP.get(normalized) or normalized
    if mapped in TARGET_API_ALLOWED_TYPES:
        return mapped
    return 'full_text'


def _target_api_base_url() -> str:
    configured = str(os.getenv('TARGET_SEARCH_BASE_URL') or os.getenv('INFOTRACK_BASE_URL') or '').strip()
    if configured:
        return configured.rstrip('/')
    return 'https://datatech.work/public-api/data'


def _target_api_key() -> str:
    return str(
        os.getenv('TARGET_SEARCH_API_KEY')
        or os.getenv('INFOTRACK_API_KEY')
        or ''
    ).strip()


def _target_api_timeout_seconds() -> int:
    raw = str(os.getenv('TARGET_SEARCH_TIMEOUT') or '25').strip()
    try:
        return max(5, min(int(raw), 90))
    except ValueError:
        return 25


def _target_api_error_payload(resp: requests.Response) -> Tuple[str, Dict[str, Any]]:
    details: Dict[str, Any] = {'status': int(resp.status_code)}
    try:
        payload = resp.json()
    except Exception:
        payload = {'raw': resp.text[:1000]}
    details['response'] = payload

    message = f'ITP API error HTTP {resp.status_code}'
    if isinstance(payload, dict):
        err = payload.get('error')
        if isinstance(err, dict):
            message = str(err.get('message') or err.get('key') or message)
        elif isinstance(err, str):
            message = err
    return message, details


def _target_itp_search(search_options: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, Any]], Optional[str], int, Dict[str, Any]]:
    key = _target_api_key()
    if not key:
        return None, 'Не настроен API ключ целевой системы (TARGET_SEARCH_API_KEY / INFOTRACK_API_KEY).', 500, {}

    base_url = _target_api_base_url()
    url = f'{base_url}/search'
    headers = {
        'x-api-key': key,
        'Content-Type': 'application/json',
    }
    body = {'searchOptions': search_options}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=_target_api_timeout_seconds())
    except requests.RequestException as exc:
        return None, f'Ошибка запроса к ITP API: {exc}', 502, {}

    if not resp.ok:
        message, details = _target_api_error_payload(resp)
        return None, message, int(resp.status_code or 502), details

    try:
        payload = resp.json()
    except ValueError:
        return None, 'ITP API вернул невалидный JSON.', 502, {'raw': resp.text[:1500]}

    return payload if isinstance(payload, dict) else {'data': payload}, None, 200, {}


def _target_itp_balance() -> Tuple[Optional[Dict[str, Any]], Optional[str], int, Dict[str, Any]]:
    key = _target_api_key()
    if not key:
        return None, 'Не настроен API ключ целевой системы (TARGET_SEARCH_API_KEY / INFOTRACK_API_KEY).', 500, {}

    base_url = _target_api_base_url()
    url = f'{base_url}/balance'
    headers = {'x-api-key': key}

    try:
        resp = requests.get(url, headers=headers, timeout=_target_api_timeout_seconds())
    except requests.RequestException as exc:
        return None, f'Ошибка запроса к ITP API: {exc}', 502, {}

    if not resp.ok:
        message, details = _target_api_error_payload(resp)
        return None, message, int(resp.status_code or 502), details

    try:
        payload = resp.json()
    except ValueError:
        return None, 'ITP API вернул невалидный JSON.', 502, {'raw': resp.text[:1500]}

    return payload if isinstance(payload, dict) else {'data': payload}, None, 200, {}


def _target_flatten_api_data(api_payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    data = api_payload.get('data')
    if not isinstance(data, dict):
        return [], []

    items: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    max_items_raw = str(os.getenv('TARGET_SEARCH_MAX_ITEMS') or '250').strip()
    try:
        max_items = max(50, min(int(max_items_raw), 1000))
    except ValueError:
        max_items = 250

    for source_name, source_payload in data.items():
        source_rows: List[Any] = []
        if isinstance(source_payload, dict):
            maybe_rows = source_payload.get('data')
            if isinstance(maybe_rows, list):
                source_rows = maybe_rows
        elif isinstance(source_payload, list):
            source_rows = source_payload

        sources.append({
            'source': str(source_name),
            'count': len(source_rows),
        })

        for row in source_rows:
            if len(items) >= max_items:
                break
            if isinstance(row, dict):
                row_payload = dict(row)
            else:
                row_payload = {'value': row}
            items.append(
                {
                    'source': str(source_name),
                    'data': row_payload,
                }
            )

        if len(items) >= max_items:
            break

    sources.sort(key=lambda x: int(x.get('count') or 0), reverse=True)
    return items, sources


@app.route('/api/miniapp/itp/types', methods=['GET'])
def api_miniapp_itp_types():
    """Returns 14 target search functions with Russian names."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    rows: List[Dict[str, str]] = []
    for row in TARGET_SEARCH_TYPES:
        search_type = str(row.get('type') or '')
        rows.append(
            {
                'type': search_type,
                'label_ru': str(row.get('label_ru') or search_type),
                'api_type': _target_to_api_type(search_type),
            }
        )
    return jsonify({'ok': True, 'items': rows, 'count': len(rows)})


@app.route('/api/miniapp/itp/search', methods=['POST'])
def api_miniapp_itp_search():
    """Target search endpoint via InfoTrackPeople API (multi-option compatibility)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    search_options_raw = data.get('search_options') if isinstance(data.get('search_options'), list) else []

    normalized_options: List[Dict[str, str]] = []
    used_types: List[str] = []
    used_queries: List[str] = []

    for item in search_options_raw:
        if not isinstance(item, dict):
            continue
        search_type = str(item.get('type') or '').strip().lower()
        query = str(item.get('query') or '').strip()
        if not query:
            continue
        normalized_options.append({'type': _target_to_api_type(search_type), 'query': query})
        used_types.append(search_type or 'full_text')
        used_queries.append(query)

    if not normalized_options:
        search_type = str(data.get('search_type') or 'phone').strip().lower()
        query = str(data.get('query') or '').strip()
        if not query:
            return jsonify({'error': 'query is required'}), 400
        normalized_options = [{'type': _target_to_api_type(search_type), 'query': query}]
        used_types = [search_type]
        used_queries = [query]

    api_payload, api_error, status_code, api_error_details = _target_itp_search(normalized_options)
    if api_error:
        return jsonify(
            {
                'error': api_error,
                'provider': 'Целевая система поиска',
                'details': api_error_details,
            }
        ), status_code

    api_payload = api_payload or {}
    items, sources = _target_flatten_api_data(api_payload)
    records = int(api_payload.get('records') or len(items))
    search_id = api_payload.get('searchId')

    return jsonify(
        {
            'ok': True,
            'provider': 'Целевая система поиска',
            'api_provider': 'InfoTrackPeople',
            'base_url': _target_api_base_url(),
            'search_type': used_types[0] if used_types else 'phone',
            'search_type_label': _target_type_label(used_types[0] if used_types else 'phone'),
            'query': used_queries[0] if used_queries else '',
            'search_options': normalized_options,
            'records': records,
            'search_id': search_id,
            'sources': sources,
            'items': items,
            'items_count': len(items),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )


@app.route('/api/miniapp/itp/search/<string:search_type>', methods=['POST'])
def api_miniapp_itp_search_by_type(search_type: str):
    """Target search endpoint for single search type via InfoTrackPeople API."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    query = str(data.get('query') or '').strip()
    if not query:
        return jsonify({'error': 'query is required'}), 400
    normalized_type = str(search_type or '').strip().lower()
    api_type = _target_to_api_type(normalized_type)

    api_payload, api_error, status_code, api_error_details = _target_itp_search([{'type': api_type, 'query': query}])
    if api_error:
        return jsonify(
            {
                'error': api_error,
                'provider': 'Целевая система поиска',
                'details': api_error_details,
            }
        ), status_code

    api_payload = api_payload or {}
    items, sources = _target_flatten_api_data(api_payload)
    records = int(api_payload.get('records') or len(items))
    search_id = api_payload.get('searchId')

    return jsonify(
        {
            'ok': True,
            'provider': 'Целевая система поиска',
            'api_provider': 'InfoTrackPeople',
            'base_url': _target_api_base_url(),
            'search_type': normalized_type,
            'search_type_label': _target_type_label(normalized_type),
            'api_type': api_type,
            'query': query,
            'records': records,
            'search_id': search_id,
            'sources': sources,
            'items': items,
            'items_count': len(items),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )


@app.route('/api/miniapp/itp/balance', methods=['GET'])
def api_miniapp_itp_balance():
    """Target search balance endpoint via InfoTrackPeople API."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    payload, api_error, status_code, api_error_details = _target_itp_balance()
    if api_error:
        return jsonify(
            {
                'error': api_error,
                'provider': 'Целевая система поиска',
                'details': api_error_details,
            }
        ), status_code

    payload = payload or {}
    return jsonify(
        {
            'ok': True,
            'provider': 'Целевая система поиска',
            'api_provider': 'InfoTrackPeople',
            'base_url': _target_api_base_url(),
            'status': 'OK',
            'available_types': len(TARGET_SEARCH_TYPES),
            'balance': payload.get('balance'),
            'deactivated_at': payload.get('deactivatedAt'),
            'note': 'Баланс и поиск получены через ITP API.',
        }
    )


@app.route('/api/miniapp/phone_search', methods=['POST'])
def api_miniapp_phone_search():
    """Mini app wrapper for phone search."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    phone = str(data.get('phone') or '').strip()
    if not phone:
        return jsonify({'error': 'phone is required'}), 400

    search_types = data.get('search_types') or ['basic', 'owner', 'data_breaches']
    if not isinstance(search_types, list):
        return jsonify({'error': 'search_types must be a list'}), 400

    result = universal_search.universal_phone_search(phone, [str(x) for x in search_types])
    return jsonify(result)


@app.route('/api/miniapp/ip_lookup', methods=['GET'])
def api_miniapp_ip_lookup():
    """Mini app wrapper for IP lookup."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    ip = (request.args.get('ip') or '').strip()
    if not ip:
        return jsonify({'error': 'ip is required'}), 400
    payload = universal_search.xosint.ip_lookup(ip)
    status = 200 if payload.get('valid', True) else 400
    return jsonify(payload), status


@app.route('/api/miniapp/email_check', methods=['GET'])
def api_miniapp_email_check():
    """Mini app wrapper for email checks."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    email = (request.args.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'email is required'}), 400
    return jsonify(universal_search.xosint.email_check(email))


@app.route('/api/miniapp/fssp_search', methods=['POST'])
def api_miniapp_fssp_search():
    """Mini app wrapper for FSSP search."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    token = (os.getenv('FSSP_API_TOKEN') or '').strip()
    if not token:
        return jsonify({'error': 'FSSP_API_TOKEN is not configured on server'}), 400

    data = request.get_json(silent=True) or {}
    query = str(data.get('query') or '').strip()
    if not query:
        fio = str(data.get('fio') or '').strip()
        birth_date = str(data.get('birth_date') or '').strip()
        region = str(data.get('region') or '').strip() or '77'
        if not fio:
            return jsonify({'error': 'query or fio is required'}), 400
        query = f'{fio};{birth_date};{region}'

    try:
        parsed = _parse_fssp_input(query)
        result = _fssp_official_search(parsed, token)
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'parsed': parsed,
        'count': len(result.get('items') or []),
        'items': result.get('items') or [],
        'raw': result.get('raw') or {},
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    })

@app.route('/api/phone_search', methods=['POST'])
def api_phone_search():
    """Phone search API"""
    data = request.get_json()
    
    if not data or 'phone' not in data:
        return jsonify({'error': 'Phone number is required'}), 400
    
    phone_number = data['phone']
    search_types = data.get('search_types', ['basic', 'google', 'social'])
    
    result = universal_search.universal_phone_search(phone_number, search_types)
    return jsonify(result)

@app.route('/api/photo_search', methods=['POST'])
def api_photo_search():
    """Photo search API"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and universal_search.allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        search_types = request.form.getlist('search_types')
        if not search_types:
            search_types = ['metadata', 'google', 'yandex']
        
        result = universal_search.universal_photo_search(filepath, search_types)
        result['filename'] = filename
        result['unique_filename'] = unique_filename
        
        return jsonify(result)
    
    return jsonify({'error': 'File type not allowed'}), 400

@app.route('/api/sources', methods=['GET'])
def api_sources():
    """Get available search sources"""
    return jsonify({
        'phone_search_engines': list(universal_search.phone_search_engines.keys()),
        'social_platforms': list(universal_search.social_platforms.keys()),
        'photo_search_engines': list(universal_search.photo_search_engines.keys()),
        'facial_services': list(universal_search.facial_services.keys()),
        'api_services': list(universal_search.api_services.keys()),
        'local_databases': ['data_breaches', 'business_directory'],
        'osint_tools': ['phone_check', 'ip_lookup', 'email_check', 'xosint_phone', 'directory_search', 'directory_stats'],
        'phone_search_types': ['basic', 'search_engines', 'social', 'api', 'data_breaches', 'xosint_phone', 'owner', 'all'],
        'allowed_extensions': list(universal_search.allowed_extensions)
    })


@app.route('/api/phone_check', methods=['GET'])
def api_phone_check():
    """Fast phone check endpoint.

    Returns:
    - validation + formatting
    - basic phone info
    - optional breach summary (redacted)
    - optional external vendor lookups (requires API keys)

    Query params:
    - phone: required
    - breaches: (true/false), default true
    - external: (true/false), default false
    """
    phone = (request.args.get('phone') or '').strip()
    if not phone:
        return jsonify({'error': 'Phone number is required'}), 400

    breaches_flag = (request.args.get('breaches') or 'true').strip().lower() in {'1', 'true', 'yes', 'y'}
    external_flag = (request.args.get('external') or 'false').strip().lower() in {'1', 'true', 'yes', 'y'}

    parsed = universal_search.validate_and_parse(phone)
    if not parsed:
        return jsonify({'error': 'Invalid phone number', 'input': phone, 'valid': False}), 400

    formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    payload = {
        'input': phone,
        'formatted': formatted,
        'valid': True,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'results': {
            'basic': universal_search.get_basic_phone_info(parsed),
        },
    }

    if breaches_flag:
        payload['results']['data_breaches'] = universal_search.data_breaches_search(formatted)

    if external_flag:
        payload['results']['xosint_phone'] = universal_search.xosint.phone_external_lookup(formatted)

    return jsonify(payload)


@app.route('/api/ip_lookup', methods=['GET'])
def api_ip_lookup():
    """IP lookup (safe OSINT)."""
    ip = (request.args.get('ip') or '').strip()
    if not ip:
        return jsonify({'error': 'IP is required'}), 400

    payload = universal_search.xosint.ip_lookup(ip)
    if payload.get('valid') is False:
        return jsonify(payload), 400
    return jsonify(payload)


@app.route('/api/email_check', methods=['GET'])
def api_email_check():
    """Basic email checks (safe OSINT)."""
    email = (request.args.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    return jsonify(universal_search.xosint.email_check(email))


@app.route('/api/directory/search', methods=['GET'])
def api_directory_search():
    """Search business directory by phone/name/address or across all fields."""
    query = (request.args.get('query') or '').strip()
    field = (request.args.get('field') or 'all').strip().lower()
    limit = request.args.get('limit', '50')
    offset = request.args.get('offset', '0')

    if not query:
        return jsonify({'error': 'query is required'}), 400

    result = search_records(query=query, field=field, limit=limit, offset=offset)
    return jsonify(result)


@app.route('/api/directory/stats', methods=['GET'])
def api_directory_stats():
    """Stats by city and category for the business directory."""
    top_n = request.args.get('top', '20')
    result = stats_by_city_and_category(top_n=top_n)
    return jsonify(result)


@app.route('/api/miniapp/photo_search', methods=['POST'])
def api_miniapp_photo_search():
    """Mini app wrapper for photo search."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file and universal_search.allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        search_types = request.form.getlist('search_types')
        if not search_types:
            search_types = ['metadata', 'search_engines']

        result = universal_search.universal_photo_search(filepath, search_types)
        result['filename'] = filename
        result['unique_filename'] = unique_filename
        return jsonify(result)

    return jsonify({'error': 'File type not allowed'}), 400


@app.route('/api/miniapp/photo_enhance', methods=['POST'])
def api_miniapp_photo_enhance():
    """Enhance photo quality (analog of photo enhance mode in legacy bot)."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not universal_search.allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    src_name = secure_filename(file.filename)
    src_unique = f"{uuid.uuid4().hex}_{src_name}"
    src_path = os.path.join(app.config['UPLOAD_FOLDER'], src_unique)
    enhanced_unique = f"{uuid.uuid4().hex}_enhanced.jpg"
    enhanced_path = os.path.join(app.config['UPLOAD_FOLDER'], enhanced_unique)
    file.save(src_path)
    try:
        _enhance_photo_file(src_path, enhanced_path)
    except Exception as exc:
        return jsonify({'error': f'Enhance failed: {exc}'}), 400

    return jsonify(
        {
            'ok': True,
            'original_file': src_name,
            'enhanced_file': enhanced_unique,
            'download_url': f'/api/miniapp/uploads/{enhanced_unique}',
        }
    )


@app.route('/api/miniapp/uploads/<path:filename>', methods=['GET'])
def api_miniapp_uploads(filename: str):
    """Download generated upload by filename."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    safe_name = os.path.basename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name, as_attachment=True)


@app.route('/api/miniapp/admin/filters', methods=['GET'])
def api_miniapp_admin_filters():
    """List keyword filters for group analytics."""
    _, error = _require_mini_app_admin()
    if error:
        return error
    return jsonify({'items': _keyword_filters_list()})


@app.route('/api/miniapp/admin/filters', methods=['POST'])
def api_miniapp_admin_filters_add():
    """Add keyword filter."""
    session, error = _require_mini_app_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    keyword = str(data.get('keyword') or '').strip()
    if not keyword:
        return jsonify({'error': 'keyword is required'}), 400

    try:
        normalized = _keyword_filter_add(
            keyword=keyword,
            user_id=int(session.get('user_id') or 0),
            username=str(session.get('username') or ''),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Такой фильтр уже существует'}), 409

    return jsonify({'ok': True, 'keyword': normalized})


@app.route('/api/miniapp/admin/filters/remove', methods=['POST'])
def api_miniapp_admin_filters_remove():
    """Remove keyword filter by id or text."""
    _, error = _require_mini_app_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    value = str(data.get('value') or '').strip()
    if not value:
        return jsonify({'error': 'value is required'}), 400

    try:
        removed = _keyword_filter_remove(value)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'ok': True, 'removed': int(removed)})


@app.route('/api/miniapp/admin/tg_group_stats', methods=['POST'])
def api_miniapp_admin_tg_group_stats():
    """Analyze Telegram group messages and keyword hit counters."""
    _, error = _require_mini_app_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    chat_ref = str(data.get('chat_ref') or '').strip()
    if not chat_ref:
        return jsonify({'error': 'chat_ref is required'}), 400

    limit_raw = data.get('limit', MINI_APP_DEFAULT_GROUP_SCAN_LIMIT)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, MINI_APP_MAX_GROUP_SCAN_LIMIT))

    filters_data = _keyword_filters_list()
    try:
        result = _run_group_scan(chat_ref=chat_ref, limit=limit, filters_data=filters_data)
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'ok': True,
        'limit': limit,
        'filters_count': len(filters_data),
        'result': result,
    })


@app.route('/api/miniapp/report767/submit', methods=['POST'])
def api_miniapp_report767_submit():
    """Submit report 767 entry."""
    session, error = _require_mini_app_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    team = str(data.get('team') or '').strip()
    if not team:
        return jsonify({'error': 'team is required'}), 400

    try:
        entry = {
            'created_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
            'chat_id': 0,
            'user_id': int(session.get('user_id') or 0),
            'username': str(session.get('username') or ''),
            'author': str(data.get('author') or session.get('username') or ''),
            'team': team,
            'reports_done': int(data.get('reports_done', 0) or 0),
            'reports_plan': int(data.get('reports_plan', 0) or 0),
            'numbers_to_check': int(data.get('numbers_to_check', 0) or 0),
            'positives': int(data.get('positives', 0) or 0),
            'active': int(data.get('active', 0) or 0),
            'vbros': int(data.get('vbros', 0) or 0),
            'predlog': int(data.get('predlog', 0) or 0),
            'soglasiy': int(data.get('soglasiy', 0) or 0),
        }
    except (TypeError, ValueError):
        return jsonify({'error': 'numeric fields must be integers'}), 400

    _insert_report767_entry(entry)
    return jsonify({'ok': True, 'entry': entry})


@app.route('/api/miniapp/report767/stats', methods=['GET'])
def api_miniapp_report767_stats():
    """Get report 767 totals by team."""
    _, error = _require_mini_app_admin()
    if error:
        return error
    try:
        team_rows = _get_report767_team_rows()
        grand = _get_report767_totals()
    except sqlite3.Error as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'teams': team_rows, 'total': grand})


@app.route('/api/miniapp/sources', methods=['GET'])
def api_miniapp_sources():
    """List configured source items."""
    _, error = _require_mini_app_admin()
    if error:
        return error
    return jsonify({'items': _sources_list()})


@app.route('/api/miniapp/sources', methods=['POST'])
def api_miniapp_sources_add():
    """Add source item (admin)."""
    session, error = _require_mini_app_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    value = str(data.get('value') or '').strip()
    if not name or not value:
        return jsonify({'error': 'name and value are required'}), 400
    _sources_add(name=name, value=value, user_id=int(session.get('user_id') or 0), username=str(session.get('username') or ''))
    return jsonify({'ok': True})


@app.route('/api/miniapp/sources/remove', methods=['POST'])
def api_miniapp_sources_remove():
    """Remove source item by id (admin)."""
    _, error = _require_mini_app_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    source_id = _parse_optional_int(data.get('id'))
    if not source_id:
        return jsonify({'error': 'id is required'}), 400
    removed = _sources_remove(source_id)
    return jsonify({'ok': True, 'removed': int(removed)})


@app.route('/api/miniapp/green_order', methods=['POST'])
def api_miniapp_green_order():
    """Create green order entry."""
    session, error = _require_mini_app_auth()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    donor_link = str(data.get('donor_link') or '').strip()
    full_name = str(data.get('full_name') or '').strip()
    birth_date = str(data.get('birth_date') or '').strip()
    vk_source = str(data.get('vk_source') or '').strip()
    count = _parse_optional_int(data.get('count'))
    if not donor_link or not full_name or not birth_date or not vk_source or count is None:
        return jsonify({'error': 'donor_link, full_name, birth_date, count, vk_source are required'}), 400
    entry = {
        'created_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        'chat_id': 0,
        'user_id': int(session.get('user_id') or 0),
        'username': str(session.get('username') or ''),
        'donor_link': donor_link,
        'full_name': full_name,
        'birth_date': birth_date,
        'count': int(count),
        'vk_source': vk_source,
    }
    _insert_green_order(entry)
    return jsonify({'ok': True, 'entry': entry})


@app.route('/api/miniapp/green_orders', methods=['GET'])
def api_miniapp_green_orders():
    """List green orders for authorized Mini App users."""
    _, error = _require_mini_app_auth()
    if error:
        return error
    limit = _parse_optional_int(request.args.get('limit')) or 100
    return jsonify({'items': _green_orders_list(limit=limit)})

if __name__ == '__main__':
    print("Universal Search System")
    print("=====================")
    print("Comprehensive OSINT tool for phones and photos")
    print("Starting web server on http://localhost:5000")
    print()
    print("Available endpoints:")
    print("  POST /api/phone_search - Universal phone search")
    print("  POST /api/photo_search - Universal photo search")
    print("  GET /api/sources - Available search sources")
    print()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
