"""测试购买 / 修改物流：演示用的下单与物流状态流转。

为什么需要"绑定"这一步：
- 登录账号在 Redis 里，user_id 是 uuid 字符串（如 fd468e10c1b4）；
- orders.user_id 是 MySQL users.id 的 int 外键。
两套 id 互不认识，所以用 Redis key `cs:mysqluid:<uuid> -> users.id`
固化绑定关系：首次下单时在 MySQL users 表补一条独立记录，
之后该账号的所有订单都归属这个 id。新建独立行而不是按用户名去匹配
已有行，是为了避免误绑到 seed_data 里"小明/小红"的演示订单上。

订单号用 11 位纯数字（日期 8 位 + 3 位序号，与 seed 风格一致），
保证 router.py 的 `(?<!\\d)\\d{10,12}(?!\\d)` 能识别，
新下的订单才能被客服 Agent 查到。
"""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import config, store
from app.db import SessionLocal
from app.models import LogisticsEvent, Order, OrderItem, User

router = APIRouter(tags=["test-shop"])

# 状态值必须和 models.py 里 Order.status 的注释保持一致
S_PENDING = "待发货"
S_SHIPPING = "运输中"
S_SIGNED = "已签收"

# 演示商品：项目没有商品表，直接沿用 seed_data.py 里的商品名与价格
PRODUCTS = [
    {"sku": "headset", "name": "星音蓝牙耳机 X9", "price": 499.00},
    {"sku": "keyboard", "name": "星辰机械键盘 K87", "price": 399.00},
    {"sku": "cable", "name": "桌面理线器套装", "price": 59.00},
    {"sku": "fridge", "name": "星辰智能冰箱 B500", "price": 2999.00},
]
_PRODUCT_MAP = {p["sku"]: p for p in PRODUCTS}


class TokenBody(BaseModel):
    """所有写操作都带 token，沿用主流程的登录校验方式。"""

    token: str = Field(default="", max_length=128)


class BuyBody(TokenBody):
    sku: str = Field(..., min_length=1, max_length=32)


def _require_uid(token: str) -> str:
    """校验登录态，返回 Redis 里的 uuid。"""
    uid = store.get_user_id_by_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return uid


def _ensure_mysql_user(redis_uid: str, create: bool = True) -> int | None:
    """方案 A：把登录账号绑定到 MySQL users 表，返回 users.id。

    优先读 Redis 绑定缓存。create=False 用于只读/改状态接口：
    还没买过东西的账号直接返回 None，绝不产生"插一行用户"的副作用。
    """
    bound = store.get_bound_mysql_user_id(redis_uid)
    if bound is not None:
        return bound
    if not create:
        return None

    username = store.get_username_by_user_id(redis_uid) or f"用户{redis_uid[:6]}"
    db = SessionLocal()
    try:
        user = User(name=username, phone=None)
        db.add(user)
        db.flush()          # 拿到自增 id，但还没提交
        mysql_id = user.id
        db.commit()
    finally:
        db.close()

    store.bind_mysql_user_id(redis_uid, mysql_id)
    return mysql_id


def _owned_order(db: Session, order_no: str, mysql_id: int) -> Order:
    """取订单并校验归属，防止改动别人的订单。"""
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"订单 {order_no} 不存在")
    if order.user_id != mysql_id:
        raise HTTPException(status_code=403, detail="只能操作当前登录账号的订单")
    return order


def _next_order_no(db: Session) -> str:
    """生成当天未占用的 11 位纯数字订单号。"""
    prefix = datetime.now().strftime("%Y%m%d")
    rows = db.query(Order.order_no).filter(Order.order_no.like(f"{prefix}%")).all()
    used = {row[0] for row in rows}
    for seq in range(1, 1000):
        no = f"{prefix}{seq:03d}"
        if no not in used:
            return no
    raise HTTPException(status_code=500, detail="当日订单号已用尽")


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


# ---------------- 页面 ----------------

@router.get("/shop", include_in_schema=False)
def shop_page():
    """商品测试页。"""
    return FileResponse(config.BASE_DIR / "static" / "shop.html")


# ---------------- 商品与下单 ----------------

@router.get("/api/test/products")
def list_products():
    return {"products": PRODUCTS}


@router.post("/api/test/buy")
def buy(body: BuyBody):
    """购买：写 orders + order_items + logistics_events，初始状态待发货。"""
    product = _PRODUCT_MAP.get(body.sku)
    if product is None:
        raise HTTPException(status_code=400, detail="商品不存在")

    redis_uid = _require_uid(body.token)
    mysql_id = _ensure_mysql_user(redis_uid)

    db = SessionLocal()
    try:
        order_no = _next_order_no(db)
        now = datetime.now()
        price = Decimal(str(product["price"]))

        order = Order(
            user_id=mysql_id,
            order_no=order_no,
            status=S_PENDING,
            total_amount=price,
            carrier=None,
            tracking_no=None,
            created_at=now,
        )
        # order_items 不能省：query_order_by_no 工具靠它拼"商品清单"
        order.items = [
            OrderItem(product_name=product["name"], quantity=1, price=price)
        ]
        db.add(order)
        db.add(LogisticsEvent(
            order_no=order_no,
            event_at=now,
            description="订单已创建，等待商家发货",
        ))
        db.commit()
        return {
            "ok": True,
            "order_no": order_no,
            "status": S_PENDING,
            "product": product["name"],
            "total_amount": float(price),
        }
    finally:
        db.close()


# ---------------- 订单列表与详情 ----------------

@router.get("/api/test/orders")
def list_my_orders(token: str = ""):
    """当前登录账号的订单，每条一个条目。"""
    redis_uid = _require_uid(token)
    mysql_id = _ensure_mysql_user(redis_uid, create=False)
    if mysql_id is None:
        return {"orders": []}

    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .filter(Order.user_id == mysql_id)
            .order_by(Order.created_at.desc())
            .all()
        )
        result = []
        for o in orders:
            item = (
                db.query(OrderItem)
                .filter(OrderItem.order_id == o.id)
                .first()
            )
            result.append({
                "order_no": o.order_no,
                "status": o.status,
                "product_name": item.product_name if item else "",
                "total_amount": float(o.total_amount),
                "created_at": _fmt(o.created_at),
            })
        return {"orders": result}
    finally:
        db.close()


@router.get("/api/test/orders/{order_no}")
def order_detail(order_no: str, token: str = ""):
    """订单信息 + 物流轨迹（弹窗用）。"""
    redis_uid = _require_uid(token)
    mysql_id = _ensure_mysql_user(redis_uid, create=False)
    if mysql_id is None:
        raise HTTPException(status_code=404, detail=f"订单 {order_no} 不存在")

    db = SessionLocal()
    try:
        order = _owned_order(db, order_no, mysql_id)
        events = (
            db.query(LogisticsEvent)
            .filter(LogisticsEvent.order_no == order_no)
            .order_by(LogisticsEvent.event_at)
            .all()
        )
        return {
            "order": {
                "order_no": order.order_no,
                "status": order.status,
                "total_amount": float(order.total_amount),
                "created_at": _fmt(order.created_at),
                "carrier": order.carrier,
                "tracking_no": order.tracking_no,
            },
            "events": [
                {"event_at": _fmt(e.event_at), "description": e.description}
                for e in events
            ],
        }
    finally:
        db.close()


# ---------------- 物流状态流转 ----------------

def _apply_event(
    order_no: str,
    body: TokenBody,
    *,
    description: str,
    new_status: str | None = None,
    set_carrier: bool = False,
    forbid: tuple[str, ...] = (),
) -> dict:
    """写一条物流轨迹，并按需更新订单状态的公共逻辑。"""
    redis_uid = _require_uid(body.token)
    mysql_id = _ensure_mysql_user(redis_uid, create=False)
    if mysql_id is None:
        raise HTTPException(status_code=404, detail=f"订单 {order_no} 不存在")

    db = SessionLocal()
    try:
        order = _owned_order(db, order_no, mysql_id)
        if order.status in forbid:
            raise HTTPException(
                status_code=400,
                detail=f"当前状态「{order.status}」不能执行该操作",
            )
        if new_status:
            order.status = new_status
        if set_carrier and not order.carrier:
            order.carrier = "测试快递"
            order.tracking_no = f"TEST{order_no}"
        db.add(LogisticsEvent(
            order_no=order_no,
            event_at=datetime.now(),
            description=description,
        ))
        db.commit()
        return {"ok": True, "order_no": order_no, "status": order.status}
    finally:
        db.close()


@router.post("/api/test/orders/{order_no}/ship")
def ship(order_no: str, body: TokenBody):
    """发货：状态改运输中 + 写一条发货轨迹。"""
    return _apply_event(
        order_no, body,
        description="商家已发货，测试快递已揽收",
        new_status=S_SHIPPING,
        set_carrier=True,
        forbid=(S_SHIPPING, S_SIGNED),
    )


@router.post("/api/test/orders/{order_no}/transit")
def transit(order_no: str, body: TokenBody):
    """物流中转：只加一条轨迹，状态不变。"""
    return _apply_event(
        order_no, body,
        description="快件到达中转中心，正在转运",
        forbid=(S_PENDING, S_SIGNED),
    )


@router.post("/api/test/orders/{order_no}/sign")
def sign(order_no: str, body: TokenBody):
    """已签收：加一条签收轨迹 + 状态改已签收。"""
    return _apply_event(
        order_no, body,
        description="快件已签收，签收人：本人",
        new_status=S_SIGNED,
        forbid=(S_SIGNED,),
    )
