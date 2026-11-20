# Tasks — dietary-filter-chips

> TDD 执行顺序：先失败测试（Red），再最小实现（Green）。纯前端改动以 build + i18n 校验为主。

## 1. 前端 dietary chips 组（PlanWizard）

- [ ] 1.1 定义数据：`dietaryKeys = ['vegetarian','halal','no-seafood','no-pork','gluten-free','none']` + `dietaryKeywordMap`（vegetarian→素食、halal→清真、no-seafood→不吃海鲜、no-pork→不吃猪肉、gluten-free→无麸质、none→null）+ `dietaryLabelKeyMap`/emoji。内部 key 存储，语言切换不丢（与既有 `preferenceKeys` 同构）。验证：`cd frontend && npm run build` 通过
- [ ] 1.2 组件渲染：独立「饮食偏好」组（紧邻兴趣偏好组），chips 多选互斥逻辑（选具体取消 none、取消具体恢复 none）；默认 none。验证：build 通过 + 浏览器手动点击互斥正确
- [ ] 1.3 提交并入：提交 payload 把选中的 dietary 关键词并入 preferences 的餐饮维度（与自由文本合并去重；none 不产生关键词）。验证：build 通过

## 2. 后端并入（方案 B：PlanRequest 增 dietary 字段）

- [ ] 2.1 **失败测试** `backend/tests/test_dietary_chips.py`：提交含 `dietary=["vegetarian","no-seafood"]` → `_FOOD_TMPL` 组装文本（或等价偏好文本）含「素食」「不吃海鲜」；`dietary=[]`/缺省 → 与现状一致（零变化）；与自由文本合并去重。运行 `cd backend && .venv/bin/python -m pytest tests/test_dietary_chips.py -x` 确认 Red
- [ ] 2.2 最小实现：`PlanRequest` 增可选 `dietary: list[str]`；新增 `dietary_keys_to_keywords` 映射表（vegetarian→素食、halal→清真、no-seafood→不吃海鲜、no-pork→不吃猪肉、gluten-free→无麸质）；`agents.py` 组装餐饮偏好段并入（与 `preference_keys_to_keywords` 同构）。运行 2.1 确认 Green
- [ ] 2.3 回归：`cd backend && .venv/bin/python -m pytest -q` 零失败

## 3. i18n

- [ ] 3.1 `zh-CN.js`/`en-US.js` 补键（dietaryGroupTitle、dietaryVegetarian/Halal/NoSeafood/NoPork/GlutenFree/None、dietaryHint 等约 8 键），`npm run check:i18n` 双侧齐零失败
- [ ] 3.2 语言切换手动验证：选中项保留（内部 key）、label 双语切换

## 4. 端到端验证

- [ ] 4.1 真机：选「素食」+「清真」提交规划 → 生成行程餐饮站含对应关键词（构造性验证，不强依赖 LLM 输出）；取消全部 → 恢复 none
- [ ] 4.2 归档：`openspec archive dietary-filter-chips` + `docs/night-build-todo.md` 登记完成项