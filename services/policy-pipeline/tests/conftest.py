"""独立版补的测试外壳(原项目没有这个文件),只管跑测试的环境,不改任何一项测试的判定。

1. 断网:测试期间不许开任何网络连接(连本机回环也不许——本机常开着代理,经它照样能出网),
   不许解析外网域名,不许真连 Postgres(psycopg2 走自己的 C 代码联网,单独拦)。
   各组测试本来就该 mock 网络(见 AGENTS.md「mock 网络,不打真网」),这里把它钉死,
   顺带保证跑测试不会调到大模型、不会碰平台库。unix socket 等本机通道不受影响。
2. 读本机政策库的那一项(tests/l1_collect/test_channel_discovery.py 里的
   test_province_targets_from_registry):它写死读 ~/Documents/Zayn Main/政策分析/ 下的
   _meta/channel_registry.yaml(原开发机上政策库的位置)。那里没有这份文件时——设了环境变量
   VAULT(政策库克隆目录),就在临时目录里搭一个同样的路径指到 VAULT 再跑;没设就跳过并写明原因。
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

import pytest

# ---- 1. 断网 -----------------------------------------------------------------

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _needs_dns(host) -> bool:
    """解析这个名字要不要查 DNS(本机名和 IP 字面量不用,连接时另有一道拦)。"""
    if host is None:
        return False
    h = (host.decode() if isinstance(host, bytes) else str(host)).strip("[]").lower()
    if h in ("", "localhost") or h.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(h.split("%")[0])
        return False
    except ValueError:
        return True


def _refuse_inet(sock, address) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError(f"测试期间不许开网络连接:试图连接 {address!r}(测试要 mock 网络)")


def _guarded_connect(self, address):
    _refuse_inet(self, address)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    _refuse_inet(self, address)
    return _orig_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if _needs_dns(host):
        raise socket.gaierror(f"测试期间不许联网:试图解析域名 {host!r}(测试要 mock 网络)")
    return _orig_getaddrinfo(host, *args, **kwargs)


def _refuse_pg(*args, **kwargs):
    raise _pg.OperationalError("测试期间不许连数据库(测试要换成假连接)")


try:
    import psycopg2 as _pg
    _orig_pg_connect = _pg.connect
except ImportError:  # 只跑一部分测试的环境里可以没装
    _pg = None


def pytest_configure(config):
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo
    if _pg is not None:
        _pg.connect = _refuse_pg


def pytest_unconfigure(config):
    socket.socket.connect = _orig_connect
    socket.socket.connect_ex = _orig_connect_ex
    socket.getaddrinfo = _orig_getaddrinfo
    if _pg is not None:
        _pg.connect = _orig_pg_connect


# ---- 2. 读本机政策库的那一项 -------------------------------------------------

#: 原开发机上政策库相对家目录的位置(测试里写死的就是它)
_ORIGINAL_VAULT = Path("Documents") / "Zayn Main" / "政策分析"
#: 读本机政策库的测试:(测试文件名, 测试函数名) → 它读的库内文件
_NEEDS_LOCAL_VAULT = {
    ("test_channel_discovery.py", "test_province_targets_from_registry"):
        Path("_meta") / "channel_registry.yaml",
}


@pytest.fixture(autouse=True)
def _local_vault_on_original_path(request, monkeypatch, tmp_path_factory):
    needed = _NEEDS_LOCAL_VAULT.get((request.node.path.name, request.node.name))
    if needed is None:
        return
    if (Path.home() / _ORIGINAL_VAULT / needed).is_file():
        return  # 库就在原位置(原开发机),照原样跑
    vault = Path(os.environ.get("VAULT") or "/nonexistent")
    if not (vault / needed).is_file():
        pytest.skip(f"这一项要读本机政策库的 {needed.as_posix()}:原开发机上库在 "
                    "~/Documents/Zayn Main/政策分析/,这台机器那里没有这份文件。"
                    "设环境变量 VAULT=<政策库克隆目录> 再跑就会照常执行。")
    home = tmp_path_factory.mktemp("home")
    (home / _ORIGINAL_VAULT).parent.mkdir(parents=True)
    (home / _ORIGINAL_VAULT).symlink_to(vault.resolve(), target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
