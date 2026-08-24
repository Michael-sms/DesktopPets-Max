# M5 最终体验验收

M5 收口桌面运行体验，并提供可重复的性能与长时间运行报告。默认角色资源仍使用已审核的 M3 动画，M5 不重新生成或修改角色美术。

## 本轮完成范围

- 将渲染定时器从 50 Hz 降至约 12 FPS，状态切换仍立即请求绘制；全部 82 帧在启动时预加载，切换时不访问网络。
- Windows 使用 manifest 的固定 `hitbox` 做系统级命中测试：角色热区可拖拽和右键操作，外侧透明区域点击穿透。
- 拖拽位置以“显示器名称 + 可用区域相对坐标”保存；重启、显示器切换或 DPI 变化后恢复并夹在可见区域内。
- 窗口置顶可通过右键菜单关闭并持久化；状态标签默认隐藏，仅在调试模式显示。
- 右键“状态”可触发四个主状态，“过渡预览”可直接播放五段过渡，“任务结束事件”可验证完成、取消、失败和超时退出忙碌状态。
- 自定义 manifest 或动画帧损坏时回退到默认桌宠；`--validate` 仍保持严格失败，便于定位坏资源。
- 新增长稳监视器，记录状态响应、RSS、CPU、预加载帧数和运行样本，并输出 JSON 验收报告。

## 自动回归

```powershell
uv run python -m unittest discover -s tests -v
uv run python main.py --validate
uv run python main.py --smoke-test
uv run python main.py --smoke-create
uv run pet-assets check assets\pets\m3_sample\manifest.json
uv run python scripts\check_windows_interaction.py
```

快速生成一份长稳报告：

```powershell
uv run python main.py --soak-test --soak-seconds 60 --soak-report workspace\m5_reports\soak-60s.json
```

最终两小时测试（默认 7200 秒）：

```powershell
uv run python main.py --soak-test --soak-report workspace\m5_reports\soak-2h.json
```

测试期间程序会轮播完整状态链。报告通过条件为：最大状态响应不超过 150 ms、首尾 RSS 增长不超过 32 MiB、按逻辑处理器归一化的平均 CPU 不超过 15%。报告和本机配置均为本地文件，不上传远程仓库。

## 人工体验审核

使用调试模式启动：

```powershell
uv run python main.py --debug
```

请依次检查：

1. 每个主状态连续观看至少 30 秒，确认无跳帧、漂移、白边和背景残留；Loading 是等待光球，Working 是主动操作终端。
2. 在右键“过渡预览”中播放五段过渡，确认没有突然缩放、瞬移或光源变化。
3. 在角色外侧透明角落点击，确认点击落到后方窗口；在角色热区内拖动并打开右键菜单。
4. 快速进出热区，确认 120 ms 进入和 200 ms 离开迟滞不会闪烁。
5. 切到 Loading/Working 后，分别触发完成、取消、失败和超时，确认回到 Idle（指针停留时回 Hover）。
6. 拖到另一显示器后退出并重启，确认位置恢复；如显示器缩放不同，确认窗口尺寸和热区仍正确。
7. 关闭“窗口置顶”后重启，确认设置保留。
8. 指定一个不存在或损坏的自定义 manifest，确认终端出现回退提示且默认桌宠继续运行。

无调试标签的最终体验使用：

```powershell
uv run python main.py --demo
```
