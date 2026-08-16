"""Ticket: race_id + account + ticket_id を一意キーとする個別買い目記録。

FINAL-LOCKで確定した買い目(bets)を実際の購入単位まで分解した記録。1 Accountに
つき0件以上のTicketを許容する。Ticketは発走前に確定するものとして扱い、
NO POST-HOCの対象とする(結果が判明した後の新規Ticket作成は禁止)。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.account import AccountRegistry, UnknownAccountError
from rin_garden.core.identity import IdentityMismatchError, verify_identity
from rin_garden.core.locks import PostHocBlockedError, enforce_final_lock_timing
from rin_garden.core.logging import AuditLogger, OP_IDENTITY_MISMATCH, OP_POST_HOC_BLOCKED, OP_WRITE_FAILED
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.storage import ImmutableRecordConflictError
from rin_garden.core.timeutil import to_iso, utcnow


@dataclass
class Ticket:
    race_id: str
    account: str
    ticket_id: str
    bet_type: str
    selection: str
    stake: float
    lock_odds: float | None = None
    status: str = "LOCKED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TicketService:
    """race_id + account + ticket_id を一意キーとするTicketの作成を担当する(immutable)。"""

    def __init__(
        self,
        tickets_dir: Path,
        race_master_store: RaceMasterStore,
        account_registry: AccountRegistry,
        audit_logger: AuditLogger,
    ):
        self.tickets_dir = Path(tickets_dir)
        self.race_master_store = race_master_store
        self.account_registry = account_registry
        self.audit_logger = audit_logger

    def _path(self, sport: str, date: str, race_id: str, account: str, ticket_id: str) -> Path:
        return self.tickets_dir / sport / date / race_id / account / f"{ticket_id}.json"

    def create(self, race_master: RaceMaster, ticket: Ticket, now: str | None = None) -> Ticket:
        """Ticketを新規作成する。race_id + account + ticket_idの組み合わせで不変。"""
        now = now or to_iso(utcnow())

        try:
            verify_identity(race_master.identity(), {"race_id": ticket.race_id})
        except IdentityMismatchError as exc:
            self.audit_logger.log(
                OP_IDENTITY_MISMATCH,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "ticket.create",
                str(exc),
                account=ticket.account,
            )
            raise

        try:
            self.account_registry.get(ticket.account)
        except UnknownAccountError as exc:
            self.audit_logger.log(
                OP_WRITE_FAILED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "ticket.create",
                str(exc),
                account=ticket.account,
            )
            raise

        if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
            exc = PostHocBlockedError(
                f"race_id={race_master.race_id} already has a result (status={race_master.status}); "
                "Ticket cannot be created after the fact"
            )
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "ticket.create",
                str(exc),
                account=ticket.account,
            )
            raise exc

        if race_master.scheduled_start is None:
            raise ValueError("race_master.scheduled_start is required to enforce Ticket timing")

        try:
            enforce_final_lock_timing(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "ticket.create",
                str(exc),
                account=ticket.account,
            )
            raise

        path = self._path(race_master.sport, race_master.date, race_master.race_id, ticket.account, ticket.ticket_id)
        try:
            storage.write_json_once(path, ticket.to_dict())
        except ImmutableRecordConflictError as exc:
            self.audit_logger.log(
                OP_WRITE_FAILED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "ticket.create",
                str(exc),
                account=ticket.account,
            )
            raise

        return ticket

    def list_tickets(self, sport: str, date: str, race_id: str, account: str) -> list[dict[str, Any]]:
        dir_path = self.tickets_dir / sport / date / race_id / account
        if not dir_path.exists():
            return []
        return [storage.read_json(p) for p in sorted(dir_path.glob("*.json"))]
