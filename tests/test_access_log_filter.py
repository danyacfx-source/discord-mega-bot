import logging

from app.core.access_log_filter import TokenMaskFilter


def _format(message: str, args=()) -> str:
    record = logging.LogRecord("aiohttp.access", logging.INFO, __file__, 1, message, args, None)
    TokenMaskFilter().filter(record)
    return record.getMessage()


def test_masks_token_in_query_string():
    line = '127.0.0.1 "GET /overlay/main?token=SECRET_TOKEN_123&x=1 HTTP/1.1" 200'
    masked = _format(line)
    assert "SECRET_TOKEN_123" not in masked
    assert "token=***&x=1" in masked


def test_masks_encoded_token_and_keeps_other_lines():
    assert "abc" not in _format("GET /a?%3Ftoken=abc HTTP/1.1") or "%3Ftoken=***" in _format("GET /a?%3Ftoken=abc HTTP/1.1")
    plain = "GET /health HTTP/1.1"
    assert _format(plain) == plain
