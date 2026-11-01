"""追问输出结构和引用边界校验，不保证模型回答的法律语义正确。"""
import json
import re

from pydantic import BaseModel, ConfigDict, Field


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    reply: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(max_length=20)
    unresolved: list[str] = Field(max_length=5)


def validate_answer(text: str, evidence_ids: list[str], context: dict) -> GeneratedAnswer:
    if not isinstance(text, str) or len(text) > 6000:
        raise ValueError('追问输出超限')
    answer = GeneratedAnswer.model_validate_json(text)
    if any(not item.strip() or len(item) > 100 for item in answer.unresolved):
        raise ValueError('待核对事项超限')
    if not set(answer.evidence_ids).issubset(evidence_ids):
        raise ValueError('引用超出授权资料')
    if not answer.evidence_ids and not answer.unresolved:
        raise ValueError('无引用且未说明无法判断')
    corpus = json.dumps(context, ensure_ascii=False)
    output = answer.reply + '\n' + '\n'.join(answer.unresolved)
    # 拦截资料中不存在的明确法规标题、条号和数字；不声称能检测所有幻觉。
    for token in re.findall(r'《[^》]+》|第[一二三四五六七八九十百千万零〇\d]+条|\d+(?:\.\d+)?\s*[%％]?', output):
        if token not in corpus:
            raise ValueError('包含资料外的新法律标识或数值')
    return answer
