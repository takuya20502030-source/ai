"""リポジトリルート直下のconftest.py。

`rin_garden` パッケージを確実にimportできるよう、リポジトリルートをsys.pathへ
追加する。pytestの実行ディレクトリに依存させないための保険。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
