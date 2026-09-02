from lead_enrichment.engine.normalization import (
    extract_ip_owner_name,
    is_valid_inn,
    normalize_http_url,
    normalize_identifier,
    normalize_inn,
    split_emails,
    split_phones,
)


def test_inn_validation_supports_legal_entity_and_entrepreneur() -> None:
    assert is_valid_inn("1234567894")
    assert is_valid_inn("123456789047")
    assert normalize_inn("123 456 7894") == "1234567894"
    assert normalize_inn("123456789048") is None


def test_identifier_normalization_does_not_accept_fractional_values() -> None:
    assert normalize_identifier(123456789.0, {9}) == "123456789"
    assert normalize_identifier(123456789.5, {9}) is None
    assert normalize_identifier(True, {1}) is None


def test_contact_splitters_normalize_and_deduplicate() -> None:
    assert split_emails("Sales@Example.ru\nsales@example.ru; owner@example.org; x@example.net") == [
        "sales@example.ru",
        "owner@example.org",
        "x@example.net",
    ]
    assert split_phones("+7 (999) 111-22-33\n8 999 111 22 33") == ["+79991112233"]


def test_phone_splitter_accepts_ten_digit_regional_numbers() -> None:
    assert split_phones(
        "(863) 1234567, (863) 7654321",
        allow_ten_digit=True,
    ) == [
        "+78631234567",
        "+78637654321",
    ]


def test_url_normalization_and_ip_owner_extraction() -> None:
    assert normalize_http_url("example.ru/contacts") == "https://example.ru/contacts"
    assert normalize_http_url("javascript:alert(1)") is None
    assert normalize_http_url("сайт не найден") is None
    assert extract_ip_owner_name("ИП Иванов Иван Иванович") == "Иванов Иван Иванович"
