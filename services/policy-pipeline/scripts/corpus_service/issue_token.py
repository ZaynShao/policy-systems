"""签发 / 吊销对外令牌。

  python -m scripts.corpus_service.issue_token issue  --registry ./tokens.json --name 外团队A
  python -m scripts.corpus_service.issue_token list   --registry ./tokens.json
  python -m scripts.corpus_service.issue_token revoke --registry ./tokens.json --name 外团队A

明文令牌只在签发时打印一次，注册表里只存哈希，丢了只能重签。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.corpus_service.tokens import DEFAULT_FULL_TEXT_PER_DAY, DEFAULT_RPM, mint_token, new_record


def _read(path: Path) -> dict:
    if not path.exists():
        return {"tokens": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)  # 注册表只给属主读写


def cmd_issue(a: argparse.Namespace) -> int:
    data = _read(a.registry)
    if any(t.get("name") == a.name and not t.get("revoked") for t in data["tokens"]):
        raise SystemExit(f"已存在未撤销的令牌: {a.name}（先 revoke 再重签）")

    token = mint_token()
    data["tokens"].append(new_record(
        a.name, token=token, expires_at=a.expires_at,
        rpm=a.rpm, full_text_per_day=a.full_text_per_day,
    ))
    _write(a.registry, data)

    print(f"已为「{a.name}」签发令牌，注册表: {a.registry}")
    print(f"有效期: {a.expires_at or '不过期'}　限流: {a.rpm}/分钟，全文 {a.full_text_per_day}/天")
    print("\n下面这行只显示这一次，请通过安全渠道交给对方：\n")
    print(f"  {token}\n")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    for t in _read(a.registry)["tokens"]:
        state = "已撤销" if t.get("revoked") else "生效"
        print(f"{state:>4}  {t.get('name'):<16} 到期={t.get('expires_at') or '—':<12} "
              f"rpm={t.get('rpm')} 全文/天={t.get('full_text_per_day')} "
              f"指纹={str(t.get('sha256'))[:12]}")
    return 0


def cmd_revoke(a: argparse.Namespace) -> int:
    data = _read(a.registry)
    hit = [t for t in data["tokens"] if t.get("name") == a.name and not t.get("revoked")]
    if not hit:
        raise SystemExit(f"没有找到生效中的令牌: {a.name}")
    for t in hit:
        t["revoked"] = True
    _write(a.registry, data)
    print(f"已撤销「{a.name}」的令牌（服务需重载注册表后生效）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="对外令牌签发 / 吊销")
    ap.add_argument("--registry", type=Path, required=True, help="令牌注册表 JSON 路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("issue", help="签发新令牌")
    i.add_argument("--name", required=True, help="使用方标识，如 外团队A")
    i.add_argument("--expires-at", dest="expires_at", default=None, help="到期日 YYYY-MM-DD，留空不过期")
    i.add_argument("--rpm", type=int, default=DEFAULT_RPM, help=f"每分钟请求上限（默认 {DEFAULT_RPM}）")
    i.add_argument("--full-text-per-day", dest="full_text_per_day", type=int,
                   default=DEFAULT_FULL_TEXT_PER_DAY,
                   help=f"每日取全文上限（默认 {DEFAULT_FULL_TEXT_PER_DAY}）")
    i.set_defaults(func=cmd_issue)

    l = sub.add_parser("list", help="列出已签发令牌")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("revoke", help="撤销令牌")
    r.add_argument("--name", required=True)
    r.set_defaults(func=cmd_revoke)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
