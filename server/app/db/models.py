"""SQLAlchemy models. Personal payloads are *_enc or *_hash columns. Index columns stay plain."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseStatus(enum.StrEnum):
    intake = "intake"
    confirming = "confirming"
    ready_for_mandate = "ready_for_mandate"
    mandate_active = "mandate_active"
    outreach = "outreach"
    awaiting_provider = "awaiting_provider"
    awaiting_consumer = "awaiting_consumer"
    provider_claimed_resolved = "provider_claimed_resolved"
    resolved_consumer_confirmed = "resolved_consumer_confirmed"
    closed = "closed"
    deleted = "deleted"


class EntityType(enum.StrEnum):
    marketplace = "marketplace"
    seller_on_marketplace = "seller_on_marketplace"
    direct_seller = "direct_seller"
    payment_intermediary = "payment_intermediary"
    unknown = "unknown"


class FactSource(enum.StrEnum):
    consumer_said = "consumer_said"
    evidence = "evidence"
    provider_said = "provider_said"


class FactCertainty(enum.StrEnum):
    stated = "stated"
    inferred = "inferred"
    approximate = "approximate"
    not_stated = "not_stated"


class ConfirmationState(enum.StrEnum):
    unconfirmed = "unconfirmed"
    confirmed = "confirmed"


class PromiseStatus(enum.StrEnum):
    open = "open"
    claimed_kept = "claimed_kept"
    claimed_broken = "claimed_broken"
    overdue = "overdue"
    withdrawn = "withdrawn"


class ApprovalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class ApprovalKind(enum.StrEnum):
    contact = "contact"
    summary = "summary"
    disclosure = "disclosure"
    send_image_to_llm = "send_image_to_llm"


class RunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    paused_for_approval = "paused_for_approval"
    failed = "failed"
    completed = "completed"


class DeadlineStatus(enum.StrEnum):
    scheduled = "scheduled"
    fired = "fired"
    cancelled = "cancelled"


class VoiceState(enum.StrEnum):
    created = "created"
    active = "active"
    closed = "closed"
    killed = "killed"
    expired = "expired"


class CallRole(enum.StrEnum):
    consumer = "consumer"
    provider_human = "provider_human"


class CallMode(enum.StrEnum):
    voice = "voice"
    text = "text"


class TagReviewState(enum.StrEnum):
    unreviewed = "unreviewed"
    llm_reviewed = "llm_reviewed"
    needs_attention = "needs_attention"
    legal_reviewed = "legal_reviewed"


def _enum(kind: type[enum.StrEnum], name: str) -> Enum:
    return Enum(kind, name=name, native_enum=True, values_callable=lambda items: [item.value for item in items])


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email_enc: Mapped[bytes] = mapped_column(LargeBinary)
    password_hash: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    step_up_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    terms_version: Mapped[str] = mapped_column(String(32))


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    label_enc: Mapped[bytes] = mapped_column(LargeBinary)
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    entity_type_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id_formats_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    contacts_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    escalation_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[CaseStatus] = mapped_column(_enum(CaseStatus, "case_status"), default=CaseStatus.intake)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    complaint_type: Mapped[str] = mapped_column(String(64), default="online_refund")
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("providers.id"), nullable=True)
    remedy_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    data_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("case_id", "field", "version", name="uq_fact_case_field_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    value_enc: Mapped[bytes] = mapped_column(LargeBinary)
    normalized_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    source: Mapped[FactSource] = mapped_column(_enum(FactSource, "fact_source"))
    certainty: Mapped[FactCertainty] = mapped_column(_enum(FactCertainty, "fact_certainty"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    phrase_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    confirmation_state: Mapped[ConfirmationState] = mapped_column(
        _enum(ConfirmationState, "confirmation_state"), default=ConfirmationState.unconfirmed
    )
    confirmed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facts.id"), nullable=True)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    file_ref: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32))
    ocr_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fields_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    timeline_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    sent_to_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    vision_approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    body_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Promise(Base):
    __tablename__ = "promises"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    who_enc: Mapped[bytes] = mapped_column(LargeBinary)
    what_enc: Mapped[bytes] = mapped_column(LargeBinary)
    by_when: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PromiseStatus] = mapped_column(_enum(PromiseStatus, "promise_status"))


class Deadline(Base):
    __tablename__ = "deadlines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[DeadlineStatus] = mapped_column(_enum(DeadlineStatus, "deadline_status"))


class Mandate(Base):
    __tablename__ = "mandates"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_mandate_case_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    goal_enc: Mapped[bytes] = mapped_column(LargeBinary)
    allowed_actions_enc: Mapped[bytes] = mapped_column(LargeBinary)
    disclosure_enc: Mapped[bytes] = mapped_column(LargeBinary)
    limits_enc: Mapped[bytes] = mapped_column(LargeBinary)
    channels_enc: Mapped[bytes] = mapped_column(LargeBinary)
    call_limit_seconds: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[ApprovalKind] = mapped_column(_enum(ApprovalKind, "approval_kind"))
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[ApprovalStatus] = mapped_column(_enum(ApprovalStatus, "approval_status"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    graph: Mapped[str] = mapped_column(String(64))
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("case_id", "idempotency_key", name="uq_run_case_idempotency"),)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    role: Mapped[CallRole] = mapped_column(_enum(CallRole, "call_role"))
    mode: Mapped[CallMode] = mapped_column(_enum(CallMode, "call_mode"))
    transcript_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    role: Mapped[CallRole] = mapped_column(_enum(CallRole, "voice_role"))
    ws_token_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    state: Mapped[VoiceState] = mapped_column(_enum(VoiceState, "voice_state"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stt_seconds: Mapped[float] = mapped_column(Float, default=0)
    tts_characters: Mapped[int] = mapped_column(Integer, default=0)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="in_app")
    body_enc: Mapped[bytes] = mapped_column(LargeBinary)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32))


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    channel: Mapped[str] = mapped_column(String(32), default="in_app")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegalChunk(Base):
    __tablename__ = "legal_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    layer: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    section: Mapped[str] = mapped_column(String(128))
    chunk_enc: Mapped[bytes] = mapped_column(LargeBinary)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    entity_tags_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tag_review_state: Mapped[TagReviewState] = mapped_column(
        _enum(TagReviewState, "tag_review_state"), default=TagReviewState.unreviewed
    )
    rationale_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    reviewer_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64))
    model_ids: Mapped[str] = mapped_column(Text)
    prompt_hashes: Mapped[str] = mapped_column(Text)
    repeat_count: Mapped[int] = mapped_column(Integer)
    scores_enc: Mapped[bytes] = mapped_column(LargeBinary)
    cost: Mapped[float] = mapped_column(Float, default=0)


class CaseStore:
    """Small repository used by services. Graphs will call a port with the same verbs later."""

    def __init__(self, session) -> None:
        self.session = session

    def add(self, row) -> None:
        self.session.add(row)

    def get_case(self, case_id: uuid.UUID) -> Case | None:
        return self.session.get(Case, case_id)

    def list_facts(self, case_id: uuid.UUID) -> list[Fact]:
        return list(self.session.query(Fact).filter(Fact.case_id == case_id).order_by(Fact.field, Fact.version))
