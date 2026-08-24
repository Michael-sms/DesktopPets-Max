# M6 透明逐帧动态角色

M6 将默认桌宠从“单张姿势做整体微位移”升级为真实姿势变化的透明逐帧动画。角色身份、服装和配色沿用已审核的小轨设定。

## 动画内容

- Idle：12 帧呼吸与闭眼循环，肩部、发梢、眼睑和衣服褶皱发生变化。
- Hover：12 帧发现用户、抬手、完整挥手和回落循环。
- Loading：12 帧光球升降，手指、视线、眼睑、发梢和粒子同步变化。
- Working：12 帧双手点击、快速输入和滑动确认，终端控件持续反馈。
- 五段 6 帧真实姿势过渡。
- `idle_variant_look`：10 帧环顾随机动作，Idle 每隔 8～20 秒低概率触发一次。

每个主循环由同一张 2×2 角色关键姿势表切格生成。构建器会清除棋盘或深色背景、删除相邻格碎片、统一 512×512 画布和 y=492 落脚点，再输出透明 PNG。PNG 避免部分 WebP 预览器错误显示 Alpha=0 像素中的隐藏 RGB。

## 重建与验证

姿势表是本地生成美术资源，位于 `assets/pets/m6_sample/source/`，整个 M6 样例目录已加入忽略规则。

```powershell
uv run python scripts\build_m6_sample.py
uv run pet-assets check assets\pets\m6_sample\manifest.json --report workspace\m6_review\quality.json
uv run python -m unittest discover -s tests -v
```

## 人工审核

自动轮播：

```powershell
uv run python main.py --demo --debug
```

建议重点确认：

1. Idle 闭眼和呼吸是否清楚但不抢注意力。
2. Hover 是否能看到抬手过程，而不是静态挥手图。
3. Loading 光球上下运动是否明显区别于 Working 的主动双手操作。
4. Working 手指、终端和身体前倾是否形成持续工作节奏。
5. 右键“过渡预览”逐段播放五个过渡。
6. 右键“随机 Idle 动作”手动触发 `idle_variant_look`，并观察它播放完后返回 Idle。
7. 正常 Idle 保持 8～20 秒，确认随机环顾会自动出现。

M6 使用 AI 生成关键姿势，随后由本地确定性构建器切帧与清理。自动质检中的亮度、色板或轮廓跳变警告代表姿势或发光道具发生显著变化，需结合完整循环人工判断，不等同于阻断错误。
