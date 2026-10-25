"""Argon2, RBAC, enkripsi field sensitif dan audit hash-chain."""
from __future__ import annotations
import hashlib, hmac, json
from collections import defaultdict
from datetime import datetime, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session
from rme.models import AuditLog, User

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
PERMISSIONS = {
 "admin_pendaftaran": {"dashboard:read","patient:create","patient:read","patient:nik:reveal","consent:create","visit:create","visit:read","visit:update","user:read"},
 "perawat": {"dashboard:read","patient:read","visit:read","visit:start","anamnesis:read","anamnesis:write","vitals:read","vitals:write","resume:read"},
 "dokter": {"dashboard:read","patient:read","patient:nik:reveal","visit:read","visit:start","visit:finish","anamnesis:read","anamnesis:write","vitals:read","vitals:write","resume:read","resume:write","resume:finalize","resume:addendum","ai:review","diagnosis:create","diagnosis:read"},
 "perekam_medis": {"dashboard:read","patient:read","patient:nik:reveal","visit:read","resume:read","icd:verify","audit:read","diagnosis:read","satusehat:read","satusehat:manage"},
 "pimpinan": {"dashboard:read","audit:read","user:read","registry:read"},
 "admin_sistem": {"dashboard:read","user:read","user:manage","registry:read","registry:manage","audit:read"},
}
class AuthorizationError(PermissionError): pass
class AuthenticationError(ValueError): pass

class SensitiveFieldCipher:
    def __init__(self, key: str):
        try: self.fernet = Fernet(key.encode("ascii"))
        except Exception as exc: raise ValueError("PII_ENCRYPTION_KEY bukan Fernet key valid.") from exc
        self.key = key.encode("ascii")
    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode("ascii")
    def decrypt(self, value: str) -> str:
        try: return self.fernet.decrypt(value.encode("ascii")).decode()
        except InvalidToken as exc: raise ValueError("Kunci enkripsi tidak cocok dengan data.") from exc
    def lookup_digest(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

def hash_password(password: str) -> str:
    if len(password) < 12: raise ValueError("Password minimal 12 karakter.")
    return HASHER.hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    try: return HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError): return False

class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, lock_seconds: int = 300):
        self.max_attempts, self.lock_seconds = max_attempts, lock_seconds
        self.attempts = defaultdict(list); self.locked_until = {}
    def locked(self, username: str, now: float) -> bool:
        return self.locked_until.get(username.lower(), 0) > now
    def fail(self, username: str, now: float) -> None:
        key = username.lower()
        self.attempts[key] = [t for t in self.attempts[key] if now - t <= self.lock_seconds] + [now]
        if len(self.attempts[key]) >= self.max_attempts: self.locked_until[key] = now + self.lock_seconds
    def success(self, username: str) -> None:
        self.attempts.pop(username.lower(), None); self.locked_until.pop(username.lower(), None)

def authenticate(session: Session, username: str, password: str, limiter: LoginRateLimiter, now: float) -> User:
    if limiter.locked(username, now): raise AuthenticationError("Terlalu banyak percobaan masuk; coba lagi setelah jeda keamanan.")
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.active or not verify_password(user.password_hash, password):
        limiter.fail(username, now); raise AuthenticationError("Nama pengguna atau kata sandi tidak valid.")
    limiter.success(username); return user

def require_permission(user: User, permission: str) -> None:
    if permission not in PERMISSIONS.get(user.role.code if user.role else "", set()):
        raise AuthorizationError(f"Tidak ada izin {permission} untuk peran {user.role.code if user.role else 'unknown'}.")

def _iso(value: datetime) -> str:
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()

def _payload(actor: str, action: str, kind: str, eid: str, stamp: str, details: str, prev: str) -> str:
    return json.dumps({"actor":actor,"action":action,"kind":kind,"entity_id":eid,"stamp":stamp,"details":details,"previous_hash":prev}, sort_keys=True, separators=(",",":"), ensure_ascii=False)

def append_audit(session: Session, actor: User | None, action: str, kind: str, entity_id: str | int, details: dict | None = None):
    actor_name = actor.username if actor else "system"
    details_json = json.dumps(details or {}, sort_keys=True, separators=(",",":"), ensure_ascii=False)
    last = session.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    prev = last.entry_hash if last else "0"*64
    stamp = _iso(datetime.now(timezone.utc))
    digest = hashlib.sha256(_payload(actor_name, action, kind, str(entity_id), stamp, details_json, prev).encode()).hexdigest()
    row = AuditLog(actor_id=actor.id if actor else None, actor_username=actor_name, action=action,
                   entity_type=kind, entity_id=str(entity_id), occurred_at=datetime.fromisoformat(stamp),
                   details_json=details_json, previous_hash=prev, entry_hash=digest)
    session.add(row); session.flush(); return row

def verify_audit_chain(session: Session) -> tuple[bool, int | None]:
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    prev = "0"*64
    for row in rows:
        raw = _payload(row.actor_username,row.action,row.entity_type,row.entity_id,_iso(row.occurred_at),row.details_json,prev)
        expected = hashlib.sha256(raw.encode()).hexdigest()
        if row.previous_hash != prev or not hmac.compare_digest(row.entry_hash, expected): return False, row.id
        prev = row.entry_hash
    return True, None
