"""GARDEN-6: 同一RaceSnapshotを6担当へ渡し、それぞれ独立にAnalysisResult
(=MemberFinding)を返すInterface。

ここではまだLLM接続を行わない。各担当はsnapshotに実際に含まれるデータの
有無・件数のみを根拠に、担当領域(`agents/*.md`)に沿った短いコメントを返す
構造上のスタブである。存在しないデータについて推測で予想内容を作らない。

最終統合は `rin_garden.analysis.garden6.integrate()` (既存構造)が引き続き担当する。
このモジュールはintegrate()の入力となるfindingsを揃えるところまでを担う。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from rin_garden.analysis.garden6 import MemberFinding
from rin_garden.analysis.snapshot import RaceSnapshot
from rin_garden.core.validation import DataConfidence


class Garden6Member(ABC):
    """GARDEN-6の1担当が実装するInterface。"""

    member_id: str

    @abstractmethod
    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        """同一のRaceSnapshotを受け取り、独立したMemberFindingを返す。"""


class RinMember(Garden6Member):
    member_id = "rin"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        entrant_count = len(snapshot.entrants())
        comment = (
            f"あたしからはまず状況整理。出走者{entrant_count}名分のデータを受け取ったよ。"
            f"データ確信度は{snapshot.source_confidence}。最終判断は美羽香・花奈・英梨紗・"
            "黒音・瑠那の分析が揃ってから出す。"
        )
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=snapshot.source_confidence,
            structured={"entrant_count": entrant_count},
        )


class MiukaMember(Garden6Member):
    member_id = "miuka"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        entrants = snapshot.entrants()
        scores = [e.get("score") for e in entrants if isinstance(e.get("score"), (int, float))]
        if scores:
            comment = f"競走得点: 最高{max(scores):.1f} / 最低{min(scores):.1f} / 件数{len(scores)}。"
            confidence = DataConfidence.CONFIRMED if len(scores) == len(entrants) else DataConfidence.ESTIMATED
        else:
            comment = "競走得点データが取得できていない。数値比較不可。"
            confidence = DataConfidence.INCOMPLETE
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=confidence,
            structured={"scores": scores},
        )


class KanaMember(Garden6Member):
    member_id = "kana"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        has_live = bool(snapshot.live_data)
        if has_live:
            comment = f"直前情報を{len(snapshot.live_data)}項目受け取ったよ。内容を確認するね。"
            confidence = DataConfidence.CONFIRMED
        else:
            comment = "直前情報(展示・気配等)はまだ届いていない。発走直前に再確認が必要。"
            confidence = DataConfidence.INCOMPLETE
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=confidence,
            structured={"live_data_keys": list(snapshot.live_data.keys())},
        )


class ErisaMember(Garden6Member):
    member_id = "erisa"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        entrants = snapshot.entrants()
        missing_by_entrant = {
            str(e.get("number", "?")): [k for k in ("score", "style", "line") if not e.get(k)]
            for e in entrants
            if any(not e.get(k) for k in ("score", "style", "line"))
        }
        if missing_by_entrant:
            comment = f"データ欠落あり: {missing_by_entrant}。この状態で確信度の高い評価は出せない。"
            confidence = DataConfidence.ESTIMATED
        else:
            comment = "現時点で明確なデータ欠落・矛盾は見当たらない。ただし過大評価バイアスは別途検証が必要。"
            confidence = DataConfidence.CONFIRMED
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=confidence,
            structured={"missing_by_entrant": missing_by_entrant},
        )


class KuroneMember(Garden6Member):
    member_id = "kurone"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        lines = {e.get("line") for e in snapshot.entrants() if e.get("line")}
        comment = f"ライン数{len(lines)}。ライン数が多いほど展開は読みにくくなる傾向がある。詳細は直前情報待ち。"
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=snapshot.source_confidence,
            structured={"line_count": len(lines)},
        )


class LunaMember(Garden6Member):
    member_id = "luna"

    def analyze(self, snapshot: RaceSnapshot) -> MemberFinding:
        has_result = snapshot.result is not None
        comment = (
            "このレースは未精算のため、バックテスト材料としてはまだ使えない。"
            if not has_result
            else "結果データが存在する。ただしこの担当は事前分析専用であり、精算はsettlementモジュールが行う。"
        )
        return MemberFinding(
            member_id=self.member_id,
            comment=comment,
            data_confidence=DataConfidence.CONFIRMED,
            structured={"has_result": has_result},
        )


MEMBER_REGISTRY: dict[str, type[Garden6Member]] = {
    "rin": RinMember,
    "miuka": MiukaMember,
    "kana": KanaMember,
    "erisa": ErisaMember,
    "kurone": KuroneMember,
    "luna": LunaMember,
}


def run_garden6(snapshot: RaceSnapshot) -> list[MemberFinding]:
    """同一snapshotを6担当全員へ渡し、それぞれ独立したMemberFindingを集める。

    最終統合(rank/chaos/decisionの確定)は行わない。呼び出し側が
    `rin_garden.analysis.garden6.integrate()` へこの結果を渡すこと。
    """
    return [member_cls().analyze(snapshot) for member_cls in MEMBER_REGISTRY.values()]
