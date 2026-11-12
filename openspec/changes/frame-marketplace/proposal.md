# Proposal

## Why

行程规划主线已基本完成，产品需要第一条创收路径。旅途中「每日打卡」是情感浓度最高的时刻，也是天然的分享场景——把打卡产物做成可售卖的旅拍相框模板包（免费基础款拉新 + 兑换码买断付费包创收），与「规划不卖货」的中立立场不冲突（卖的是自家模板，不是货架返佣）。

## What Changes

- 新增相框模板目录（FrameTemplate / FramePack，种子数据 + alembic 迁移）：免费模板 + 付费模板包，模板本体为前端渲染器可执行的 JSON 配置
- 新增兑换码权益体系（RedemptionCode 存哈希 / FrameEntitlement 幂等权益）：外部平台售卖兑换码，站内兑换解锁模板包
- 新增单日卡 / 整程总结图数据投影接口（只含 checked 站点，owner 限定）与 AI 配文生成接口（LLM 主路径 + 模板兜底，source 诚实标注；无自动发布副作用）
- 前端新增 Canvas 相框渲染器（照片仅内存处理不上传、站点坐标手绘风格化轨迹、未购水印预览）、模板商店页（/frames）、单日卡生成器入口（今日视图 / 行程详情）
当日一句话总结复用已有 `TripDay.note` 字段（无新字段）；站点趣事复用现有 `Stop.notes`
- 新增一次性兑换码生成脚本 `scripts/gen_codes.py`（明文不落库）

## Capabilities

### New Capabilities

- `frame-marketplace`: 旅拍相框市场——模板目录与商店展示、兑换码兑换与权益幂等、单日卡/总结图数据投影、AI 配文生成（双路径降级）、前端渲染与导出边界（照片不出设备、无自动发布）

### Modified Capabilities

（无——现有 booking-ledger / booking-rhythm / favorite-spots 的需求不变）

## Impact

- **后端**：`app/models/framemarket.py`（新表）、`app/api/v1/frames.py`（新路由）、`app/services/frame_catalog_service.py` / `frame_entitlement_service.py` / `frame_copy_service.py`（新服务）、`scripts/gen_codes.py`
- **前端**：`src/frames/`（渲染器/模板注册表/导出）、`FrameStoreView`、今日视图与行程详情新入口、i18n 键新增（zh/en）
- **依赖**：无新增外部依赖（渲染纯 canvas，配文复用现有 LLM provider 管线）
- **风险面**：兑换码安全（只存哈希）、权益越权（owner/user 隔离沿用现有模式）、现有 453 测试全绿为底线
