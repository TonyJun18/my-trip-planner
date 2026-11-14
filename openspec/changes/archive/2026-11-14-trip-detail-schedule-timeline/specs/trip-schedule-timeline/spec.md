# trip-schedule-timeline Spec

## ADDED Requirements

### Requirement: 每日行程确定性排程（派生时刻）

行程详情与分享的读取路径 SHALL 为每日站点提供由确定性代码计算的派生时刻：
每站点包含 `visit_start`（访问开始，HH:MM）、`visit_end`（访问结束，HH:MM）、
`travel_to_next_minutes`（到下一站的段间交通估算分钟数，最后一站为 null）、
`is_transfer`（是否多城市交通占位站）。这些字段均为派生值， SHALL NOT 作为站点持久化
存储字段；任意写操作（对话式修订、手动编辑、重排、增删站）后，再次读取时 SHALL 反映
新的顺序与时长，无需额外同步。

#### Scenario: 正常排程

- **WHEN** 某日有 3 个非住宿站点（时长 180/90/90 分钟，无显式锚点），依次为景点/餐饮/景点
- **AND** 各站点之间均有坐标且直线距离对应估算通勤
- **THEN** 第一站 `visit_start` 为该日起点（默认 09:00，与排程校验同源）
- **AND** 每站 `visit_end = visit_start + 游玩时长`，下一站 `visit_start = 上一站 end + 段间交通估算`
- **AND** 前两站 `travel_to_next_minutes` 为正整数，最后一站为 null

#### Scenario: 住宿站不占游玩时段

- **WHEN** 某日站点序列包含住宿站（类型为 hotel，时长如 720 分钟——过夜停留）
- **THEN** 住宿站 SHALL NOT 按其停留时长（如 720 分钟）占用时段队列；其后站点的排程 SHALL 从住宿站的到店时刻（短期停留语义）继续推导
- **AND** 住宿站的渲染语义为「入住 {到店时刻}」

#### Scenario: 排程跨夜过载信号

- **WHEN** 某日按游玩时长与通勤累计的结束时刻超过当日边界（>24:00），或全天窗口跨度超过 12 小时
- **THEN** 该日排程结果 SHALL 携带过载（overflow）信号
- **AND** 消费端（详情页日程卡）SHALL 以醒目样式呈现过载并给出「让 AI 压缩该日」的引导提示

#### Scenario: 无坐标站点与一直以来不变的兜底

- **WHEN** 相邻站点缺少经纬度坐标
- **THEN** 段间交通估算 SHALL 跳过该相邻对（不编造数字），`travel_to_next_minutes` 为 null，
  站点时刻按「上一站 end 直接顺延」计算
- **AND** 排程是纯确定性计算，SHALL NOT 调用 LLM，SHALL NOT 依赖外部网络服务

### Requirement: 交通占位站识别

多城市行程中的「前往 {city}（交通占位）」站 SHALL 被排程与渲染识别为交通占位（is_transfer=true），
不作为景点游玩语义；新落库的占位站 SHALL 将 is_transfer 持久化到站点元数据，
存量行程 SHALL 按名称后缀「（交通占位）」兼容识别。

#### Scenario: 多城市占位站在时间轴

- **WHEN** 某日首站为交通占位站（plan 中含显式锚点时刻或名称匹配存量规则）
- **THEN** 读取路径输出 is_transfer=true
- **AND** 前端渲染为交通样式（如交通图标 + 「前往 {city}」），不显示游玩时长语义

### Requirement: 行程问答卡错误态与空态分离

行程问答卡在数据接口返回错误（网络失败 / 404 / 5xx）时 SHALL 显示明确的错误态
（「数据加载失败」+ 重试操作），
SHALL NOT 复用「暂无可答的结构化数据」的空态文案误导用户。

#### Scenario: 接口失败时的展示

- **WHEN** 问答卡数据请求返回非成功状态
- **THEN** 卡片显示错误提示与重试按钮
- **WHEN** 重试成功且数据存在
- **THEN** 恢复事实清单展示
