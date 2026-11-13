"""LangGraph 图的状态定义。

状态 = 一张在节点间传递的“共享表格”。每个节点往里写自己的产出，
下一个节点读自己需要的字段。

为什么 messages 要用 Annotated + operator.add：
LangGraph 默认认为“节点返回什么，字段就整体替换成什么”。
如果多个节点都往 messages 里加消息，后面的会覆盖前面的。
operator.add 是 reducer（归并器）：告诉 LangGraph“返回的新消息要
追加到已有列表后面”，这样消息才会越积越多而不是互相覆盖。
"""
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage


class AgentState(TypedDict, total=False):
    # 对话消息：初始 = 历史 + 用户新消息；专家节点把最终回答追加进来
    messages: Annotated[list[AnyMessage], operator.add]
    # 路由结果：order / after_sale / knowledge / chat / clarify
    intent: str
    # 路由时抽出的关键信息（如订单号），各节点复用，不用重复找
    extracted: dict[str, Any]
    # 会话 ID（转人工工单要记录是哪位用户）
    session_id: str
    # 该会话此前“连续没能理解”的次数（由 main 从外部存储读入）
    attempts: int
    # 转人工标记：售后专家工具触发后置 True，条件边据此改道
    handoff_requested: bool
    handoff_ticket_id: str
    handoff_reason: str
    # 最终回答（专家节点产出，接口层从这里取）
    answer: str
    # 每个节点的执行记录（节点名 + 耗时），方便复盘整张图的走向
    trace: Annotated[list[str], operator.add]
    # 登录用户的 Redis uuid（匿名时为空串）
    user_id: str


class AgentContext(TypedDict, total=False):
    """子 Agent 的运行时上下文（create_agent 的 context_schema）。

    为什么单独定义、且放在 state.py：
    1. 它描述的是「图节点 → 子 Agent → 工具」这条链路上传递的上下文，
       本质属于状态定义的一部分；
    2. 放在 experts.py 里会被 tools.py 反向 import，形成循环依赖
       （experts → tools → experts），启动时直接 ImportError。

    user_id 这里是 MySQL 自增 id（int），不是 Redis 的 uuid——
    工具做 Order.user_id 过滤时用的就是它。
    """

    user_id: int | None
