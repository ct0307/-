"""来源审批绑定正文和适用范围，内容变化后审批自动失效。"""
import hashlib
import json


def approval_fingerprint(values) -> str:
    return hashlib.sha256(json.dumps(list(values), ensure_ascii=False, default=str,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def chunk_fingerprint(chunk) -> str:
    return approval_fingerprint(getattr(chunk, field) for field in (
        "content", "source", "category", "article_number", "version", "effective_date",
        "expiry_date", "applicable_contract_types", "applicable_dimensions", "scope_mode",
    ))


def reference_sources(query: str, docs: list[tuple]) -> tuple[bool, set[str]]:
    """仅识别库内法源标题及受控简称，最长别名优先避免民法典串引解释。"""
    import re
    aliases = {
        "中华人民共和国民法典": ("民法典",),
        "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释":
            ("合同编通则解释", "民法典合同编通则解释", "合同编通则司法解释"),
    }
    matches = []
    for doc in docs:
        title = str(doc[19] if len(doc) > 19 and doc[19] else doc[2])
        identity = str(doc[18] if len(doc) > 18 and doc[18] else title)
        for alias in (title, *aliases.get(title, ())):
            if alias and alias in query:
                matches.append((len(alias), identity))
    if matches:
        longest = max(length for length, _ in matches)
        return True, {identity for length, identity in matches if length == longest}
    prefix = re.split(r"第?[一二三四五六七八九十百千万零〇两\d]+条", query, maxsplit=1)[0]
    prefix = re.sub(r"请查询|请检索|查询|查找|请问|检索|依据|根据|[《》\s：:]", "", prefix)
    return bool(prefix), set()
