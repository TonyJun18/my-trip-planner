# task-collab-democracy-eval 评估记录（2026-10-22）

> 背景：MonkeyTravel 群组页（2026）实证——4 级投票（Love / Flexible / Concerns / No）+
> 实时 consensus 与参与率 + 角色权限（Owner / Editor / Voter / Viewer）。
> 我们：二值 up/down（-1/0/1）+ consensus=ceil(规模/2) 且 up>down + share/edit 双 token，无 vote-only 档。
> 结论：**采纳最小版「参与率透出」；四档投票与 vote-only 档记录降级**。

## 一、成本边界评估

| 候选 | 需要的改动 | 成本 | 判定 |
|---|---|---|---|
| 四档投票（Love/Flexible/Concerns/No） | `StopVote.value` int → 枚举/字符串 + 迁移 + 共识算法重写 + ShareView 交互 + 前后端测试 | 中高（~2-3 天） | ❌ 本期不做 |
| vote-only 角色档 | 新 token 类型 + 访问控制矩阵 + share/edit 语义拆分 + 前端入口 | 中（~1-2 天） | ❌ 本期不做 |
| **参与率透出（responded/group_size/participation）** | `VoteOut` +3 字段、`cast_vote`/`list_stop_votes` 返回、ShareView 徽标 | **低（~2h）** | ✅ **已落地** |
| 角色权限（Owner/Editor/Voter/Viewer） | 权限矩阵 + 所有写接口鉴权改造 | 高 | ❌ 不做（与「免登录轻协作」定位冲突） |

## 二、落地内容（最小版）

- 后端：`VoteOut` 增加 `responded` / `group_size` / `participation`（0-1）；
  `cast_vote` 与 `list_stop_votes` 同步透出（共识算法不变，仍为「过半表态且赞成多」）。
- 前端：ShareView 投票组旁显示「已表态/小组规模」徽标，hover 提示
  「不响应 ≠ 反对，多数表态即推进」。
- 测试：`test_vote_participation_transparency`（1/3 → 0.33 不共识；2/3 → 0.67 共识；汇总接口一致）。

## 三、为什么四档投票不做

1. **数据模型破坏性**：`StopVote.value` 被 `consensus`/`my_value`/前端逻辑共同依赖，改枚举需迁移存量数据；
2. **收益不确定**：四档只在「行程分歧大」时优于二值，缺少真实用户验证（项目 A 假设未闭环）；
3. **与渐进式推进哲学冲突**：现有规则「过半表态且赞成多即一致、未响应不阻塞」已体现「不响应≠反对」，
   参与率透出补上了信息透明度，四档属增量优化而非关键缺口。

## 四、后续重启条件

- 有真实群组使用数据（投票分歧率、参与率）证明二值不够用；
- 或多人协作成为核心场景时，按「四档投票」立项，含迁移脚本 + 前端交互 + 测试矩阵。