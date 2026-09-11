"""URL 对外披露的最小化工具。"""
from urllib.parse import urlsplit, urlunsplit


def safe_http_authority(endpoint: str | None) -> str | None:
    """仅保留 scheme、host 和显式端口，不披露凭据或路径。"""
    if not endpoint:
        return None
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    safe_hostname = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{safe_hostname}:{port}" if port is not None else safe_hostname
    return urlunsplit((parsed.scheme, netloc, "", "", ""))
