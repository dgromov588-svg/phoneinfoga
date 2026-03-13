"""Helper for generating Russian resource search URLs."""

import re
from typing import Dict, List
from urllib.parse import quote

RU_RESOURCE_TEMPLATES = [
    {
        "name": "VK — поиск людей",
        "url_template": "https://vk.com/search?c[section]=people&c[q]={value}",
        "description": "Публичный поиск профилей ВКонтакте по номеру",
        "value_source": "digits",
    },
    {
        "name": "2GIS",
        "url_template": "https://2gis.ru/search/{value}",
        "description": "Поиск по номеру в каталоге 2GIS",
        "value_source": "formatted",
    },
    {
        "name": "Avito",
        "url_template": "https://www.avito.ru/rossiya?q={value}",
        "description": "Поиск объявлений на Авито по номеру",
        "value_source": "digits",
    },
    {
        "name": "Yandex Search",
        "url_template": "https://yandex.ru/search/?text={value}&lr=213",
        "description": "Общий поиск по номеру на Яндексе",
        "value_source": "formatted",
    },
    {
        "name": "Yandex Maps",
        "url_template": "https://yandex.ru/maps/?text={value}&lr=213",
        "description": "Поиск по номеру на Яндекс.Картах",
        "value_source": "formatted",
    },
]


def build_ru_resource_links(phone_number: str) -> List[Dict[str, str]]:
    """Return a list of curated Russian resource links for a phone number."""
    digits = re.sub(r"\D", "", phone_number)
    formatted = phone_number
    links: List[Dict[str, str]] = []

    for template in RU_RESOURCE_TEMPLATES:
        source = template.get("value_source", "formatted")
        if source == "digits" and digits:
            value = digits
        else:
            value = formatted

        if not value:
            continue

        encoded = quote(value)
        url = template["url_template"].format(value=encoded)
        links.append({
            "name": template["name"],
            "url": url,
            "description": template.get("description", ""),
        })

    return links
