"""GARDEN-6: 同一RaceSnapshotを6担当へ渡し、独立したAnalysisResultを得られること。

最終統合(integrate())は既存構造のまま変更しないことも合わせて確認する。
"""

from __future__ import annotations

from rin_garden.analysis.garden6 import MEMBER_IDS, integrate
from rin_garden.analysis.members import MEMBER_REGISTRY, run_garden6
from rin_garden.analysis.snapshot import RaceSnapshot
from rin_garden.analysis.value import ValueAssessment
from rin_garden.core.validation import DataConfidence


def _snapshot(**overrides) -> RaceSnapshot:
    base = dict(
        race_id="KEIRIN-2026-08-16-abc",
        sport="keirin",
        captured_at="2026-08-16T10:00:00+00:00",
        race_card={
            "entrants": [
                {"number": 1, "score": 100.0, "style": "先行", "line": "A"},
                {"number": 2, "score": 95.0, "style": "追込", "line": "A"},
            ]
        },
        market_odds={"1": 3.0},
        live_data={},
        result=None,
        source_confidence=DataConfidence.CONFIRMED,
    )
    base.update(overrides)
    return RaceSnapshot(**base)


def test_run_garden6_returns_one_distinct_finding_per_member():
    snapshot = _snapshot()

    findings = run_garden6(snapshot)

    assert len(findings) == len(MEMBER_REGISTRY) == 6
    member_ids = [f.member_id for f in findings]
    assert set(member_ids) == set(MEMBER_IDS)
    assert len(set(member_ids)) == 6  # 全員分、重複なく独立して存在する

    # 全員が同じ結論に寄せていない(コメントが一律ではない)ことを確認する
    comments = [f.comment for f in findings]
    assert len(set(comments)) == 6


def test_members_do_not_fabricate_missing_data():
    snapshot = _snapshot(race_card={"entrants": [{"number": 1, "style": "先行", "line": "A"}]}, live_data={})

    findings = {f.member_id: f for f in run_garden6(snapshot)}

    # scoreが無いため美羽香はCONFIRMEDと言い切らない
    assert findings["miuka"].data_confidence == DataConfidence.INCOMPLETE
    # 直前情報が無いため花奈もINCOMPLETEを明示する
    assert findings["kana"].data_confidence == DataConfidence.INCOMPLETE


def test_integrate_still_works_with_members_output():
    snapshot = _snapshot()
    findings = run_garden6(snapshot)
    value = ValueAssessment.build(estimated_probability=0.4, market_odds=3.0)

    analysis = integrate(snapshot.race_id, findings, rank="A", chaos=3, value=value)

    assert analysis.race_id == snapshot.race_id
    assert analysis.decision in ("BUY", "WAIT", "SKIP")
    assert len(analysis.findings) == 6
