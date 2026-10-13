"""Экран от сканеров: глушим известные path'ы и User-Agent'ы до хендлеров.

Скейлеры и vulnerability-сканеры (Shodan-джобы, nikto, sqlmap, пробивальщики
wp-admin/.git) не должны достигать прикладных роутов и тратить rate-бюджет —
отвечаем пустыми 404/403 как можно раньше в middleware.
"""
from __future__ import annotations

import re

#: Точечные path'ы, которые сканеры дёргают в первую очередь.
_SCANNER_PATHS = frozenset(
    {
        "/.env",
        "/env",
        "/.git",
        "/.git/HEAD",
        "/.svn/entries",
        "/wp-admin",
        "/wp-login.php",
        "/xmlrpc.php",
        "/phpmyadmin",
        "/pma",
        "/adminer.php",
        "/config.json",
        "/config.php",
        "/configuration.php",
        "/actuator",
        "/actuator/env",
        "/server-status",
        "/manager/html",
        "/solr",
        "/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php",
        "/cgi-bin/.%2e/.%2e/.%2e/.%2e/etc/passwd",
    }
)

#: Префиксы каталогов, где сканерам нечего искать.
_SCANNER_PATH_PREFIXES = ("/.git/", "/.svn/", "/vendor/phpunit/", "/phpmyadmin/", "/wp-content/")

_SCANNER_UA_RE = re.compile(
    r"sqlmap|nikto|nmap|masscan|zgrab|dirbuster|gobuster|feroxbuster|wpscan|"
    r"acunetix|nessus|openvas|netsparker|havij|arachni|semrush|ahrefs|"
    r"dotbot|mj12bot|ahrefsbot|blexbot|seokicks|dataforseo",
    re.IGNORECASE,
)


def is_scanner_path(path: str) -> bool:
    if path in _SCANNER_PATHS:
        return True
    return path.startswith(_SCANNER_PATH_PREFIXES)


def is_scanner_ua(user_agent: str) -> bool:
    return bool(user_agent) and bool(_SCANNER_UA_RE.search(user_agent))
