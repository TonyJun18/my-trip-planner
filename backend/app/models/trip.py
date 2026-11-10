"""SQLAlchemy ORM 模型：行程规划领域实体。"""
from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


# TripDay.date 属性与类型名 `date` 同名，SQLAlchemy 在类命名空间求值注解时
# 会被列对象遮蔽，导致 `Mapped[date | None]` 解析失败 —— 使用模块级别名避开。
_Date = date


class Trip(Base):
    """一趟旅行（聚合根）。"""

    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    # 出发地（AI 规划时可选）：用于大交通方案查询与行程详情展示
    departure: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 出行性质（休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假；默认休闲）
    trip_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    travelers: Mapped[int] = mapped_column(Integer, default=1)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    """只读分享令牌：非空表示行程已生成分享链接，持令牌可免登录只读访问。"""
    edit_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    """受邀编辑令牌（高级权限）：非空表示行程已开放「受邀编辑权」。

    - 与 share_token 分离（特权分离）：分享链接默认只读，只有 owner 显式开放编辑
      后才生成 edit_token；受邀者凭 edit_token 可读 + 受限编辑（站点备注/勾选/顺序）。
    - owner 可随时清空（收回），不影响只读分享。
    """
    # ── 公开灵感画廊（task-gallery-featured）──────────────────
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    """是否发布到公开灵感画廊（运营/owner 主动标记；默认 False 不公开）。"""
    gallery_blurb: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """画廊一句话卖点（如「西湖环湖骑行 + 灵隐寺半日」）；发布时填写。"""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    days: Mapped[list[TripDay]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="TripDay.day_number"
    )
    plans: Mapped[list[TripPlan]] = relationship(
        back_populates="trip", order_by="TripPlan.created_at.desc()"
    )

    @property
    def escalated(self) -> bool:
        """人工兜底信号（task-human-escalation-eval）：派生属性，非 DB 列。

        从最新 AI 方案（TripPlan.plan_data.quality）派生：finalized=true /
        passed=false / degraded=true 任一命中 → 建议人工复核。ORM 属性供
        Pydantic from_attributes 直接读出（TripOut.escalated），零端点改动。
        无 plan / 正常通过 → False。plans relationship 已按 created_at 倒序。
        """
        try:
            plan = (self.plans or [None])[0]
        except Exception:  # noqa: BLE001 — 派生失败按不升级处理，绝不阻断读取
            return False
        if plan is None:
            return False
        from app.services.escalation_service import escalate_from_quality

        return escalate_from_quality((plan.plan_data or {}).get("quality"))


class TripDay(Base):
    """行程中的一天。"""

    __tablename__ = "trip_days"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[_Date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    trip: Mapped[Trip] = relationship(back_populates="days")
    stops: Mapped[list[Stop]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="Stop.order_index"
    )


class Stop(Base):
    """每日行程中的一个站点（景点/餐厅/住宿）。"""

    __tablename__ = "stops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day_id: Mapped[str] = mapped_column(ForeignKey("trip_days.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stop_type: Mapped[str] = mapped_column(String(20), default="attraction")  # attraction/food/hotel
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    """受邀编辑时的协作勾选状态（如「已确认要去 / 已完成」），owner 与受邀者共享。"""
    # 供地图/导出使用的可选元数据
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    day: Mapped[TripDay] = relationship(back_populates="stops")


class TripPlan(Base):
    """Agent 生成的完整行程方案（JSON 快照 + 轨迹）。"""

    __tablename__ = "trip_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    plan_data: Mapped[dict] = mapped_column(JSON, nullable=False)  # 完整行程 JSON
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)  # T-A-O 轨迹
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # openai/deepseek/ollama
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # running/completed/failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trip: Mapped[Trip] = relationship(back_populates="plans")


class PlanTask(Base):
    """异步规划任务：追踪 Agent 执行进度，结果回填。"""

    __tablename__ = "plan_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    request_data: Mapped[dict] = mapped_column(JSON, nullable=False)  # PlanRequest 快照
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/running/completed/failed
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # 规划过程事件流(phase / artifact),供轮询快照读取、前端阶段视图渲染
    events: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 阶段状态机(2期检查点门控预留):collecting/awaiting_review/assembling/reviewing/completed
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripComment(Base):
    """分享页协作：访客对行程的评论（凭 share_token 免登录，只读分享链路上的轻量互动）。"""

    __tablename__ = "trip_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    author_name: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 访客昵称（可选）
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StopVote(Base):
    """分享页协作：访客对行程站点的 👍/👎 投票。

    - voter_key 为服务端计算的轻量匿名身份（share_token + IP + UA 哈希），仅用作
      「一访客一票、可翻转」的去重依据，不是强身份认证（与只读分享同信任级别）。
    - 同一 visitor 对同一站点：不存在则新建；方向变化则更新；方向相同则幂等（不重复累计）。
    """

    __tablename__ = "stop_votes"
    __table_args__ = (UniqueConstraint("stop_id", "voter_key", name="uq_stop_votes_stop_voter"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id", ondelete="CASCADE"), index=True)
    voter_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=👍 / -1=👎
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareToken(Base):
    """分享/受邀编辑令牌的生命周期记录（方案 2：task-share-token-lifecycle）。

    与 trips.share_token / trips.edit_token 列并存（旧列承载「当前生效令牌」，
    本表承载「过期 / 吊销 / 最近使用」等生命周期元数据）：

    - kind: share=只读分享 / edit=受邀编辑
    - expires_at: null=永久有效；非 null 且已过期 → 读取侧按失效处理
    - revoked_at: owner 吊销时间；非 null → 立即失效（幂等）
    - last_used_at: 最近一次成功访问（审计），由读取端点更新
    - password_hash: 访问密码哈希（PBKDF2，task-share-gate-eval）；非空表示
      该令牌受密码保护；NULL=无锁旧数据兼容
    - 旧数据（trips 列已有 token 但本表无记录）→ 按永久、未吊销、免审计兼容
    """

    __tablename__ = "share_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # share / edit
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripFavorite(Base):
    """收藏灵感夹：登录用户收藏他人分享的行程。

    - 与 share 解耦：收藏只读引用（不复制行程），分享失效后收藏自然失效。
    - 同一 user + trip 唯一（幂等收藏/取消）。
    """

    __tablename__ = "trip_favorites"
    __table_args__ = (UniqueConstraint("user_id", "trip_id", name="uq_trip_favorites_user_trip"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FavoriteSpot(Base):
    """收藏地点（task-social-favorites-flow-eval：Plotline collect-first 范式落地）。

    - 与 TripFavorite 分离：TripFavorite 收藏「行程」（只读引用他人分享的行程），
      本表收藏「地点」——用户自己的收集箱：社交/笔记导入解析出的候选地点，
      行程未定时先攒着（collect-first），行程确定后再转行程
      （与 favorites-to-route 的「收藏行程→一键成路线」闭环衔接）。
    - 同一 user + 归一化名称（name_key）唯一：重复收藏幂等跳过。
    - 来源信息（platform + snippet）只作展示参考，绝不把外部内容当指令。
    """

    __tablename__ = "favorite_spots"
    __table_args__ = (UniqueConstraint("user_id", "name_key", name="uq_favorite_spots_user_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 归一化去重键：去空白 + 小写（与 social/note 导入的 dedup_key 同源思路）
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    stop_type: Mapped[str] = mapped_column(String(20), default="attraction")  # attraction/food/hotel
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Python 侧 default（每次插入取当前时刻，微秒区分）+ SQL 兜底 server_default
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(), server_default=func.now()
    )


class TripRating(Base):
    """行程评分 / 信任信号（task-trip-rating-signal：画廊与灵感缺「多少用户用过、几分」）。

    - 登录用户对行程评分（1-5 星）+ 「我去过」标记（visited=True）；
      同 user + trip 唯一（可改分 / 可翻转 visited，幂等）。
    - 只读聚合（count / avg / visited_count）供画廊卡片透出热度；
      评分本身不改变行程可见性——与 TripFavorite 同语义（存在即可见）。
    - 信任口径：avg 为真实用户评分均值，绝不由系统编造/加权（诚实标注）。
    - 归属：owner 与被评分行程无写扩散（任何登录用户可评公开可见行程，
      与收藏一致）；仅评分者可改/删自己的评分。
    """

    __tablename__ = "trip_ratings"
    __table_args__ = (UniqueConstraint("user_id", "trip_id", name="uq_trip_ratings_user_trip"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    visited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TripBooking(Base):
    """预订条目（task-booking-outlink：行程内「可预订」建议 + 凭证回填）。

    - 规划后由 BookingStep 产出「建议」（provider_url 直达 OTA 搜索页，用户自助完成交易），
      与 expense 的「实付」、plan 的「估算」三者区分；
    - ``reference``：plan.generated（编排层回填）/ user.confirmed（用户回填凭证）/
      channel.callback（渠道回调，本期未接）；
    - 状态机：suggested → pending → confirmed ⇄ cancelled。
      只允许带凭证（order_no/credential）进入 confirmed；suggested 可重复 upsert（幂等）。
    - 与 TripEvent 联动：confirm/cancel 记 booking.confirmed / booking.cancelled 事件；
    - probe_plan 非空：为旅程追踪「预订状态」投影保留挂载点（本期不落 probe）。
    - 归属：owner 可写，受邀 share/edit token 只读（与费用语义对齐）。
    """

    __tablename__ = "trip_bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="train", nullable=False)  # train/hotel
    provider: Mapped[str] = mapped_column(String(20), default="ctrip", nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provider_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    order_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="suggested", nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(20), default="plan.generated", nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)
    probe_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripEvent(Base):
    """行程事件日志（task-trip-event-notify）：修订/打卡/投票/评论等业务动作的事件流。

    - 用途：行程内「主动通知」最小版——owner 与受邀者订阅事件流，前端轮询或 WS 实时消费；
    - 事件是事实记录（append-only），不做状态承载（权威状态仍在 trip/stop 自身）；
    - ``event_type``：revise / check / skip / delay / comment / vote / edit / share；
    - ``payload``：可读摘要（含 i18n 文案 key 或直接文案 + 参数），前端可直接展示；
    - ``trip_id`` 索引 + ``created_at`` 排序：按行程查最近事件。
    """

    __tablename__ = "trip_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TripExpense(Base):
    """行中费用记录（task-expense-split-mini：Stippl/MonkeyTravel 行中管理一体化）。

    - 行程内的实际花费（金额/类别/支付人），与 stops.estimated_cost（估算）区分：
      估算进预算视图（compute_budget），实付进费用分摊视图（expense_service）。
    - ``payer``：支付人的自由文本姓名（如「小彭」），零凭证、零成员表依赖；
      空串表示「未指定」，不参与人均结余（见 expense_service.balance 处理）。
    - ``category``：food / transport / hotel / attraction / shopping / other（默认 other）。
    - 删除为物理删除（最小版：owner 页面可撤销误记）；金额不允许原地修改，
      修改 = 删除旧记录 + 新增（保持 append-only 记账语义，见 service 注释）。
    - 多币种（task-multi-currency-expense-eval）：
      - ``currency``：记账原币种（ISO 4217，默认 CNY——与预算/费用整体基准币种一致）；
      - ``rate_to_base``：记账时锁定的「1 原币 = ? 基准币」汇率（默认 1.0=CNY）；
      - ``amount_base``：按锁定汇率折算出的基准金额（默认 = amount）。
      汇率绝不由实时 API 注入（零凭证哲学），由用户填写或规则库兜底；
      append-only 语义下锁定汇率不可变，保证结余可复算、历史不漂移。
    """

    __tablename__ = "trip_expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    amount_base: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)
    rate_to_base: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    payer: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TripPassport(Base):
    """旅程护照（task-journey-passport：行中激励 + 徽章体系）。

    - 一行行程一条（trip_id 唯一）：phase（upcoming/live/finished）+ badges[] +
      最近进度时间 + 状态快照；徽章为确定性规则触发（幂等，只增不减）。
    - 与 TripEvent 联动：record_event 后 hook maybe_award；历史回填一次性投影。
    - 徽章墙是「完成感 + 分享素材」，绝不做成营销追踪（不采集第三方转化）。
    - 归属：owner 可写，受邀 share/edit token 只读（分享页徽章墙）。
    """

    __tablename__ = "trip_passports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), unique=True, index=True)
    phase: Mapped[str] = mapped_column(String(20), default="upcoming", nullable=False)
    badges: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{key,label,earned_at}]
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class XhsPublishTask(Base):
    """小红书发布任务（本机发布器模式）。

    **服务端不碰账号凭证**：这里只存"要发什么"，由用户自己浏览器里的
    扩展/助手去小红书创作平台填表并发布，再把结果回写。

    状态机：pending → claimed → filled → published
                                 ↘ failed / expired / cancelled
    """

    __tablename__ = "xhs_publish_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    trip_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    asset_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    note_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """领取任务的客户端标识（扩展实例），便于排查"是谁拿走的"。"""
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
