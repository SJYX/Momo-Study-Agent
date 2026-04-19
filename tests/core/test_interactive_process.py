import os
import sys
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def runpy():
    import runpy
    return runpy

def test_interactive_profile_selection_via_runpy(monkeypatch):
    """
    测试在默认环境且 TTY 交互模式下，main.py 会触发用户选择
    并经由 subprocess.run 重载进程。
    """
    # 模拟是在真实终端下运行
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    
    # 移除可能的环境变量干扰，使 __main__ 认为是从零启动的 default 用户
    monkeypatch.delenv("MOMO_USER", raising=False)
    
    # 我们需要在 config.py 层面上让 _USER_FROM_ENV 为 False
    import config
    monkeypatch.setattr(config, "ACTIVE_USER", "default")
    monkeypatch.setattr(config, "_USER_FROM_ENV", False)
    
    # 模拟 ProfileManager 的用户选择动作
    monkeypatch.setattr("config.pm.pick_profile", lambda: "mock_asher")
    
    # 我们要拦截 subprocess.run 以及 sys.exit，防止测试进程真的退出！
    mock_subprocess_run = MagicMock()
    # 返回一个包含退出的 returncode=0 的假运行结果
    mock_subprocess_run.return_value.returncode = 0
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    
    mock_sys_exit = MagicMock(side_effect=SystemExit)
    monkeypatch.setattr(sys, "exit", mock_sys_exit)
    
    # 我们还要 mock run()，因为重启后主脚本原本会继续 run(args.env, args.config)。
    # 但我们期望在 sys.exit 处就已经拦截了，所以原先的 run() 理论上在 main.py 里甚至不该发生。
    monkeypatch.setattr("main.run", MagicMock())
    
    # 为了执行 if __name__ == "__main__": 的逻辑，我们使用 runpy
    import runpy
    import __main__
    
    # 为了避免 args 解析报错，注入测试参数
    monkeypatch.setattr(sys, "argv", ["main.py"])
    
    # 运行模块
    try:
        runpy.run_path("main.py", run_name="__main__")
    except SystemExit:
        pass  # 允许 sys.exit 抛出的异常通过 (如果没被 mock 完整截获)
        
    # 断言 subprocess.run 应该被精确调用，模拟了进程级替换重启
    assert mock_subprocess_run.called, "预期调用 subprocess.run 来重启带新环境变量的子进程，但未调用。"
    
    # 检查重启用的参数数组是不是包含当前 python 执行器和参数
    args, kwargs = mock_subprocess_run.call_args
    assert sys.executable in args[0][0], "执行命令必须是当前 python"
    assert "main.py" in args[0][1], "应当携带原生命令脚本"
    
    # 断言环境变量是不是在重启前被塞入了正确的值
    assert os.environ.get("MOMO_USER") == "mock_asher", "重启前必须向环境变量灌入选定的用户身份！"
    
    # 断言成功接管并阻断了之后的程序生命周期
    assert mock_sys_exit.called, "重启子进程完成后必须立刻退出父进程，防止继续向下执行造成系统双开冲突！"
