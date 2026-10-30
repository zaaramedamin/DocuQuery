import io
import zipfile

import pytest
from fastapi import HTTPException

from services import extractors
from tests.conftest import make_pptx, make_xlsx


# ── PowerPoint ───────────────────────────────────────────────────────

def test_pptx_has_one_page_per_slide_in_order():
    pages = extractors.extract_pptx_pages(make_pptx(["Title slide\nBy Alice", "Agenda\nItem one", "Thanks"]))
    assert pages == ["Title slide\nBy Alice", "Agenda\nItem one", "Thanks"]


def test_pptx_follows_presentation_order_not_file_numbering():
    # Files are slide3, slide2, slide1 — but the deck's own order is what matters.
    pages = extractors.extract_pptx_pages(make_pptx(["first", "second", "third"], reverse_order=True))
    assert pages == ["first", "second", "third"]


def test_pptx_speaker_notes_are_appended_to_their_slide():
    pages = extractors.extract_pptx_pages(make_pptx(["Revenue", "Costs"], notes={2: "Mention the 3% drop"}))
    assert pages[0] == "Revenue"
    assert pages[1] == "Costs\n\nSpeaker notes: Mention the 3% drop"


def test_pptx_keeps_empty_slides_so_slide_numbers_stay_correct():
    pages = extractors.extract_pptx_pages(make_pptx(["Intro", "", "Closing"]))
    assert len(pages) == 3 and pages[1] == ""


def test_pptx_notes_text_is_included():
    pptx = make_pptx(["A"], notes={1: "real note"})
    assert "real note" in extractors.extract_pptx_pages(pptx)[0]


@pytest.mark.parametrize("data", [b"not a zip", b""])
def test_pptx_rejects_invalid_files(data):
    with pytest.raises(HTTPException) as exc:
        extractors.extract_pptx_pages(data)
    assert exc.value.status_code == 400


def test_pptx_without_slides_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/other.xml", "<x/>")
    with pytest.raises(HTTPException) as exc:
        extractors.extract_pptx_pages(buffer.getvalue())
    assert "no readable slides" in exc.value.detail


def test_office_zip_bombs_are_refused(monkeypatch):
    monkeypatch.setattr(extractors, "_MAX_OFFICE_UNZIPPED_BYTES", 1000)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/slides/slide1.xml", "a" * 50_000)  # tiny when compressed, huge when unpacked
    with pytest.raises(HTTPException) as exc:
        extractors.extract_pptx_pages(buffer.getvalue())
    assert exc.value.status_code == 413


# ── Excel ────────────────────────────────────────────────────────────

def test_xlsx_rows_become_column_value_lines():
    data = make_xlsx({"Sales": [["Region", "Revenue"], ["North", 1200], ["South", 950.5]]})
    (page,) = extractors.extract_xlsx_pages(data)
    assert page.startswith("Sheet: Sales\nColumns: Region, Revenue\n")
    assert "Row 2: Region: North; Revenue: 1200" in page
    assert "Row 3: Region: South; Revenue: 950.5" in page


def test_xlsx_reads_every_visible_sheet_and_skips_hidden_ones():
    data = make_xlsx(
        {"Q1": [["a"], ["1"]], "Q2": [["a"], ["2"]], "Secret": [["a"], ["classified"]]},
        hidden=("Secret",),
    )
    pages = extractors.extract_xlsx_pages(data)
    assert [p.splitlines()[0] for p in pages] == ["Sheet: Q1", "Sheet: Q2"]
    assert not any("classified" in p for p in pages)


def test_xlsx_formats_dates_booleans_and_whole_numbers():
    import datetime

    data = make_xlsx({"S": [["when", "ok", "n"], [datetime.date(2026, 3, 5), True, 7.0]]})
    (page,) = extractors.extract_xlsx_pages(data)
    assert "when: 2026-03-05; ok: TRUE; n: 7" in page


def test_xlsx_splits_long_sheets_and_repeats_the_header_on_each_page():
    rows = [["id", "name"]] + [[i, f"item{i}"] for i in range(1, 101)]
    pages = extractors.extract_xlsx_pages(make_xlsx({"Big": rows}))
    assert len(pages) == 3  # 100 data rows / 40 per page
    assert all(p.startswith("Sheet: Big\nColumns: id, name\n") for p in pages)


def test_xlsx_skips_blank_rows_and_empty_cells():
    data = make_xlsx({"S": [["a", "b"], [None, None], ["x", None]]})
    (page,) = extractors.extract_xlsx_pages(data)
    assert "Row 3: a: x" in page and "b:" not in page.split("Row 3:")[1]


def test_xlsx_with_only_a_header_still_describes_the_sheet():
    (page,) = extractors.extract_xlsx_pages(make_xlsx({"Empty": [["only", "headers"]]}))
    assert page == "Sheet: Empty\nColumns: only, headers"


@pytest.mark.parametrize("data", [b"garbage", b"PK\x03\x04 truncated"])
def test_xlsx_rejects_invalid_files(data):
    with pytest.raises(HTTPException) as exc:
        extractors.extract_xlsx_pages(data)
    assert exc.value.status_code == 400


# ── CSV ──────────────────────────────────────────────────────────────

def test_csv_basic():
    (page,) = extractors.extract_csv_pages(b"name,age\nAlice,30\nBob,25\n")
    assert page == "Columns: name, age\nRow 2: name: Alice; age: 30\nRow 3: name: Bob; age: 25"


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_csv_detects_other_delimiters(delimiter):
    data = f"city{delimiter}pop\nParis{delimiter}2100000\n".encode()
    (page,) = extractors.extract_csv_pages(data)
    assert "city: Paris; pop: 2100000" in page


def test_csv_handles_quoted_fields_with_commas_and_newlines():
    (page,) = extractors.extract_csv_pages(b'name,note\n"Smith, J.","line one\nline two"\n')
    assert "name: Smith, J.; note: line one line two" in page


def test_csv_handles_utf8_bom_and_unicode():
    (page,) = extractors.extract_csv_pages("﻿ville,pays\nZürich,Suisse\nالقاهرة,مصر\n".encode("utf-8"))
    assert "ville: Zürich; pays: Suisse" in page and "ville: القاهرة; pays: مصر" in page


def test_csv_extra_cells_without_a_header_get_a_generic_name():
    (page,) = extractors.extract_csv_pages(b"a,b\n1,2,3\n")
    assert "a: 1; b: 2; Column 3: 3" in page


def test_csv_row_cap(monkeypatch):
    monkeypatch.setattr(extractors, "MAX_TABLE_ROWS", 5)
    data = ("n\n" + "\n".join(str(i) for i in range(100))).encode()
    pages = extractors.extract_csv_pages(data)
    assert sum(p.count("Row ") for p in pages) == 5


def test_empty_csv_has_no_pages():
    assert extractors.extract_csv_pages(b"\n\n  \n") == []


# ── dispatch + file classification ───────────────────────────────────

@pytest.mark.parametrize(
    "name, kind",
    [("deck.pptx", "pptx"), ("Budget.XLSX", "xlsx"), ("data.csv", "csv"), ("data.tsv", "csv")],
)
def test_new_extensions_are_accepted(name, kind):
    assert extractors.classify_filename(name)[1] == kind


@pytest.mark.parametrize("name", ["old.ppt", "old.xls", "macro.xlsm", "deck.key"])
def test_legacy_and_unsupported_office_formats_are_rejected(name):
    with pytest.raises(HTTPException) as exc:
        extractors.classify_filename(name)
    assert "PowerPoint" in exc.value.detail and "Excel" in exc.value.detail


def test_extract_text_pages_routes_each_type():
    assert extractors.extract_text_pages(make_pptx(["x"]), "pptx", 1000) == ["x"]
    assert extractors.extract_text_pages(b"a,b\n1,2", "csv", 1000)[0].startswith("Columns:")
    assert extractors.extract_text_pages(make_xlsx({"S": [["a"], [1]]}), "xlsx", 1000)[0].startswith("Sheet: S")
