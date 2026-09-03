from pathlib import Path

from openpyxl import Workbook

from lead_enrichment.application import inspect_inputs


def test_inspect_inputs_supports_assessment_without_kontur(tmp_path: Path) -> None:
    path = tmp_path / "assessment.xlsx"
    workbook = Workbook()
    main = workbook.active
    main.title = "Ростовская область"
    main.append(["Застройщик / бренд", "Сайт компании / проекта", "TIR"])
    main.append(["ГК Тест", "example.ru", "TIR 1"])
    lpr = workbook.create_sheet("ЛПР 2026 verified")
    lpr.append(["Строка", "Компания", "Основной актуальный ЛПР", "Роль"])
    lpr.append([2, "ГК Тест", "Иванов Иван", "директор по маркетингу"])
    workbook.save(path)
    workbook.close()

    result = inspect_inputs(path)

    assert result.assessment_rows == 1
    assert result.rows_with_website == 1
    assert result.primary_contacts == 1
    assert result.kontur_rows == 0
    assert result.not_found_rows == 1
