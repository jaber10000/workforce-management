from sqlalchemy.orm import Session

from app.models.roster import AuditLog


def log(db: Session, action: str, entity_type: str, entity_id, details: dict | None = None,
        version_id: int | None = None, actor: str = "system") -> AuditLog:
    """Add an audit row to the current transaction (caller commits)."""
    row = AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=str(entity_id),
                   version_id=version_id, details=details or {})
    db.add(row)
    return row
