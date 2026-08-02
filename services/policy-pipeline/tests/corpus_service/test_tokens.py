"""令牌注册表测试。独立签发 —— 不依赖平台账号体系。"""
from __future__ import annotations

import json

import pytest

from scripts.corpus_service.tokens import TokenRegistry, hash_token, mint_token, new_record

NOW = 1_800_000_000.0  # 2027-01-15 前后，与下方 expires_at 配合


@pytest.fixture()
def registry_file(tmp_path):
    rec = new_record("外团队A", token="tok-aaa", expires_at="2099-01-01",
                     rpm=60, full_text_per_day=200)
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"tokens": [rec]}, ensure_ascii=False), encoding="utf-8")
    return path


# --- 签发 ------------------------------------------------------------------

def test_mint_token_is_long_and_unique():
    a, b = mint_token(), mint_token()
    assert a != b
    assert len(a) >= 32


def test_new_record_stores_hash_not_plaintext():
    """明文令牌绝不落盘 —— 注册表泄露不等于令牌泄露。"""
    rec = new_record("外团队A", token="tok-aaa")
    flat = json.dumps(rec, ensure_ascii=False)
    assert "tok-aaa" not in flat
    assert rec["sha256"] == hash_token("tok-aaa")


def test_new_record_carries_identity_and_limits():
    rec = new_record("外团队A", token="t", rpm=30, full_text_per_day=100)
    assert rec["name"] == "外团队A"
    assert rec["rpm"] == 30
    assert rec["full_text_per_day"] == 100
    assert rec["issued_at"]


# --- 校验 ------------------------------------------------------------------

def test_valid_token_authenticates(registry_file):
    rec = TokenRegistry.load(registry_file).authenticate("tok-aaa", now=NOW)
    assert rec is not None
    assert rec.name == "外团队A"
    assert rec.rpm == 60
    assert rec.full_text_per_day == 200


def test_unknown_token_is_rejected(registry_file):
    assert TokenRegistry.load(registry_file).authenticate("tok-zzz", now=NOW) is None


def test_empty_token_is_rejected(registry_file):
    assert TokenRegistry.load(registry_file).authenticate("", now=NOW) is None


def test_expired_token_is_rejected(tmp_path):
    rec = new_record("过期方", token="tok-old", expires_at="2020-01-01")
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"tokens": [rec]}), encoding="utf-8")
    assert TokenRegistry.load(path).authenticate("tok-old", now=NOW) is None


def test_revoked_token_is_rejected(tmp_path):
    rec = new_record("已撤销", token="tok-rev")
    rec["revoked"] = True
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"tokens": [rec]}), encoding="utf-8")
    assert TokenRegistry.load(path).authenticate("tok-rev", now=NOW) is None


def test_token_without_expiry_never_expires(tmp_path):
    rec = new_record("长期方", token="tok-forever", expires_at=None)
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"tokens": [rec]}), encoding="utf-8")
    assert TokenRegistry.load(path).authenticate("tok-forever", now=NOW) is not None


def test_registry_key_is_stable_and_not_the_plaintext_token(registry_file):
    """限流按令牌身份记账，这个 key 不能是明文令牌（会进日志）。"""
    rec = TokenRegistry.load(registry_file).authenticate("tok-aaa", now=NOW)
    assert "tok-aaa" not in rec.key
    assert rec.key == hash_token("tok-aaa")[:16]


def test_missing_registry_file_yields_empty_registry(tmp_path):
    reg = TokenRegistry.load(tmp_path / "nope.json")
    assert reg.is_empty is True
    assert reg.authenticate("anything", now=NOW) is None
