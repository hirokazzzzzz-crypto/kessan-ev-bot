"""JPX基準適合度(近似)の入力データを手動で積み上げるためのJSONストア。

浮動株比率データを自動取得できないため、ユーザー(またはCLI/ダッシュボード経由)が
銘柄ごとに手入力した値をここに保存する。cli.py / app.py の両方から使う共通ロジック。
"""
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "topix_fit_inputs.json"


def load_fit_inputs(path=None) -> dict:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_fit_inputs(data: dict, path=None) -> Path:
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
