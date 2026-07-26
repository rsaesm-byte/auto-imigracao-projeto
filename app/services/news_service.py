"""Busca e cacheia as últimas notícias do feed RSS oficial do USCIS
(https://www.uscis.gov/news/rss-feed/59144) para exibição no site.

O uscis.gov bloqueia clientes HTTP com "cara de bot" -- confirmado
empiricamente: `httpx` (já usado no projeto para a API da Anthropic) toma
403 nesse domínio mesmo com um User-Agent de navegador, enquanto `requests`
com o mesmo header passa normalmente (o bloqueio parece ser por fingerprint
de TLS/HTTP do cliente, não pelo header em si). Por isso usamos `requests`
aqui especificamente, mesmo o projeto já tendo httpx instalado.

Cache em memória (nível de módulo) com TTL de 1h: evita bater no USCIS a
cada carregamento de página (landing/dashboard), e nunca deixa a página
quebrar por causa de uma falha de rede -- em caso de erro, devolve o cache
anterior (mesmo vencido) ou lista vazia; esta função nunca levanta exceção.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

USCIS_NEWS_RSS_URL = "https://www.uscis.gov/news/rss-feed/59144"
CACHE_TTL_SECONDS = 60 * 60  # 1 hora
REQUEST_TIMEOUT = 10
DEFAULT_MAX_ITEMS = 6

_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
}

_cache: dict = {"items": [], "fetched_at": 0.0}


def _parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        pub_date = None
        if pub_date_raw:
            try:
                pub_date = parsedate_to_datetime(pub_date_raw)
            except (TypeError, ValueError):
                pub_date = None
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
            })
    return items


def get_latest_news(max_items: int = DEFAULT_MAX_ITEMS) -> list[dict]:
    """Devolve as últimas notícias oficiais do USCIS, buscando o feed se o
    cache estiver vencido. Nunca levanta exceção -- em falha (rede, parsing,
    bloqueio), devolve o cache anterior (mesmo vencido) ou lista vazia."""
    now = time.time()
    if _cache["items"] and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return _cache["items"][:max_items]

    try:
        response = requests.get(USCIS_NEWS_RSS_URL, headers=_BROWSER_HEADERS,
                                 timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        items = _parse_feed(response.content)
        if items:
            _cache["items"] = items
            _cache["fetched_at"] = now
    except Exception:
        pass  # mantém o cache anterior (mesmo vencido) -- nunca quebra a página

    return _cache["items"][:max_items]
