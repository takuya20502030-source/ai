from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from rin_garden.core.final_lock import FinalLockService
from rin_garden.core.identity import build_race_id
from rin_garden.core.logging import AuditLogger
from rin_garden.core.pre_fix import PreFixService
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.settlement.result_loader import ResultLoaderService
from rin_garden.settlement.settlement import SettlementService


@pytest.fixture
def data_root(tmp_path: Path) -> dict[str, Path]:
    return {
        "normalized_dir": tmp_path / "data" / "normalized",
        "pre_dir": tmp_path / "data" / "pre",
        "final_dir": tmp_path / "data" / "final",
        "results_dir": tmp_path / "data" / "results",
        "audit_log_file": tmp_path / "logs" / "audit.log",
    }


@pytest.fixture
def audit_logger(data_root: dict[str, Path]) -> AuditLogger:
    return AuditLogger(data_root["audit_log_file"])


@pytest.fixture
def race_master_store(data_root: dict[str, Path]) -> RaceMasterStore:
    return RaceMasterStore(data_root["normalized_dir"])


@pytest.fixture
def pre_fix_service(data_root, race_master_store, audit_logger) -> PreFixService:
    return PreFixService(data_root["pre_dir"], race_master_store, audit_logger)


@pytest.fixture
def final_lock_service(data_root, race_master_store, audit_logger) -> FinalLockService:
    return FinalLockService(data_root["final_dir"], race_master_store, audit_logger)


@pytest.fixture
def result_loader_service(data_root, race_master_store, audit_logger) -> ResultLoaderService:
    return ResultLoaderService(data_root["results_dir"], race_master_store, audit_logger)


@pytest.fixture
def settlement_service(data_root, race_master_store, audit_logger) -> SettlementService:
    return SettlementService(data_root["results_dir"], race_master_store, audit_logger)


@pytest.fixture
def make_race_master(race_master_store: RaceMasterStore):
    """発走時刻を未来/過去にずらしてRaceMasterを作るファクトリ。"""

    def _make(
        sport: str = "jra",
        date: str = "2026-08-16",
        venue: str = "chukyo",
        race_number: int = 11,
        event_id: str = "evt-0001",
        starts_in_minutes: int = 60,
    ) -> RaceMaster:
        race_id = build_race_id(sport, date, venue, race_number, event_id)
        scheduled_start = to_iso(utcnow() + timedelta(minutes=starts_in_minutes))
        rm = race_master_store.create_scheduled(
            sport=sport,
            date=date,
            venue=venue,
            race_number=race_number,
            race_id=race_id,
            event_id=event_id,
            canonical_source="test-fixture",
            scheduled_start=scheduled_start,
        )
        return rm

    return _make


def make_pre_kwargs(race_id: str) -> dict:
    return dict(
        race_id=race_id,
        timestamp=to_iso(utcnow()),
        data_snapshot={"note": "test snapshot"},
        garden6_analysis={"rin": "test comment"},
        rank="A",
        chaos=3,
        confidence="CONFIRMED",
        predicted_scenario={"label": "normal"},
        bets=[{"type": "win", "target": "1", "amount": 100}],
        fair_probability={"1": 0.4},
        fair_odds={"1": 2.5},
        market_odds={"1": 3.0},
        expected_value={"1": 1.2},
    )


def make_final_kwargs(race_id: str, decision: str = "BUY") -> dict:
    return dict(
        race_id=race_id,
        timestamp=to_iso(utcnow()),
        marks={"1": "◎"},
        evaluation={"1": "A"},
        bets=[{"type": "win", "target": "1"}],
        amounts={"1": 1000},
        decision=decision,
    )
