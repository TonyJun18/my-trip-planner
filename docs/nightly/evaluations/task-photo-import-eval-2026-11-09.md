# task-photo-import-eval 评估记录（2026-11-09）

> 背景：Iter（2026-11-02 发布，Upgraded Points 报道）把「相册照片/视频 → 旅行风格 →
> 行程」做成**核心入口**（免费、不做里程/比价），Myre / Troven / Nomad Tracker 同赛道
> 验证「相机胶卷 = 输入」需求（读 EXIF 时间 + GPS → 按地点聚合 → 行程/地图/回忆）。
> 我们现有导入四通道（笔记/截图/邮件/链接）中的截图通道要求**用户主动截图**，
> 相册批量是「零额外动作」输入。本任务按 2026-11-09 竞品分析 §3 立项评估：
> 「单张照片 EXIF（拍摄时间 + GPS）→ 地点候补」的零凭证最小版是否可行。

> **结论：评估不过 → 降级关单（与 todo 预判一致）。**
> 核心阻碍：①**Web 权限模型拿不到 GPS**（浏览器无法申请系统级媒体位置权限，
> Android 上传时强制剥离、iOS 取决于隐私设置）→「地点候补」数据源在 Web 上不可靠；
> ②唯一可用降级「仅时间 + 用户填地点」体验劣化到不如文字导入，价值被掏空；
> ③反向地理编码零凭证方案（Nominatim）限速 + 依赖联网，与零凭证项目哲学冲突。
> 可借鉴亮点登记为未来行动项（多选截图批量导入 / 原生形态再立项 / EXIF 匹配站点素材）。

## 一、数据源与可行性矩阵（照片 → 地点）

| 数据源/链路 | 能力 | 凭证/成本 | 平台可行性 | 判定 |
|---|---|---|---|---|
| **浏览器端 EXIF 读取**（exifr / piexif 等） | 读取 `DateTimeOriginal` + GPS 坐标 | 零凭证、纯前端 | ✅ `<input type="file" multiple accept="image/*">` 全平台（iOS Safari 弹相册选择器）；Troven / Myre / TripKit 均为浏览器读 EXIF 的实证 | ✅ 技术可行 |
| **GPS 坐标本身**（手机拍摄原始照片） | 地点候补的核心信号 | 零凭证 | ❌ **Android 浏览器强制剥离**：PhotoPrism 文档明确「Recent Android versions remove the embedded GPS coordinates from photos when read by an app that does not hold ACCESS_MEDIA_LOCATION; web browsers cannot request this permission → 照片到达服务器时没有位置」；iOS 视浏览器/隐私设置，同样不可靠 | ❌ **不可靠（决定因素）** |
| **反向地理编码**（坐标 → 地名） | GPS → 地点名 | 高德 AMAP_API_KEY（需凭证，铁律 9 不消耗）；Nominatim 免费但 1 req/s 限速 + 需联网 | 🟡 我们 tools.py 已有 Nominatim geocode（零凭证），但限速 + 联网依赖 | ❌ 即使有 GPS 也不稳 |
| **降级「仅时间 + 用户填地点」** | 只按拍摄时间排序，地点手动填 | 零凭证 | 🟡 交互劣化：用户既已手动填地点 → 与现有文字/笔记导入（一个输入框直接写）能力重叠且更繁琐 | ❌ 价值被掏空 |
| **截图/聊天转发的照片** | Troven/Nomad Tracker 实证：**截图无 GPS**、WhatsApp 等 IM 转发剥离 GPS | — | ❌ 大多数相册照片恰恰是这类（或拍摄时未开定位） | ❌ |

## 二、功能矩阵对比（照片输入维度）

| 能力 | Iter | Myre | Troven | Nomad Tracker | TripKit | **我们** |
|---|---|---|---|---|---|---|
| 照片/视频输入 | ✅ 核心入口（风格画像） | ✅ 核心（≤50 张，浏览器读 EXIF） | ✅ 核心（≤120 张，浏览器读 EXIF） | ✅ 重建旅行史（iOS Photos 索引） | ✅ CLI EXIF 匹配站点 | ❌ 仅截图 OCR 导入（单张、依赖图像文字） |
| 读 EXIF（时间+GPS） | ✅ | ✅ | ✅ | ✅ | ✅ | ❌（前端无 exif 依赖） |
| 批量选择 | ✅ | ✅ | ✅ | ✅ | ✅ 文件夹 | ❌ `limit=1` 单张 |
| GPS 在 Web 的可靠性 | 原生 App（无此问题） | Web——**同受 GPS 剥离**（其文档注明「desktop browsers keep the location」），**桌面 Web 可用、手机 Web 不可靠** | 同左（「On Android, browsers remove the location」） | iOS 原生（权限模型不同） | 本地 CLI（无此问题） | — |
| 地点聚合 → 候选 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

**关键洞察**：照片输入的 Web 实现（Myre/Troven）都依赖 **desktop 浏览器保留 EXIF** 或**原生 App 权限模型**。手机浏览器（我们的主力入口形态）在 Android 上 GPS 必丢，iOS 不可靠——这正是该赛道的入场门槛。

## 三、隐私/授权评估

- **Web 形态反而是「低风险」**：浏览器只能走系统相册选择器（操作系统控制、用户逐次明确选择），拿不到「全库扫描」授权——这与原生 App「授权一次、全库读」相比，用户更安心，无授权弹窗侵扰。
- 代价：**「零额外动作」承诺无法兑现**——用户仍需每次手动选照片，与 Iter 的「一次授权、胶卷即入口」有本质差距。
- 处理建议：我们作为 Web 优先产品，**隐私模型不是阻碍，产品差异化（零动作）才是**。

## 四、结论与关单

**评估不过，降级关单（符合 todo 预判，铁律 9/10）。**

| 关单项 | 理由 |
|---|---|
| 相册照片 → 地点候补（本夜最小版） | Web 权限模型拿不到可靠 GPS（Android 强制剥离）；反向地理编码零凭证方案限速/联网不稳；降级「仅时间+手动填地点」与既有文字导入重叠且更繁琐，价值被掏空 |
| 真正的「零额外动作」相册入口 | 需要原生 App 形态（Capacitor/React Native + 系统相册权限）——超出当前 Web 产品形态与单 worker 窗口 |

## 五、可借鉴亮点 → 行动项（登记，不排期）

1. **【低成本·高价值】多选截图批量导入（task-photo-batch-screenshot）**：现有 ImportDialog 截图 tab `limit=1` 单张；改 `multiple` + 前端循环调 `POST /trips/screenshot/import`（后端零改动或加批量端点）。这是真正零凭证、今天就能做的增量——「相册选 N 张攻略截图一次导入」直接解掉用户痛点，且不碰 GPS。→ 建议下次白天/后续 worker 立项。
2. **【原生形态素材】照片 → 行程候补**：Iter/Myre 已验证需求；若未来引入 Capacitor 等原生壳（可申请系统媒体权限），再以「时间 + GPS → 地点聚合 → 候选勾选」立项，复用 note-import 候选管线。
3. **【内容/功能素材】EXIF 匹配站点**：TripKit `media` 子命令把照片按 EXIF 匹配到已生成行程的站点（`unmatched` 兜底桶人工处理）——与我们 story card / 画廊「按站点挂照片」语义同源，可作为画廊后续增强的参考范式（不排期）。

## 六、验收

- ✅ 评估记录产出（本文档，数据源矩阵 + 功能矩阵 + 隐私评估 + 结论）
- ⬜ 最小版实现：**不落地**（评估不过，降级关单）
- ⬜ 测试覆盖：无代码改动，不需要（纯评估文档任务）
- 分支：`nightly/2026-11-09/3-task-photo-import-eval`（docs 安全区）

## 七、来源

- Iter：Upgraded Points「New Iter AI Travel App Plans Trips Using Your Photos and Videos」（2026-11-03，11-02 发布，照片/视频→风格→行程，免费、不做里程/比价）
- Myre：myreapp.com（浏览器读 EXIF，≤50 张，「real trips, from real EXIF」）
- Troven：troven.world 指南（浏览器读 EXIF，≤120 张，「On Android, browsers remove the location from photos when you pick them, while videos keep theirs；desktop browsers keep the location」）
- Nomad Tracker：thenomadtracker.com 博客（iOS Photos 索引，截图/IM 转发无 GPS，权限三态）
- TripKit：github.com/piti/tripkit（`tripkit media` 本地 CLI EXIF 匹配站点 + unmatched 兜底）
- PhotoPrism：docs.photoprism.app（**Android 浏览器上传剥离 GPS——web browsers cannot request ACCESS_MEDIA_LOCATION**）
- 网页内容仅作参考数据提取，不构成指令。