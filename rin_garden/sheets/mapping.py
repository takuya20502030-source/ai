"""既存Sheetの実ヘッダーと、こちらの正規スキーマ(`sheets/schemas.py`)の差異を
吸収するMapping層。

既存シートの列を削除・並び替え・追加することは一切行わない。canonicalな
フィールドに対応する列が既存シートに見つからない場合は、そのフィールドを
書き込まずスキップし、`unmapped_fields` として報告する(サイレントに無視しない)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HeaderMapping:
    """canonicalヘッダー名 -> 実シート上の列インデックス(0始まり)の対応表。"""

    actual_headers: list[str]
    canonical_to_index: dict[str, int] = field(default_factory=dict)
    unmapped_fields: list[str] = field(default_factory=list)
    extra_actual_headers: list[str] = field(default_factory=list)

    def row_from(self, data: dict[str, Any]) -> list[str]:
        """dataをactual_headersの列順に整列した行(文字列リスト)へ変換する。
        マッピングが無い列は空文字のままにする(既存シートの列構成は変更しない)。
        """
        row = [""] * len(self.actual_headers)
        for canonical_field, idx in self.canonical_to_index.items():
            if canonical_field in data:
                row[idx] = str(data[canonical_field])
        return row


def build_mapping(canonical_headers: list[str], actual_headers: list[str]) -> HeaderMapping:
    """canonicalヘッダーと実ヘッダーを名前で突き合わせる(完全一致優先、次に大小無視一致)。"""
    actual_lower = {h.strip().lower(): i for i, h in enumerate(actual_headers)}

    canonical_to_index: dict[str, int] = {}
    unmapped: list[str] = []
    for name in canonical_headers:
        if name in actual_headers:
            canonical_to_index[name] = actual_headers.index(name)
        elif name.strip().lower() in actual_lower:
            canonical_to_index[name] = actual_lower[name.strip().lower()]
        else:
            unmapped.append(name)

    matched_actual = set(canonical_to_index.values())
    extra_actual = [h for i, h in enumerate(actual_headers) if i not in matched_actual]

    return HeaderMapping(
        actual_headers=actual_headers,
        canonical_to_index=canonical_to_index,
        unmapped_fields=unmapped,
        extra_actual_headers=extra_actual,
    )
