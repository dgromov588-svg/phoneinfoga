"""
Легальный каркас интеграции с внешним сервисом знакомств (например, Mamba)
через официальные API/SDK и с соблюдением ToS/закона.

Важно:
- Не используйте этот модуль для парсинга, обходов защиты, массовых действий или автоспама.
- Подключайте только документированные endpoints и токены доступа.
"""

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class MambaClient:
    base_url: str
    token: str

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_me(self) -> dict[str, Any]:
        """Пример вызова профиля текущего пользователя через официальный endpoint."""
        response = requests.get(f"{self.base_url}/me", headers=self._headers(), timeout=15)
        response.raise_for_status()
        return response.json()

    def list_matches(self) -> list[dict[str, Any]]:
        """Пример получения мэтчей через официальный endpoint."""
        response = requests.get(f"{self.base_url}/matches", headers=self._headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [])

    def send_message(self, match_id: str, text: str) -> dict[str, Any]:
        """Пример отправки сообщения в рамках официального API."""
        payload = {"match_id": match_id, "text": text}
        response = requests.post(
            f"{self.base_url}/messages",
            headers=self._headers(),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
