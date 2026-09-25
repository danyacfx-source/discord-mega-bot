from app.services.wardogs_service import WardogsService


def test_select_requires_exact_server_name() -> None:
    service = WardogsService(server_name="Wardogs")
    rows = [
        {"name": "Wardogs Central", "players": 100},
        {"name": "WARDOGS", "players": 12},
    ]

    assert service._select(rows) == rows[1]


def test_select_never_falls_back_to_another_server() -> None:
    service = WardogsService(server_name="Наш сервер")

    assert service._select([{"name": "Чужой сервер", "players": 100}]) is None


def test_select_join_id_has_priority() -> None:
    service = WardogsService(server_name="Любое имя", server_id="abc-123")
    rows = [
        {"serverId": "other", "name": "Первый"},
        {"serverId": "ABC-123", "name": "Нужный"},
    ]

    assert service._select(rows) == rows[1]
