import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.services.rag.legal_sources import (
    LegalSourceError,
    SourceSpec,
    chinese_number_to_int,
    int_to_chinese_number,
    load_manifest,
    parse_articles,
    validate_article_set,
    verify_source_file,
)


FIXTURES = Path(__file__).parent / "fixtures" / "legal_sources"


def _spec(**overrides) -> SourceSpec:
    base = SourceSpec(
        source_id="sample-law",
        title="示例规则",
        issuing_authority="全国人民代表大会",
        official_url="https://flk.npc.gov.cn/sample-law",
        file="sample-law.txt",
        file_sha256=hashlib.sha256((FIXTURES / "sample-law.txt").read_bytes()).hexdigest(),
        included_ranges=((1, 3),),
        expected_article_count=3,
        publication_date=date(2020, 5, 28),
        effective_date=date(2021, 1, 1),
        version_status="现行有效",
        retrieved_at=date(2026, 9, 8),
    )
    return replace(base, **overrides)


@pytest.mark.parametrize(
    ("number", "label"),
    [(204, "二百零四"), (386, "三百八十六"), (988, "九百八十八")],
)
def test_article_number_conversion_covers_target_ranges(number, label):
    assert int_to_chinese_number(number) == label
    assert chinese_number_to_int(label) == number


def test_load_manifest_and_verify_authoritative_file():
    specs = load_manifest(FIXTURES / "manifest.json")

    assert len(specs) == 1
    assert specs[0].included_ranges == ((1, 3),)
    assert verify_source_file(specs[0], FIXTURES).startswith("第一章 示例规则")


def test_manifest_rejects_non_authoritative_host(tmp_path):
    payload = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    payload["sources"][0]["official_url"] = "https://example.com/copied-law"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(LegalSourceError, match="非权威域名"):
        load_manifest(path)


def test_verify_source_rejects_hash_mismatch_and_path_escape(tmp_path):
    (tmp_path / "sample-law.txt").write_text("第一条 内容", encoding="utf-8")

    with pytest.raises(LegalSourceError, match="SHA-256"):
        verify_source_file(_spec(file_sha256="0" * 64), tmp_path)
    with pytest.raises(LegalSourceError, match="法源目录"):
        verify_source_file(_spec(file="../outside.txt"), tmp_path)


def test_parse_articles_normalizes_numbers_and_preserves_context():
    text = """第一章 示例规则
第1条 第一条内容。
第二条 第二条内容。
第二条之一 第二条的补充内容。
第三条 第三条内容。"""
    spec = _spec(expected_article_count=4)

    articles = parse_articles(spec, text)
    validate_article_set(spec, articles)

    assert [article.article_number for article in articles] == [
        "第一条", "第二条", "第二条之一", "第三条"
    ]
    assert articles[0].chapter_title == "第一章 示例规则"
    assert articles[0].content == "第一条 第一条内容。"
    assert articles[2].article_sort > articles[1].article_sort


def test_validate_rejects_duplicate_missing_and_out_of_bounds_ranges():
    duplicate = """第一条 第一版。
第一条 第二版。
第二条 内容。
第三条 内容。"""
    with pytest.raises(LegalSourceError, match="重复条号"):
        parse_articles(_spec(), duplicate)

    missing = parse_articles(_spec(), "第一条 内容。\n第三条 内容。")
    with pytest.raises(LegalSourceError, match="缺少条号.*第二条"):
        validate_article_set(_spec(), missing)

    out_of_bounds = _spec(included_ranges=((1, 4),), expected_article_count=4)
    articles = parse_articles(
        out_of_bounds, (FIXTURES / "sample-law.txt").read_text(encoding="utf-8")
    )
    with pytest.raises(LegalSourceError, match="缺少条号.*第四条"):
        validate_article_set(out_of_bounds, articles)


def test_source_file_rejects_path_traversal():
    with pytest.raises(LegalSourceError, match="法源目录之外"):
        verify_source_file(_spec(file="../sample-law.txt"), FIXTURES)


def test_source_file_rejects_hash_mismatch():
    with pytest.raises(LegalSourceError, match="SHA-256"):
        verify_source_file(_spec(file_sha256="0" * 64), FIXTURES)


def test_parse_and_validate_selected_articles():
    text = verify_source_file(_spec(), FIXTURES)
    articles = parse_articles(_spec(), text)

    validate_article_set(_spec(), articles)
    assert [item.article_number for item in articles] == ["第一条", "第二条", "第三条"]
    assert articles[0].chapter_title == "第一章 示例规则"
    assert articles[0].content.startswith("第一条")


def test_arabic_and_subarticle_numbers_are_normalized():
    spec = _spec(included_ranges=((1, 2),), expected_article_count=3)
    text = "第1条 第一项。\n第2条 第二项。\n第二条之一 补充项。"
    articles = parse_articles(spec, text)

    validate_article_set(spec, articles)
    assert [item.article_number for item in articles] == ["第一条", "第二条", "第二条之一"]
    assert articles[-1].article_sort > articles[-2].article_sort


def test_duplicate_article_number_is_rejected():
    text = "第一条 第一项。\n第一条 重复项。\n第二条 第二项。\n第三条 第三项。"

    with pytest.raises(LegalSourceError, match="重复条号"):
        parse_articles(_spec(), text)


@pytest.mark.parametrize(
    ("ranges", "count", "message"),
    [
        (((1, 4),), 4, "缺少条号"),
        (((1, 3),), 4, "条数不一致"),
    ],
)
def test_article_set_rejects_missing_or_wrong_count(ranges, count, message):
    spec = _spec(included_ranges=ranges, expected_article_count=count)
    articles = parse_articles(spec, verify_source_file(_spec(), FIXTURES))

    with pytest.raises(LegalSourceError, match=message):
        validate_article_set(spec, articles)
