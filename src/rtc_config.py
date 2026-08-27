import base64
import hashlib
import hmac
import time
from copy import deepcopy


RTC_MODES = {"off", "auto", "relay"}
DEFAULT_ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]


def normalize_ice_servers(value):
    if not isinstance(value, list):
        return deepcopy(DEFAULT_ICE_SERVERS)

    normalized = []
    for server in value:
        if isinstance(server, str) and server.strip():
            normalized.append({"urls": server.strip()})
            continue

        if not isinstance(server, dict):
            continue

        urls = server.get("urls")
        if isinstance(urls, str) and urls.strip():
            normalized.append(deepcopy(server))
        elif isinstance(urls, list) and any(isinstance(url, str) and url.strip() for url in urls):
            normalized.append(deepcopy(server))

    return normalized or deepcopy(DEFAULT_ICE_SERVERS)


def split_ice_servers(servers):
    stun_servers = []
    turn_servers = []

    for server in normalize_ice_servers(servers):
        raw_urls = server["urls"]
        urls = [raw_urls] if isinstance(raw_urls, str) else raw_urls
        stun_urls = [url for url in urls if isinstance(url, str) and url.lower().startswith(("stun:", "stuns:"))]
        turn_urls = [url for url in urls if isinstance(url, str) and url.lower().startswith(("turn:", "turns:"))]

        if stun_urls:
            stun_server = deepcopy(server)
            stun_server["urls"] = stun_urls[0] if isinstance(raw_urls, str) else stun_urls
            stun_server.pop("username", None)
            stun_server.pop("credential", None)
            stun_servers.append(stun_server)

        if turn_urls:
            turn_server = deepcopy(server)
            turn_server["urls"] = turn_urls[0] if isinstance(raw_urls, str) else turn_urls
            turn_servers.append(turn_server)

    return stun_servers or deepcopy(DEFAULT_ICE_SERVERS), turn_servers


def generate_turn_credentials(secret, client_id, ttl_seconds, now=None):
    issued_at = int(time.time() if now is None else now)
    username = f"{issued_at + ttl_seconds}:{client_id}"
    digest = hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
    return {
        "username": username,
        "credential": base64.b64encode(digest).decode("ascii"),
    }


def managed_turn_server(host, port, secret, client_id, ttl_seconds, now=None):
    if not host or not secret:
        return None

    url_host = host.strip()
    if ":" in url_host and not url_host.startswith("["):
        url_host = f"[{url_host}]"

    credentials = generate_turn_credentials(secret, client_id, ttl_seconds, now=now)
    return {
        "urls": [
            f"turn:{url_host}:{port}?transport=udp",
            f"turn:{url_host}:{port}?transport=tcp",
        ],
        **credentials,
    }


def build_rtc_config(base_servers, mode, managed_server=None):
    if mode not in RTC_MODES:
        raise ValueError(f"Modo RTC invalido: {mode}")

    stun_servers, configured_turn_servers = split_ice_servers(base_servers)
    turn_servers = configured_turn_servers + ([managed_server] if managed_server else [])

    if mode == "off":
        ice_servers = stun_servers
        policy = "all"
    elif mode == "auto":
        ice_servers = stun_servers + turn_servers
        policy = "all"
    else:
        ice_servers = turn_servers
        policy = "relay"

    return {
        "mode": mode,
        "iceServers": ice_servers,
        "iceTransportPolicy": policy,
    }
