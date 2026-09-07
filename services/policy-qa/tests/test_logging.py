"""应用日志要真的能打进 docker logs。

这条不是"日志好看一点"的问题。2026-09-03 之前,运维手册让人用

    docker logs platform-policy-qa | grep 已加载业务战略画像

去确认业务战略画像加载成功——**那条指令永远不会有输出**,而且和画像毫无关系:
uvicorn 只给 uvicorn.* 那几个 logger 配 handler,root 上一个也没有,
`logging.getLogger("policy-qa")` 于是既没有自己的 handler 也没有可继承的,
只剩 Python 的 lastResort,而 lastResort 是 **WARNING** 级的 —— info 一行都出不来。
照着那条查的人会得出"画像没加载"的错误结论。
"""
import logging

from app import main


def _reset() -> logging.Logger:
    """把 policy-qa 这支 logger 恢复到"没人配过"的状态。

    propagate 置 False 是为了让测试确定地走 lastResort 分支——
    否则 pytest 自己挂在 root 上的 handler 会把记录接走,测不到真实情况。
    """
    lg = logging.getLogger("policy-qa")
    for h in list(lg.handlers):
        lg.removeHandler(h)
    lg.setLevel(logging.NOTSET)
    lg.propagate = False
    return lg


def test_unconfigured_info_is_silently_dropped_but_warning_survives(capsys):
    """钉住根因本身:info 没了,warning 还在。

    后半句同样重要——它说明"画像加载失败"一直是可见的,
    所以这补的是可观测性,不是正确性。
    """
    lg = _reset()
    lg.info("这行在配 handler 之前不该出现")
    lg.warning("失败信息任何时候都该出现")
    err = capsys.readouterr().err
    assert "这行在配 handler 之前不该出现" not in err
    assert "失败信息任何时候都该出现" in err


def test_configure_logging_lets_info_reach_stderr(capsys):
    _reset()
    main.configure_logging()
    logging.getLogger("policy-qa").info("已加载业务战略画像 2026-energy-strategy")
    assert "已加载业务战略画像" in capsys.readouterr().err


def test_configure_logging_is_idempotent():
    """测试里会建多个 app,重复装配不能让每行日志打 N 遍。"""
    _reset()
    main.configure_logging()
    main.configure_logging()
    main.configure_logging()
    assert len(logging.getLogger("policy-qa").handlers) == 1


def test_level_can_be_turned_down_without_touching_code(capsys):
    _reset()
    main.configure_logging("WARNING")
    lg = logging.getLogger("policy-qa")
    lg.info("调低之后 info 不该出来")
    lg.warning("warning 还在")
    err = capsys.readouterr().err
    assert "调低之后 info 不该出来" not in err and "warning 还在" in err


def test_level_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("POLICY_QA_LOG_LEVEL", "debug")
    _reset()
    main.configure_logging()
    assert logging.getLogger("policy-qa").level == logging.DEBUG


def test_root_logger_is_left_alone():
    """只配自己这一支:动 root 会把 httpx / pydantic_ai 的 INFO 一起放出来,
    把真正有用的几行淹掉。"""
    _reset()
    before = list(logging.getLogger().handlers)
    main.configure_logging()
    assert logging.getLogger().handlers == before
