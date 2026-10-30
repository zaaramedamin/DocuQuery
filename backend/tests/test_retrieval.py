import pytest

from services import llm, retrieval
from services.retrieval import build_tsquery, rerank


# ── keyword query builder ────────────────────────────────────────────

def test_tsquery_drops_stopwords_and_joins_with_or():
    assert build_tsquery("What is the refund policy?") == "refund | policy"


def test_tsquery_deduplicates_and_lowercases():
    assert build_tsquery("Refund REFUND refund") == "refund"


def test_tsquery_strips_operator_characters():
    # Anything that could be tsquery syntax must never reach Postgres.
    query = build_tsquery("a & b | !c <-> (d:*) 'quoted' ; drop table")
    assert set(query) <= set("abcdefghijklmnopqrstuvwxyz0123456789 |")
    assert "&" not in query and "!" not in query and ":" not in query


def test_tsquery_keeps_non_latin_words():
    assert build_tsquery("سياسة الاسترجاع") == "سياسة | الاسترجاع"


def test_tsquery_empty_when_only_stopwords():
    assert build_tsquery("what is the") == ""
    assert build_tsquery("") == ""


def test_tsquery_is_capped():
    text = " ".join(f"term{i}" for i in range(50))
    assert len(build_tsquery(text).split(" | ")) == 12


# ── rerank ───────────────────────────────────────────────────────────

def chunks(n):
    return [{"id": i, "filename": "f.pdf", "page": 1, "text": f"passage {i}"} for i in range(n)]


@pytest.fixture
def with_model(monkeypatch):
    monkeypatch.setattr(retrieval, "gemini_client", object())
    monkeypatch.setattr(retrieval, "RERANK_ENABLED", True)


def test_rerank_orders_by_model_scores(with_model, monkeypatch):
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: [1, 9, 3, 8])
    result = rerank("q", chunks(4), top_k=2)
    assert [c["id"] for c in result] == [1, 3]


def test_rerank_accepts_scores_wrapped_in_an_object(with_model, monkeypatch):
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: {"scores": [0, 10, 5]})
    assert [c["id"] for c in rerank("q", chunks(3), top_k=2)] == [1, 2]


def test_rerank_falls_back_on_wrong_length(with_model, monkeypatch):
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: [5, 5])
    assert [c["id"] for c in rerank("q", chunks(4), top_k=2)] == [0, 1]


def test_rerank_falls_back_on_garbage(with_model, monkeypatch):
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: "not a list")
    assert [c["id"] for c in rerank("q", chunks(4), top_k=2)] == [0, 1]


def test_rerank_falls_back_when_model_errors(with_model, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(llm, "generate_json", boom)
    assert [c["id"] for c in rerank("q", chunks(4), top_k=3)] == [0, 1, 2]


def test_rerank_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(retrieval, "gemini_client", object())
    monkeypatch.setattr(retrieval, "RERANK_ENABLED", False)

    def must_not_call(*a, **k):
        raise AssertionError("rerank should not call the model")

    monkeypatch.setattr(llm, "generate_json", must_not_call)
    assert len(rerank("q", chunks(10), top_k=3)) == 3


def test_rerank_skips_the_model_when_nothing_to_choose(with_model, monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("not needed")

    monkeypatch.setattr(llm, "generate_json", must_not_call)
    assert len(rerank("q", chunks(2), top_k=5)) == 2


def test_rerank_drops_irrelevant_passages_when_enough_are_relevant(with_model, monkeypatch):
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: [0, 7, 0, 6, 0])
    assert [c["id"] for c in rerank("q", chunks(5), top_k=4)] == [1, 3]


# ── JSON parsing helper ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here you go: {"a": 1} hope that helps', {"a": 1}),
        ("[1, 2, 3]", [1, 2, 3]),
        ("no json here", None),
        ("", None),
    ],
)
def test_parse_json_loose(raw, expected):
    assert llm.parse_json_loose(raw) == expected
