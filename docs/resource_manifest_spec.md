# 桌宠资源清单协议 v1

每个桌宠位于 `assets/pets/<pet_id>/`，入口文件固定为 `manifest.json`。程序只通过清单读取资源，不依赖特定角色的文件名。

## 必填字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 | 当前必须为 `1` |
| `pet_id` | 字符串 | 稳定且非空的角色标识 |
| `name` | 字符串 | UI 中显示的角色名称 |
| `canvas` | `[宽, 高]` | 美术源画布，单位 px |
| `display_size` | `[宽, 高]` | 桌面窗口默认显示尺寸 |
| `anchor` | `[x, y]` | 角色落脚锚点 |
| `hitbox` | `[x, y, 宽, 高]` | 角色交互区域，必须位于画布内 |
| `animations` | 对象 | 动画集合，必须包含四个主状态 |

四个主状态固定为 `idle`、`hover`、`loading`、`working`。额外过渡动画可沿用 `idle_to_hover` 等命名，但不影响主状态校验。

## 动画与帧

每个动画包含：

- `loop`：是否循环。
- `interruptible_frames`：允许安全切换状态的零基帧序号。
- `frames`：按播放顺序排列的帧。

每帧包含相对于 `manifest.json` 的 `file` 与正整数 `duration_ms`。资源路径不得逃离当前角色目录。开发阶段支持透明 PNG、WebP 和 SVG；正式美术资源优先使用透明 PNG/WebP。

```json
{
  "loop": true,
  "interruptible_frames": [0],
  "frames": [
    {"file": "idle/idle_000.png", "duration_ms": 83}
  ]
}
```

## 版本策略

- 兼容性修改不提升 `schema_version`。
- 删除字段、改变字段含义或增加新的必需字段时提升主版本。
- 加载失败时应用应显示默认桌宠，并报告具体资源错误。
