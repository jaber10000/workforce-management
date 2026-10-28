"""Private conversation between an employee and their team leader (observations, problems, shift questions), with images."""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_db, get_principal
from app.models.employee import Employee, RolePool
from app.models.message import TeamMessage

router = APIRouter(prefix="/messages", tags=["Team messages"], dependencies=[Depends(get_principal)])

MAX_IMAGE = 3 * 1024 * 1024
TOPICS = ("Observation", "Problem", "Shift question", "Leave", "Other")


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    topic: str | None = Field(default=None, max_length=80)
    image_b64: str | None = None
    image_name: str | None = Field(default=None, max_length=120)


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _emp(db: Session, employee_id: str) -> Employee:
    e = db.scalar(select(Employee).where(Employee.employee_id == employee_id))
    if not e:
        raise HTTPException(404, "Employee not found")
    return e


def _side(db: Session, p: Principal, target: Employee) -> str:
    """'employee' (the thread owner) or 'staff' (their own assigned team leader). Everyone else - other team leaders,
    managers and admins included - is refused: a conversation is private to the employee and their supervisor."""
    if p.role == "supervisor":
        mine = db.scalar(select(Employee.team).where(Employee.employee_id == (p.employee_id or "__none__")))
        if mine and target.team == mine:
            return "staff"
        raise HTTPException(403, "You can only read your own team's conversations")
    if p.role != "employee":
        raise HTTPException(403, "This conversation is private to the employee and their team leader")
    if p.employee_id and p.employee_id == target.employee_id:
        return "employee"
    raise HTTPException(403, "This conversation is private")


def _out(m: TeamMessage) -> dict:
    return {"id": m.id, "employee_id": m.employee_id, "sender": m.sender, "sender_name": m.sender_name, "side": m.side,
            "topic": m.topic, "text": m.body, "has_image": m.image_data is not None, "image_name": m.image_name,
            "image_size": m.image_size, "created_at": m.created_at.isoformat() if m.created_at else None}


def _leader(db: Session, e: Employee) -> dict | None:
    if not e.team:
        return None
    l = db.scalar(select(Employee).where(Employee.team == e.team, Employee.role_pool == RolePool.supervisor,
                                          Employee.is_active.is_(True)).order_by(Employee.employee_id))
    return {"employee_id": l.employee_id, "full_name": l.full_name} if l else None


@router.get("/topics")
def topics():
    return list(TOPICS)


@router.get("/threads")
def threads(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    """Employee: their own conversation. Team leader: every member of their own team. Managers/admins: none (private)."""
    if p.role == "employee":
        if not p.employee_id:
            return []
        emps = [_emp(db, p.employee_id)]
    elif p.role == "supervisor":
        mine = db.scalar(select(Employee.team).where(Employee.employee_id == (p.employee_id or "__none__")))
        emps = list(db.scalars(select(Employee).where(Employee.team == mine, Employee.is_active.is_(True),
                                                      Employee.role_pool != RolePool.supervisor)
                               .order_by(Employee.full_name))) if mine else []
    else:
        return []
    staff = p.role != "employee"
    flag = TeamMessage.read_by_staff if staff else TeamMessage.read_by_employee
    other_side = "employee" if staff else "staff"
    out = []
    for e in emps:
        last = db.scalar(select(TeamMessage).where(TeamMessage.employee_id == e.employee_id).order_by(TeamMessage.id.desc()).limit(1))
        unread = db.scalar(select(func.count()).select_from(TeamMessage).where(
            TeamMessage.employee_id == e.employee_id, TeamMessage.side == other_side, flag.is_(False))) or 0
        out.append({"employee_id": e.employee_id, "full_name": e.full_name, "role_pool": e.role_pool.value, "team": e.team,
                    "leader": _leader(db, e), "unread": unread, "last": _out(last) if last else None})
    out.sort(key=lambda t: t["last"]["created_at"] if t["last"] else "", reverse=True)
    return out


@router.get("/unread")
def unread(db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    return {"unread": sum(t["unread"] for t in threads(db, p))}


@router.get("/thread/{employee_id}")
def get_thread(employee_id: str, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    e = _emp(db, employee_id)
    side = _side(db, p, e)
    msgs = list(db.scalars(select(TeamMessage).where(TeamMessage.employee_id == employee_id).order_by(TeamMessage.id)))
    changed = False
    for m in msgs:  # opening the conversation marks the other side's messages as read
        if side == "staff" and m.side == "employee" and not m.read_by_staff:
            m.read_by_staff, changed = True, True
        if side == "employee" and m.side == "staff" and not m.read_by_employee:
            m.read_by_employee, changed = True, True
    if changed:
        db.commit()
    return {"employee": {"employee_id": e.employee_id, "full_name": e.full_name, "team": e.team},
            "leader": _leader(db, e), "me_side": side, "messages": [_out(m) for m in msgs]}


@router.post("/thread/{employee_id}", status_code=201)
def send(employee_id: str, body: MessageIn, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    e = _emp(db, employee_id)
    side = _side(db, p, e)
    text = body.text.strip()
    data = mime = None
    if body.image_b64:
        try:
            data = base64.b64decode(body.image_b64.split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "The image could not be read")
        if len(data) > MAX_IMAGE:
            raise HTTPException(413, f"The image is too large (max {MAX_IMAGE // 1024 // 1024} MB)")
        mime = _sniff(data)
        if not mime:
            raise HTTPException(422, "Only PNG, JPEG, GIF or WebP images can be sent")
    if not text and not data:
        raise HTTPException(422, "Write a message or attach an image")
    own = db.scalar(select(Employee.full_name).where(Employee.employee_id == (p.employee_id or "__none__")))
    m = TeamMessage(employee_id=employee_id, sender=p.username, sender_name=own or p.username, side=side,
                    topic=(body.topic or None) if side == "employee" or body.topic else None, body=text,
                    image_name=(body.image_name or "image")[:120] if data else None, image_mime=mime, image_data=data,
                    image_size=len(data) if data else None,
                    read_by_employee=side == "employee", read_by_staff=side == "staff")
    db.add(m)
    db.commit()
    db.refresh(m)
    return _out(m)


@router.get("/{message_id}/image")
def image(message_id: int, db: Session = Depends(get_db), p: Principal = Depends(get_principal)):
    m = db.get(TeamMessage, message_id)
    if not m or m.image_data is None:
        raise HTTPException(404, "Image not found")
    _side(db, p, _emp(db, m.employee_id))
    return Response(m.image_data, media_type=m.image_mime or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": "inline"})
