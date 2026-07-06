"""Shared HTTP session factory.

All outbound HTTP traffic must go through this module so proxy, timeout,
and environment-proxy behavior is controlled in one place.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_sessions: dict[tuple, requests.Session] = {}


def _get_network_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    network = config.get("network", {})
    return network if isinstance(network, dict) else {}


def _get_proxy_config(config: dict[str, Any] | None) -> dict[str, Any]:
    network = _get_network_config(config)
    proxy = network.get("proxy", {})
    return proxy if isinstance(proxy, dict) else {}


def get_timeout(config: dict[str, Any] | None, default: tuple[int, int] = (5, 12)) -> tuple[int, int]:
    """Return a requests timeout tuple from config.network."""
    network = _get_network_config(config)
    connect_timeout = network.get("connect_timeout", default[0])
    read_timeout = network.get("read_timeout", default[1])
    try:
        return int(connect_timeout), int(read_timeout)
    except (TypeError, ValueError):
        return default


def create_session(config: dict[str, Any] | None = None) -> requests.Session:
    """Create or return a cached requests.Session using config.network.proxy.

    Expected config shape:

    network:
      proxy:
        enabled: true
        http: http://127.0.0.1:7897
        https: http://127.0.0.1:7897

    When proxy.enabled=true, environment proxies are deliberately ignored
    and the explicit local VPN proxy is used. When disabled, environment
    proxies are still ignored by default to avoid accidental routing changes.
    """
    proxy = _get_proxy_config(config)
    enabled = bool(proxy.get("enabled", False))
    http_proxy = proxy.get("http") or proxy.get("http_proxy")
    https_proxy = proxy.get("https") or proxy.get("https_proxy") or http_proxy

    # Keep environment proxies disabled unless a user explicitly opts in.
    trust_env = bool(_get_network_config(config).get("trust_env", False))

    key = (enabled, http_proxy, https_proxy, trust_env)
    if key in _sessions:
        return _sessions[key]

    session = requests.Session()
    session.trust_env = trust_env

    if enabled:
        session.proxies = {
            "http": http_proxy,
            "https": https_proxy,
        }
        logger.info(
            "Network proxy enabled: http=%s https=%s trust_env=%s",
            http_proxy,
            https_proxy,
            trust_env,
        )
    else:
        session.proxies = {}
        logger.info("Network proxy disabled; trust_env=%s", trust_env)

    _sessions[key] = session
    return session
