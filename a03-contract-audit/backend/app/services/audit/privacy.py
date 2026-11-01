"""审查调用的请求级已知敏感字段脱敏；不替代底层出站授权和原文核验。"""
import json
import re
import secrets
from dataclasses import replace

from app.services.sensitive_data import _PATTERNS

_LABEL_START = re.compile(r'(联系人|姓名|联系地址|通讯地址|住所地|开户行|甲方|乙方)\s*[:：][ \t]*')
_VALUE_BOUNDARY = re.compile(r'[\r\n，,。；;"<>]')


def _map_strings(value, transform):
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, dict):
        return {key: _map_strings(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_strings(item, transform) for item in value]
    return value


def _decode_input(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text, False
    return value, True


def _letters(index):
    result = ''
    while True:
        result = chr(ord('a') + index % 26) + result
        index = index // 26 - 1
        if index < 0:
            return result


def _collect_fragments(text, fragments):
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            fragment = match.group()
            label = re.match(r'^(联系人|姓名|联系地址|通讯地址|住所地|开户行|甲方|乙方)\s*[:：]\s*(.+)$', fragment)
            fragments[fragment] = label[1] if label else '字段'
    # 按下一个标签或标点截断，避免同行多个字段合并后遗漏裸值的重复位置。
    labels = list(_LABEL_START.finditer(text))
    for index, match in enumerate(labels):
        end = min(match.end() + 80, labels[index + 1].start() if index + 1 < len(labels) else len(text))
        candidate = _VALUE_BOUNDARY.split(text[match.end():end].lstrip(), maxsplit=1)[0].strip()
        if candidate:
            fragments.setdefault(candidate, match[1])
    return text


class AuditPrivacyAdapter:
    """仅用于外部审查chat；映射不跨请求共享，不写入日志或检查点。"""

    def __init__(self, adapter, *, context='', elements=None):
        self.adapter = adapter
        self._known_fragments = {}
        _collect_fragments(context, self._known_fragments)
        for key, label in (('party_a', '甲方'), ('party_b', '乙方')):
            value = (elements or {}).get(key)
            if isinstance(value, str) and len(value.strip()) >= 2:
                self._known_fragments.setdefault(value.strip(), label)

    def chat(self, system, user, *, temperature=0.2, options=None):
        inputs = [_decode_input(system), _decode_input(user)]
        fragments = dict(self._known_fragments)

        def collect(text):
            return _collect_fragments(text, fragments)

        for value, _ in inputs:
            _map_strings(value, collect)
        if not fragments:
            return self.adapter.chat(system, user, temperature=temperature, options=options)

        # 使用纯字母随机串，避免占位符再次命中账号/手机号正则。
        nonce = secrets.token_hex(16).translate(str.maketrans('0123456789', 'ghijklmnop'))
        originals = sorted(fragments, key=lambda item: (-len(item), item))
        encoded = {value: f'【{fragments[value]}_隐私_{nonce}_{_letters(i)}】' for i, value in enumerate(originals)}
        pattern = re.compile('|'.join(re.escape(value) for value in originals))

        def mask(text):
            return pattern.sub(lambda match: encoded[match.group()], text)

        outbound = [
            json.dumps(_map_strings(value, mask), ensure_ascii=False) if structured else mask(value)
            for value, structured in inputs
        ]
        response = self.adapter.chat(*outbound, temperature=temperature, options=options)
        try:
            decoded = json.loads(response.text)
        except (ValueError, TypeError):
            # 不替模型修复格式错误，仍由既有严格协议拒绝。
            return response
        inverse = {token: original for original, token in encoded.items()}
        token_pattern = re.compile('|'.join(re.escape(token) for token in inverse))

        def restore(text):
            # 仅单次还原本请求已发出的标记；未知标记和原文中的伪标记不解释。
            return token_pattern.sub(lambda match: inverse[match.group()], text)

        restored = _map_strings(decoded, restore)
        return replace(response, text=json.dumps(restored, ensure_ascii=False))
