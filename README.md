# DesktopPet

一个基于 PySide6 的透明桌面宠物。当前已完成 M1～M5：支持照片制作流程、完整状态动画、资源打包导入，以及透明热区交互、多屏位置恢复、损坏资源回退和长时间运行验收。

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
- 角色外透明区域在 Windows 上点击穿透；窗口位置和置顶设置会在重启后恢复。
- 使用 `uv run python main.py --debug` 显示状态标签和完整验收菜单。

M3 默认角色会按 `Idle → Hover → Idle → Loading → Working → Idle` 轮播，以展示全部五段标准过渡。详细审阅步骤见 [docs/m3_review.md](docs/m3_review.md)。

## M2 角色制作审阅

使用内置样例走完闭环（不联网）：

```powershell
uv run python main.py --create-demo
```

在界面中依次点击“生成 3 个候选方案”，选择方案并勾选三项人工确认，最后点击“确认并生成 Idle 动画”。生成结果保存在 `workspace/generated_pets/`。

使用自己的照片建立本地草稿：

```powershell
uv run python main.py --create
```

照片分析、色板提取和规格草稿均在本地执行。真实照片转二次元候选需要显式安装可选 AI Provider，并在本机配置 `OPENAI_API_KEY`：

```powershell
uv sync --extra ai
```

应用不会保存或显示 API Key，也不会在未配置 Provider 时上传照片。

## 验证

```powershell
uv run python -m unittest discover -s tests -v
uv run python main.py --validate
uv run python main.py --smoke-test
uv run python main.py --smoke-create
uv run pet-assets check assets\pets\m3_sample\manifest.json
uv run python main.py --soak-test --soak-seconds 60
```

M5 最终审核步骤见 [docs/m5_final_acceptance.md](docs/m5_final_acceptance.md)，M4 打包与导入见 [docs/m4_asset_pipeline.md](docs/m4_asset_pipeline.md)。资源协议见 [docs/resource_manifest_spec.md](docs/resource_manifest_spec.md)。
