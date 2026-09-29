"""模型出站策略：私有模式仅接受显式私网/回环 IP，禁止 DNS 重绑定。"""
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

_PRIVATE_NETWORKS = tuple(ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7"))


def check_model_endpoint(endpoint: str, config) -> None:
    mode = config.MODEL_PROCESSING_MODE
    if mode == "rules_fallback":
        raise ValueError("规则模式禁止模型出站调用")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("模型地址必须为不含凭据的 HTTP(S) 地址")
    if mode != "private_model":
        return
    try:
        address = ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("私有模型模式请使用明确的私网或回环 IP，禁止外部域名") from exc
    if not any(address in network for network in _PRIVATE_NETWORKS):
        raise ValueError("私有模型模式禁止公共网络地址")
