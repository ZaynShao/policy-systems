"""生产后 git 收尾:add(白名单)→ commit → pull --rebase → push。

所有生产 cron 共用。exit:0=成功/无变更(白名单外改动只隔离告警,不阻断);
5=push 失败(本地 commit 保留,下轮 cron 重试;期间 sync_tick 守卫会 abort 不 reset)。

2026-08 复盘(退役 exit 4):旧行为"见越界整单拒绝"下,四个生产作业共用一个
工作区、白名单互不相交——任一作业容器步骤失败留下的孤儿文件,会被其余作业
判为越界,连各自名单内的合法产出也一并拒提,四方互锁自锁(8/4 一次 DNS 抖动
→ 17 天 push 停摆)。现改为:越界文件绝不进 commit(纪律不变),但不再阻断
名单内产出;孤儿由其归属作业的下一轮成功 run 自然收编,系统自愈。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.service.notify import send_text as notify_send


def _git(args: list, cwd) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd), check=True,
                         capture_output=True, text=True)
    return res.stdout.strip()


def classify_changes(porcelain: str, whitelist: list) -> tuple:
    """git status --porcelain -z 输出 → (白名单内路径, 白名单外路径)。
    -z:NUL 分隔、文件名原样不转义(内嵌换行/制表符等控制字符不会拆条目或被转义,
    否则 git add 拿到转义名找不到真文件会退 128 崩管线);R/C 条目后随一个 NUL 终止的原路径字段。"""
    to_add, violations = [], []
    records = porcelain.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        if not rec:
            i += 1
            continue
        status, path = rec[:2], rec[3:]        # "XY " 前缀:2 状态位 + 空格
        if "R" in status or "C" in status:     # rename/copy:原路径在随后一条,跳过,只按新路径分类
            i += 1
        (to_add if any(path.startswith(w) for w in whitelist) else violations).append(path)
        i += 1
    return to_add, violations


def _pull_rebase_push(vault_dir, ts: str, fail_prefix: str) -> int:
    """pull --rebase + push;失败则 abort rebase、告警、exit 5(commit 保留待重试)。
    rebase.autoStash:工作区可能留着越界的隔离文件(见模块 docstring),
    裸 rebase 会因脏树拒跑;autostash 让隔离文件安然穿过 rebase。"""
    try:
        _git(["-c", "rebase.autoStash=true", "pull", "--rebase", "origin", "main"], vault_dir)
        _git(["push", "origin", "main"], vault_dir)
    except subprocess.CalledProcessError as e:
        subprocess.run(["git", "rebase", "--abort"], cwd=str(vault_dir),
                       capture_output=True)
        msg = f"[produce_and_push] {fail_prefix}: {e.stderr[:200] if e.stderr else e}"
        print(f"[{ts}] {msg}", file=sys.stderr)
        notify_send(msg)
        return 5
    return 0


def run(vault_dir, whitelist: list, message: str) -> int:
    vault_dir = Path(vault_dir)
    porcelain = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-u", "-z"],
        cwd=str(vault_dir), check=True, capture_output=True, text=True).stdout
    to_add, violations = classify_changes(porcelain, whitelist)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if violations:
        # 隔离不阻断:越界文件绝不进本次 commit,留在工作区等归属作业收编;
        # 若始终无人收编(不在任何作业白名单内),会每轮告警直到人工处理。
        msg = f"[produce_and_push] 白名单外改动,已隔离不提交: {violations[:5]} (共{len(violations)})"
        print(f"[{ts}] {msg}", file=sys.stderr)
        notify_send(msg)
    if not to_add:
        ahead = _git(["rev-list", "--count", "origin/main..HEAD"], vault_dir)
        if ahead != "0":
            rc = _pull_rebase_push(vault_dir, ts, "滞留 commit 重推失败")
            if rc:
                return rc
            print(f"[{ts}] pushed stranded commits ({ahead})")
            return 0
        print(f"[{ts}] no change, skip")
        return 0
    _git(["add", "--", *to_add], vault_dir)
    _git(["commit", "-m", message], vault_dir)
    rc = _pull_rebase_push(vault_dir, ts, "push 失败(本地 commit 保留待重试)")
    if rc:
        return rc
    print(f"[{ts}] pushed {len(to_add)} paths: {message}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-dir", required=True)
    ap.add_argument("--whitelist", required=True, help="逗号分隔路径前缀")
    ap.add_argument("--message", required=True)
    args = ap.parse_args(argv)
    return run(args.vault_dir, [w for w in args.whitelist.split(",") if w], args.message)


if __name__ == "__main__":
    raise SystemExit(main())
