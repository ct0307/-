"""模型出站策略：私有模式仅接受显式私网/回环 IP，禁止 DNS 重绑定。"""
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

_PRIVATE_NETWORKS = tuple(ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7"))


def check_model_endpoint(endpoint: str, config) -> None:
    mode = config.MODEL_PROCESSING_MODE
    if mode == "rules_fallback":
        raise ValueError("规则模式禁止模型出站调用")
    parsed = urlsplit(endpoint)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError('模型地址端口无效') from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("模型地址必须为不含凭据的 HTTP(S) 地址")
    if mode != "private_model":
        if parsed.scheme != 'https' or parsed.query or parsed.fragment:
            raise ValueError('外部模型必须使用无查询参数的 HTTPS 地址')
        allowed = getattr(config, 'MODEL_EXTERNAL_ALLOWED_BASE_URLS', [])
        if endpoint.rstrip('/') not in {value.rstrip('/') for value in allowed}:
            raise ValueError('外部模型地址尚未获得明确出站授权')
        return
    try:
        address = ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("私有模型模式请使用明确的私网或回环 IP，禁止外部域名") from exc
    if not any(address in network for network in _PRIVATE_NETWORKS):
        raise ValueError("私有模型模式禁止公共网络地址")
