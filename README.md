# DesktopPet

一个基于 PySide6 的透明桌面宠物原型。当前完成 M1“规范与原型”：使用占位角色验证 Idle、Hover、Loading、Working 四状态、资源协议与桌面交互。

## 运行

```powershell
uv sync --python 3.12
uv run python main.py
```

窗口支持：

- 鼠标悬停 120 ms 后进入 Hover，离开 200 ms 后恢复 Idle。
- 按 `1`、`2`、`3`、`4` 手动切换四状态。
- 右键打开状态调试菜单或退出。
- 按住角色左键拖动。
- 使用 `uv run python main.py --demo` 自动轮播四状态。

## 验证

```powershell
uv run python -m unittest discover -s tests -v
uv run python main.py --validate
uv run python main.py --smoke-test
```

资源协议见 [docs/resource_manifest_spec.md](docs/resource_manifest_spec.md)，本轮审阅指引见 [docs/m1_review.md](docs/m1_review.md)。
