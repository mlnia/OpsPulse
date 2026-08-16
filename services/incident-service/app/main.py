import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

import redis
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from passlib.context import CryptContext
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, String, create_engine, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./opspulse.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-secret")
JWT_ALGORITHM = "HS256"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
passwords = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
provider = TracerProvider(resource=Resource.create({"service.name": "incident-service"}))
if endpoint := os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


class Base(DeclarativeBase):
    pass


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class UserRole(StrEnum):
    ADMIN = "admin"
    RESPONDER = "responder"
    VIEWER = "viewer"


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(180))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default=IncidentStatus.OPEN)
    service: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default=UserRole.VIEWER)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_email: Mapped[str] = mapped_column(String(180))
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentComment(Base):
    __tablename__ = "incident_comments"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    author_email: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentCreate(BaseModel):
    title: str = Field(min_length=4, max_length=180)
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    service: str = Field(min_length=2, max_length=100)


class IncidentUpdate(BaseModel):
    status: IncidentStatus


class IncidentOut(BaseModel):
    id: UUID
    title: str
    severity: str
    status: str
    service: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    email: str
    role: UserRole

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(BaseModel):
    id: UUID
    author_email: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SloSummary(BaseModel):
    total_incidents: int
    active_incidents: int
    resolved_incidents: int
    mttr_minutes: float | None


def publish(event_type: str, incident: Incident) -> None:
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.xadd("incident-events", {"type": event_type, "payload": json.dumps({"id": str(incident.id), "title": incident.title, "severity": incident.severity, "status": incident.status})})
    except redis.RedisError:
        # Events can be retried by an outbox in a production deployment.
        pass


def audit(session: Session, actor: User, action: str, incident: Incident) -> None:
    session.add(AuditLog(actor_email=actor.email, action=action, resource_id=str(incident.id)))


def create_token(user: User) -> str:
    return jwt.encode({"sub": user.email, "role": user.role}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token", headers={"WWW-Authenticate": "Bearer"})
    try:
        email = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM]).get("sub")
        if not email:
            raise credentials_error
    except JWTError as error:
        raise credentials_error from error
    with Session(engine) as session:
        user = session.query(User).filter_by(email=email).first()
        if user is None:
            raise credentials_error
        session.expunge(user)
        return user


def require_write_access(user: User = Depends(current_user)) -> User:
    if user.role not in {UserRole.ADMIN, UserRole.RESPONDER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Responder role required")
    return user


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@opspulse.local")
        if not session.query(User).filter_by(email=email).first():
            session.add(User(email=email, password_hash=passwords.hash(os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "ChangeMe123!")), role=UserRole.ADMIN))
            session.commit()
    yield


app = FastAPI(title="OpsPulse Incident Service", version="0.1.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/token", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenOut:
    with Session(engine) as session:
        user = session.query(User).filter_by(email=form.username).first()
        if user is None or not passwords.verify(form.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        return TokenOut(access_token=create_token(user), user=user)


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@app.get("/api/v1/incidents", response_model=list[IncidentOut])
def list_incidents(_: User = Depends(current_user)) -> list[Incident]:
    with Session(engine) as session:
        return list(session.query(Incident).order_by(Incident.created_at.desc()).all())


@app.post("/api/v1/incidents", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, actor: User = Depends(require_write_access)) -> Incident:
    with Session(engine) as session:
        with tracer.start_as_current_span("incident.create"):
            incident = Incident(**payload.model_dump())
            session.add(incident)
            session.flush()
            audit(session, actor, "incident.created", incident)
        session.commit()
        session.refresh(incident)
        publish("incident.created", incident)
        return incident


@app.patch("/api/v1/incidents/{incident_id}", response_model=IncidentOut)
def update_incident(incident_id: UUID, payload: IncidentUpdate, actor: User = Depends(require_write_access)) -> Incident:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        incident.status = payload.status
        audit(session, actor, "incident.status_changed", incident)
        session.commit()
        session.refresh(incident)
        publish("incident.updated", incident)
        return incident


@app.get("/api/v1/incidents/{incident_id}/audit")
def incident_audit(incident_id: UUID, _: User = Depends(current_user)) -> list[dict[str, str]]:
    with Session(engine) as session:
        logs = session.query(AuditLog).filter_by(resource_id=str(incident_id)).order_by(AuditLog.created_at.desc()).all()
        return [{"actor": log.actor_email, "action": log.action, "at": log.created_at.isoformat()} for log in logs]


@app.get("/api/v1/incidents/{incident_id}/comments", response_model=list[CommentOut])
def list_comments(incident_id: UUID, _: User = Depends(current_user)) -> list[IncidentComment]:
    with Session(engine) as session:
        return list(session.query(IncidentComment).filter_by(incident_id=incident_id).order_by(IncidentComment.created_at.desc()).all())


@app.post("/api/v1/incidents/{incident_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(incident_id: UUID, payload: CommentCreate, actor: User = Depends(require_write_access)) -> IncidentComment:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        comment = IncidentComment(incident_id=incident_id, author_email=actor.email, body=payload.body)
        session.add(comment)
        audit(session, actor, "incident.comment_added", incident)
        session.commit()
        session.refresh(comment)
        return comment


@app.get("/api/v1/analytics/slo", response_model=SloSummary)
def slo_summary(_: User = Depends(current_user)) -> SloSummary:
    with Session(engine) as session:
        incidents = list(session.query(Incident).all())
    resolved = [item for item in incidents if item.status == IncidentStatus.RESOLVED and item.updated_at and item.created_at]
    durations = [(item.updated_at - item.created_at).total_seconds() / 60 for item in resolved]
    return SloSummary(total_incidents=len(incidents), active_incidents=len(incidents) - len(resolved), resolved_incidents=len(resolved), mttr_minutes=round(sum(durations) / len(durations), 2) if durations else None)
