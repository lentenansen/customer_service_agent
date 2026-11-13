# 项目修改概述（Change Details）

> 本文件用于存放每次改动的「修改概述」（详细说明）。编号与 `Ansenlearn/changeLog.md` 的表格条目**一一对应**（同号），只记录详细说明，不重复表格字段。
>
> 写入规则：**尾部追加**，不覆盖、不重排。每次改动先在 `changeLog.md` 登记表格行（拿到编号），再到本文件用相同编号追加概述。

---

### 02：新增「测试购买」入口、商品页与物流模拟接口（支线-1，2026-11-10）

> 性质：功能新增（前端排障修复另见 03）。
> 备注：概述原写在 `changeLog.md`（规范实施前），于 2026-11-11 按新规范迁入本文件，内容未改动。

**需求**：聊天页加「测试购买」按钮跳商品页；商品页展示商品名/价格/购买按钮，右上「修改物流」列出当前登录用户的订单，点条目弹窗看物流轨迹，并提供「发货 / 物流中转 / 已签收」三个操作。

**前置冲突与决策**：`models.py` 里 `orders.user_id` 是外键指向 MySQL `users.id`（int），而登录账号的 `user_id` 是 Redis 里的 uuid 字符串，两者无关联。采用**方案 A**：给每个登录账号绑定一条独立的 MySQL `users` 行，用 Redis key `cs:mysqluid:<uuid> → users.id` 固化映射。落地时做了一处微调——**不按 username 匹配已有行**（否则注册「小明」会误绑到 seed 的演示订单），而是首次购买时新建一行。`_ensure_mysql_user(create=False)` 用于只读接口，点「修改物流」不会往 users 表插记录。

**改动文件**：
- `app/test_shop.py`（新）：8 个接口——`GET /shop`、`GET /api/test/products`、`POST /api/test/buy`、`GET /api/test/orders`、`GET /api/test/orders/{order_no}`、`POST .../ship`、`POST .../transit`、`POST .../sign`；商品硬编码 4 件常量（不新建表）；全部沿用现有 token 校验。
- `static/shop.html`（新）/ `static/shop.js`（新）：商品卡片、右上修改物流、订单列表、物流时间线弹窗与三个按钮。
- `app/store.py`：新增 `get_username_by_user_id`、`get_bound_mysql_user_id`、`bind_mysql_user_id` 三个函数。
- `app/main.py`：仅加 2 行（import + `include_router`）。
- `static/index.html` / `static/chat.js`：header 加「测试购买」按钮与跳转 `/shop`。

**数据逻辑**：
- 购买写 **3 张表**：`orders`（状态「待发货」）+ `order_items`（不可省，`query_order_by_no` 靠它拼商品清单）+ `logistics_events`（创建事件）。
- 订单号 11 位纯数字（日期 8 位 + 3 位序号，如 `20261110001`），已验证匹配 `router.py` 的 `(?<!\d)\d{10,12}(?!\d)`，新订单能被客服 Agent 检索到。
- 状态机：待发货 ─[发货]→ 运输中 ─[已签收]→ 已签收；「物流中转」只加事件不改状态；「发货」额外写一条揽收轨迹并填 `carrier/tracking_no`；加了轻量状态校验（已签收不能再发货、待发货不能中转）。

**验证**：`py_compile`（3 个 py）、`node --check`（2 个 js）、订单号正则、DOM id 对照、接口清单均通过；本地 Python 未装 fastapi（项目依赖跑在 Docker），故未做容器外 import 起服务。后经本地 8000 实测：openapi 含 7 个 `/api/test/*`，`/shop` 等静态资源 200，购买接口写库链路正常。

**运行环境 / 影响**：当前是「三个服务在 Docker、代码本地 uvicorn 跑」的模式，`docker compose restart app` 不适用；改 Python 需重启本地 uvicorn（建议加 `--reload`），改静态文件刷新浏览器即可。⚠️ 已知边界：重跑 `seed_data` 会 `drop_all` 重建表，Redis 里的 `cs:mysqluid:*` 会指向旧 id，需清掉重新绑定。同步更新了 `Ansenlearn/learnState.md` 与 `.workbuddy/memory/2026-11-10.md`。

---

### 03：修复「测试购买」按钮点击无反应（支线-1，2026-11-10）

> 性质：缺陷修复（仅静态文件，无需重启服务）。
> 备注：概述原写在 `changeLog.md`（规范实施前），于 2026-11-11 按新规范迁入本文件，内容未改动。

**现象**：聊天页点「测试购买」地址栏不变、页面不动。

**排查结论**：后端与文件均正常——服务端返回的 4 个静态文件与磁盘 MD5 一致、`chat.js` 里确实有事件绑定、只有一个 uvicorn 进程（PID 15924，`127.0.0.1:8000`）、购买接口写库链路验证通过。根因在浏览器侧：
1. **浏览器缓存了旧版 `chat.js`**：按钮来自新 `index.html`，点击逻辑却在旧 js 里，静态资源无版本号最易中招（主因）；
2. **`shop.js` 的 token 是页面加载时的快照**：重新登录后不刷新 /shop，点购买只会 401 显示一行红字，容易被误判成「按钮没生效」；
3. `index.html` 里 `.user-bar { display:flex }` 优先级高于 `[hidden]`，登录遮罩盖在 header 上，按钮「看得到点不到」。

**改动文件（仅静态文件，刷新即生效，不用重启服务）**：
- `static/index.html`：加 `[hidden] { display: none !important; }`；按钮改内联 `onclick="location.href='/shop'"`（即使 js 被缓存或加载失败也能跳）；脚本引用加 `?v=2`。
- `static/chat.js`：移除 `testBuyBtn.addEventListener(...)`，避免重复绑定、去掉对外部 js 的依赖。
- `static/shop.html`：脚本引用加 `?v=2`。
- `static/shop.js`：token 改为 `currentToken()` 每次请求实时读 localStorage；401 提示语改准确；不再在页面加载时存 token 常量。

**验证**：`node --check` 通过；静态断言（hidden 修正 / 内联 onclick / 版本号 / 无重复绑定 / token 实时读取）全过；服务端实时返回 `/`、`/shop`、`/static/chat.js?v=2`、`/static/shop.js?v=2` 均 200 且含新代码。排障期间用当前登录态**实下了一单 `20261110001`**（桌面理线器套装 ¥59，待发货），MySQL `orders` 增 id=5、`users` 增 id=4（张三），Redis 写入 `cs:mysqluid:fd468e10c1b4` —— 数据库里这条测试订单由此而来，可直接用于后续物流流程验证。

---

### 04：售后「超阈值订单」代码兜底的脆弱点

> 性质：学习笔记 / 改进提案，非 bug 报告。

#### 1. 背景：当前机制是什么

售后专家节点（`after_sale_agent_node`）在跑完 `AFTER_SALE_AGENT` 后，做两道「转人工」检查：

1. **第一道（正常路径）**：`_extract_handoff_marker` —— 检查模型是否**主动**调用了 `request_human_handoff` 工具，留下 `HANDOFF_REQUESTED|工单号|原因` 标记。
2. **第二道（兜底路径）**：`_find_over_threshold_order` —— 模型没主动转人工时，代码**事后遍历消息列表**，筛出 `query_order_by_no` 工具返回的 `ToolMessage`，用正则抠出「实付金额」和「订单号」，金额超过 `config.REFUND_THRESHOLD` 就强制转人工。

命中兜底后，售后节点返回 `handoff_requested = True`，由 `graph.py` 的条件边 `_after_sale_exit` 把流程改道到 `handoff_node`，生成工单并回复「已转人工」。

#### 2. 核心结论

**当前兜底是「事后从文本里反查」的被动粗筛，不是精确、完备的规则保障。** 它只能兜住「模型恰好调用了 `query_order_by_no`，且返回格式符合正则」这一种情形，存在两个无法自我消除的脆弱点。

#### 3. 脆弱点一：依赖模型「恰好调用了工具」

`query_order_by_no` 是否被调用，完全由模型自主决定。代码是**事后被动接收**，无法保证消息列表里一定存在这条 `ToolMessage`。

| 场景 | 后果 |
|------|------|
| 模型没查订单（用户只说「我要退货」，模型凭感觉直接回复） | 消息列表里没有 `query_order_by_no` 的 `ToolMessage`，遍历后返回 `None`，兜底**静默失效** |
| 模型用其它工具查了金额（如 `query_after_sale_by_no`） | 代码只认 `query_order_by_no` 这一个名字，其它工具返回被忽略 |
| 工具返回文案格式变化，正则匹配不到 | 金额/订单号抓取失败，返回 `None` |

**本质**：兜底「赌」的是售后提示词会引导模型去查订单金额，因此调用工具是大概率事件。但这只是**概率**，不是**保证**。

#### 4. 脆弱点二：多个订单查询时无法精确定位

`_find_over_threshold_order` 在循环内 `return`，行为是「**取第一条金额超阈值的 `ToolMessage` 就结束**」，不区分用户当前真正要退的是哪一单。

- 会话中多次查订单（先查 A 单 ¥100，再查 B 单 ¥3000）：返回的可能是**第一条超阈值的单**，不一定等于用户意图里的那一单。
- A、B 都超阈值：只返回第一条，其余被忽略。

**本质**：函数目标不是「精确定位该退哪一单」，而是「只要发现存在超阈值订单，就强制转人工」。精确核对被**推迟**给转人工后的真人客服。

#### 5. 脆弱点三（隐含）：正则抠文本的脆弱性

金额与订单号都靠正则从 `str(message.content)` 里硬抠：

```python
amount_match = re.search(r"实付金额：¥([\d.]+)", content)
order_match = re.search(r"订单号：([A-Za-z0-9]+)", content)
```

- 工具返回一旦改为结构化对象（dict/json），这段正则就失效。
- `[\d.]+` 不够严谨（`1.2.3` 也会被匹配）。
- 格式依赖「实付金额：¥」这类硬编码文案，任何文案改动都会静默破坏兜底。

#### 6. 优化方向

**6.1 结构化数据（治「正则脆弱」）**

让 `query_order_by_no` 工具返回**结构化字段**，而非带格式字符串：

```python
{
    "order_no": "20241105001",
    "amount": 2999.00,
    "status": "已完成",
}
```

兜底代码随之简化：

```python
if tool_result.amount > config.REFUND_THRESHOLD:
    return tool_result.order_no, str(tool_result.amount)
```

**效果**：消除格式依赖，但未解决「依赖模型调用」与「选哪一单」。

**6.2 规则下沉到工具（治「依赖模型调用」）**

把「超阈值判断」放进 `query_order_by_no` 工具**内部**，查出金额超阈值就**主动触发转人工信号**：

```python
def query_order_by_no(order_no):
    order = db.query(order_no)
    if order.amount > config.REFUND_THRESHOLD:
        trigger_handoff(order_no, order.amount)  # 工具层直接触发
    return order
```

**效果**：只要「查订单」这个动作发生，规则就必然执行，**彻底摆脱对模型自觉的依赖**。

**6.3 槽位定死订单（治「选哪一单」）**

把「订单号」作为**明确槽位（slot）**，在路由/售后**开头**结构化抽取，而非事后遍历：

- 路由节点除 `intent` 外，额外抽取 `order_no` 槽位。
- 售后节点带着确定的 `order_no` 去查**那一单**。

**效果**：「是哪一单」从源头确定，不存在「多个 ToolMessage 选哪个」的问题。

**6.4 目标组合方案**

三层合起来，完备链路为：

```
1. 路由阶段：结构化抽取 intent + order_no（确定「哪一单」）
        ↓
2. 售后节点：带着明确的 order_no 调用工具（不再靠模型乱查）
        ↓
3. 工具内部：查出金额，超阈值就立刻触发转人工信号（不依赖模型自觉）
        ↓
4. 图的条件边：读到信号 → 强制改道 handoff_node
```

#### 7. 为什么当前实现「够用」却「不完备」

这是教学/演示项目，不是生产级风控系统。作者的目标是**展示「代码在事后补一道防线」这个思路**，而非封死所有边界。因此选择了最简单、最易读的方式（遍历消息 + 正则），以**可读性**换取了**完备性**。

> 事后翻文本 = 被动 + 脆弱。要完备，判断必须**前移**——结构化数据、规则进工具、槽位定死订单。

#### 8. 待办

- [ ] 确认 `query_order_by_no` 工具当前的返回格式，评估改造为结构化的成本。
- [ ] 评估是否需要在售后提示词中强化「退款/退货必须先查订单」的约束。
- [ ] 若面向生产，按 6.2 + 6.3 落地「规则进工具 + 槽位定死订单」。

---

### 05（落地）：订单归属校验已实施（主线，2026-11-12）

> 本小节是 05 号条目「方案→落地」的实施记录，接在原文之后，说明实际改了什么、最终方案与最初的设想有何不同、踩了哪些坑。

#### 1. 最终方案与最初设想的关键差异

最初方案设想用 `InjectedToolArg`（`Annotated[int, InjectedToolArg]`）从 `RunnableConfig["configurable"]` 注入 `user_id`。**实际落地时发现该机制已失效**，原因：

- 项目已升级到 **langchain 1.x（`langchain 1.4.7` / `langchain_core 1.7.1`）**，Agent 改用 `langchain.agents.create_agent` 新 API。
- 新版里工具拿「会话级上下文」的标准通道是 **`ToolRuntime`（from `langgraph.prebuilt`）+ `context_schema`**，不再是旧的 `config["configurable"]` + `InjectedToolArg`。
- 实测：用 `InjectedToolArg` 时工具拿到的 `user_id` 恒为 `None`（客服回复「user_id 字段缺失」），归属校验全部失效。

因此最终方案改为：**`create_agent(context_schema=AgentContext)` 声明上下文结构 + `agent.ainvoke(..., context={...})` 传值 + 工具内 `runtime.context["user_id"]` 取值**。

#### 2. 实际改动文件与内容

| 文件 | 改动 | 说明 |
|------|------|------|
| `app/state.py` | 新增 `user_id: str` 字段（AgentState）；新增 `AgentContext`（`TypedDict`，`user_id: int | None`） | `user_id` 携带登录用户的 Redis uuid；`AgentContext` 是子 Agent 的运行时上下文，`user_id` 存 **MySQL 自增 id** |
| `app/main.py` | `ainvoke` 初始状态加 `"user_id": user_id` | 把已解析的登录用户身份传入图 |
| `app/agents/experts.py` | `_build_agent` 加 `context_schema=AgentContext`（带 `# type: ignore[arg-type]`）；新增 `_agent_context(state)` 做 uuid→mysql_uid 转换；`_run_agent_node` 改用 `context=_agent_context(state)` 传参 | 三个专家节点统一复用 `_run_agent_node`，一处改动全局生效 |
| `app/tools.py` | 三个订单工具签名改为 `(order_no, runtime: ToolRuntime[AgentContext])`，函数内 `user_id = runtime.context["user_id"]`；查询加 `.filter(Order.user_id == user_id)`（售后表同理）；`_query_order_rows` 改为普通内部函数、查不到统一 `return None`；三个工具话术统一为「未找到订单…请核实」 | 归属过滤 + 防探测 |

#### 3. 关键机制沉淀

**3.1 `ToolRuntime` + `context_schema`（替代失效的 `InjectedToolArg`）**

- `ToolRuntime` 是 LangGraph 执行工具时自动注入的「百宝箱」参数（`langgraph.prebuilt`），含 `context / state / config / store / stream_writer / tool_call_id / tools`。
- 它属于 `_DirectlyInjectedToolArg`，是旧 `InjectedToolArg` 的新替代，**无需 `Annotated` 包裹**。
- 配套两步缺一不可：`create_agent(context_schema=...)` 声明结构 + `ainvoke(..., context={...})` 传值；少了 `context_schema`，`context` 传不进去。
- `context_schema` 类型检查器（Pylance）会报「无重载匹配」——根因是 `create_agent` 的 `middleware` 参数默认空元组使 `ContextT` 泛型无法推导。属库 typing 缺陷，用 `# type: ignore[arg-type]` 抑制，**运行时正常**（`TypedDict` 与 `dataclass` 均已实测可跑）。

**3.2 `cs:mysqluid` 映射（Redis uuid ↔ MySQL 自增 id）**

- 登录账号在 Redis 里是 uuid 字符串（`83e137ad0831`），订单表 `orders.user_id` 是 MySQL 自增整数（`5`），两套 id 互不认识。
- `store.get_bound_mysql_user_id(uuid)` 读 `cs:mysqluid:<uuid>` 得到 MySQL `users.id`；`bind_mysql_user_id` 固化关系。这个映射是**身份**，不设 TTL（账号存在多久、映射就存在多久）。
- **绑定时机**：目前仅 `test_shop.py` 的 `_ensure_mysql_user` 在下单时建立。因此**从未下单的用户 `cs:mysqluid` 不存在，`get_bound_mysql_user_id` 返回 None**——这正是落地测试时「李四查不到自己订单」现象的根因之一（详见坑 3）。

#### 4. 踩过的坑（归因）

1. **循环导入**：`AgentContext` 最初定义在 `experts.py`，被 `tools.py` 反向 import，形成 `experts → tools → experts` 循环，启动直接 ImportError。→ 下沉到 `app/state.py`。
2. **`ToolRuntime` 未泛型化**：`runtime: ToolRuntime` 未写 `[AgentContext]`，每次工具调用产生两条 Pydantic 序列化警告。→ 改 `ToolRuntime[AgentContext]` 后归零。
3. **context 键名不一致 / 漏传**：写入用 `mysql_uid`/`usr_id`、读取用 `user_id`，导致 `user_id=None` 恒返回「未找到订单」；且 `after_sale_agent_node` 未传 context 抛 `AttributeError`。→ 统一走 `_agent_context(state)`，取值 `(runtime.context or {}).get("user_id")`。
4. **`_query_order_rows` 返回类型混乱 + 缺参**：早期版本「查不到返回字符串、查到返回元组」且 `query_logistics_by_no` 调它漏传 `user_id`，导致字符串被当元组解包崩溃、`TypeError` 缺参。→ 统一 `return None` + 显式传 `user_id`。

#### 5. 验证结果

- 用户 5（李四）查自己的 `20261112001` 正常返回；
- 用户 4（张三）查他人订单返回「未找到」（不泄露订单存在性，防探测）；
- 匿名用户不崩；
- 三种场景 Pydantic 序列化警告均为 0。

#### 6. 遗留待决策点（未闭合）

- **匿名用户归属策略**仍悬置（05 待决策点 1）：当前匿名用户 `user_id=None`，`_agent_context` 返回 `{"user_id": None}`，工具 `filter(Order.user_id == None)` 恒查不到订单（等效「拒绝」，但不报错）。可选方向：绑定演示账号（如「小明」）或明确拒绝，待定。
- **校验拒绝文案**：最终采用「未找到订单…请核实」统一话术（不与「订单不存在」区分），已闭合防探测诉求。

---
