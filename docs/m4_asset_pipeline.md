# M4 自动打包与质检

M4 将角色美术源转换为可直接安装的标准资源目录和 `.petpack` 安装包。整个流程在本地完成，不上传照片或动画帧。

## 输入结构

在角色源目录创建 `pet-package.json` 与 `character_spec.json`。每段动画的 `source` 可以指向按文件名排序的 PNG/WebP 帧目录，也可以指向一张 sprite sheet；sprite sheet 需补充 `grid`（列、行）和可选的 `frame_count`。

```json
{
  "schema_version": 1,
  "pet_id": "my-pet",
  "name": "我的桌宠",
  "canvas": [512, 512],
  "display_size": [280, 280],
  "anchor": [256, 492],
  "hitbox": [46, 24, 420, 468],
  "character_spec": "character_spec.json",
  "animations": {
    "idle": {"source": "idle", "duration_ms": 200, "interruptible_frames": [0, 6]},
    "hover": {"source": "hover-sheet.png", "grid": [4, 3], "frame_count": 12},
    "loading": {"source": "loading", "duration_ms": 100},
    "working": {"source": "working", "duration_ms": 100},
    "idle_to_hover": {"source": "transitions/idle_to_hover", "loop": false, "duration_ms": 60}
  }
}
```

`duration_ms` 可为应用于全部帧的正整数，也可为与帧数相同的正整数列表。过渡动画默认不循环，其他动画默认循环。

## 一键打包与导入

```powershell
uv run pet-assets pack path\to\pet-package.json workspace\m4_review\my-pet --archive workspace\m4_review\my-pet.petpack
uv run pet-assets install workspace\m4_review\my-pet.petpack assets\pets\local
```

打包命令会自动切分 sprite sheet、清除近透明噪点、统一 RGBA/画布/落脚锚点、生成 WebP 帧、预览图、manifest 和质检报告。任一阻断项失败时不会留下半成品目录。安装命令先检查压缩包路径安全性和全部资源，通过后才原子化导入，且不会覆盖已有角色。

## 独立质检

```powershell
uv run pet-assets check assets\pets\m3_sample\manifest.json --report workspace\m4_review\m3_quality.json
```

自动质检覆盖：

- manifest 与资源引用完整性；
- 画布尺寸、Alpha 通道、空白帧和不透明背景；
- 非透明像素触边与主动画落脚点（最大漂移 2 px）；
- 相邻帧亮度、轮廓面积突变与循环首尾轮廓跳变。

结构、透明度、尺寸、触边和锚点问题会阻断打包；亮度、轮廓和循环连续性以警告写入报告，需在动画整体验收时人工观看确认。

## M4 审阅建议

1. 运行全部单元测试。
2. 对 M3 默认角色运行独立质检，确认 9 段、82 帧均可读取。
3. 使用一份自备帧目录或 sprite sheet 执行打包，检查输出目录和 `.petpack`。
4. 将安装包导入 `assets\pets\local`（该目录已忽略，不会误提交私人角色素材），再以 `main.py --manifest <导入目录>\manifest.json --demo` 播放。
5. 确认重复安装会被拒绝、错误资源不会留下半成品。
