#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競馬予想マスター Ver1.8 JSON実行エンジン。

入力JSON形式:
{
  "レース情報": {...},
  "出走馬": [{...}, ...]
}
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


LOCAL_COURSES = {"函館", "札幌", "福島", "新潟", "小倉"}
REQUIRED_RACE_FIELDS = ("レース名", "開催日", "開催場", "距離")
REQUIRED_HORSE_FIELDS = ("馬番", "馬名")
SCORE_FIELDS = ("能力評価", "再現性評価", "距離適性", "開催場適性", "展開評価", "期待値評価")
SUPPORTED_TEMPLATE_MAJOR_VERSIONS = {1}
DEFAULT_WEIGHTS = {
    "能力評価": 0.25,
    "再現性評価": 0.25,
    "距離適性": 0.15,
    "開催場適性": 0.15,
    "展開評価": 0.10,
    "期待値評価": 0.10,
}
SUMMER_WEIGHTS = {
    "能力評価": 0.15,
    "再現性評価": 0.15,
    "距離適性": 0.20,
    "開催場適性": 0.25,
    "展開評価": 0.20,
    "期待値評価": 0.05,
}
RACE_TYPE_KEY_MAP = {
    "能力": "能力評価",
    "再現性": "再現性評価",
    "距離適性": "距離適性",
    "開催場適性": "開催場適性",
    "展開": "展開評価",
    "期待値": "期待値評価",
}


class KeibaEngineError(ValueError):
    """入力または設定が不正な場合の例外。"""


class KeibaEngine:
    def __init__(self, template_path: str | Path, learning_log_path: str | Path):
        self.template_path = Path(template_path).expanduser().resolve()
        self.learning_log_path = Path(learning_log_path).expanduser().resolve()
        self.template = self.load_json(self.template_path)
        self.learning_log = self.load_json(self.learning_log_path)
        self.diagnostics: list[dict[str, str]] = []
        self._validate_config()

    @staticmethod
    def load_json(path: str | Path) -> dict[str, Any]:
        path = Path(path)
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except FileNotFoundError as exc:
            raise KeibaEngineError(f"JSONファイルが見つかりません: {path}") from exc
        except json.JSONDecodeError as exc:
            raise KeibaEngineError(
                f"JSON構文エラー: {path} ({exc.lineno}行 {exc.colno}列: {exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise KeibaEngineError(f"JSONの最上位はオブジェクトである必要があります: {path}")
        return data

    @staticmethod
    def save_json(path: str | Path, data: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _validate_config(self) -> None:
        if "採点システム" not in self.template:
            raise KeibaEngineError("予想テンプレートに「採点システム」がありません")
        if not isinstance(self.learning_log.get("学習ログ", []), list):
            raise KeibaEngineError("学習ログ.json の「学習ログ」は配列である必要があります")
        self.diagnostics = self.run_diagnostics()

    def template_version(self) -> str:
        return str(
            self.template.get("template_version")
            or self.template.get("テンプレートバージョン")
            or self.template.get("バージョン")
            or "不明"
        )

    def configured_score_fields(self) -> tuple[str, ...]:
        configured = self.template.get("エンジン設定", {}).get("評価項目")
        if isinstance(configured, list) and configured:
            fields = [str(field) for field in configured if str(field).strip()]
            return tuple(dict.fromkeys(fields))
        return SCORE_FIELDS

    def run_diagnostics(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []

        def add(level: str, code: str, message: str) -> None:
            issues.append({"レベル": level, "コード": code, "内容": message})

        version = self.template_version()
        try:
            major = int(version.split(".", 1)[0])
            if major not in SUPPORTED_TEMPLATE_MAJOR_VERSIONS:
                add("警告", "UNSUPPORTED_MAJOR_VERSION", f"テンプレート主要バージョン {major} は動作保証外です")
        except ValueError:
            add("警告", "INVALID_VERSION", f"テンプレートバージョンを解析できません: {version}")

        if not self.template.get("評価優先順位"):
            add("警告", "MISSING_PRIORITY", "「評価優先順位」が未設定です")
        if not self.learning_log.get("累積傾向分析", {}).get("内部補正値_累積"):
            add("情報", "MISSING_CUMULATIVE_BIAS", "累積補正値が未保存です。ログから実行時集計します")

        configured_fields = set(self.configured_score_fields())
        default_weights = set(self.get_configured_default_weights())
        missing_weights = configured_fields - default_weights
        if missing_weights:
            add("警告", "MISSING_SCORE_WEIGHTS", f"通常重みがない評価項目: {', '.join(sorted(missing_weights))}")

        known_top_level = {
            "template_version", "テンプレートバージョン", "バージョン", "system_name", "エンジン設定",
            "レース識別ルール", "実行モード", "判断制限", "評価優先順位", "夏競馬モード",
            "採点システム", "レースタイプ評価", "コースタイプ評価", "距離適性評価",
            "ローカル開催補正", "ペース分析", "G1開催場巧者評価", "人気薄実力馬チェック",
            "評価除外防止チェック", "能力保険枠", "P群運用ルール", "馬評価", "購入判断",
            "直前馬場変更補正", "馬券変換ルール", "馬券戦略", "ワイド資金配分ルール",
            "BOX最適化チェック", "BOX最終確認", "リスク管理", "期待値と再現性バランス",
            "最終判断", "レース後検証", "レース後学習ログ", "更新履歴",
        }
        unknown = sorted(set(self.template) - known_top_level)
        if unknown:
            add("情報", "UNKNOWN_TEMPLATE_SECTIONS", f"エンジン未接続の可能性がある新規セクション: {', '.join(unknown)}")
        return issues

    def get_configured_default_weights(self) -> dict[str, float]:
        configured = self.template.get("エンジン設定", {}).get("通常重み")
        if isinstance(configured, dict) and configured:
            return {str(key): self._number(value) for key, value in configured.items()}
        return DEFAULT_WEIGHTS.copy()

    def aggregate_learning_bias(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for entry in self.learning_log.get("学習ログ", []):
            if not isinstance(entry, dict):
                continue
            values = entry.get("内部補正値", entry.get("内部補正メモ", {}))
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                totals[str(key)] = totals.get(str(key), 0.0) + self._number(value)
        return totals

    def refresh_learning_summary(self) -> dict[str, float]:
        totals = self.aggregate_learning_bias()
        analysis = self.learning_log.setdefault("累積傾向分析", {})
        analysis["内部補正値_累積"] = {
            key: int(value) if value.is_integer() else value for key, value in sorted(totals.items())
        }
        return totals

    def create_backup(self, backup_dir: str | Path) -> list[str]:
        destination = Path(backup_dir)
        destination.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        copied: list[str] = []
        for source in (self.template_path, self.learning_log_path):
            target = destination / f"{source.stem}_{stamp}{source.suffix}"
            shutil.copy2(source, target)
            copied.append(str(target.resolve()))
        return copied

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return float(value)
        try:
            return float(str(value).replace("%", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _truthy(horse: dict[str, Any], *keys: str) -> bool:
        return any(horse.get(key) is True or horse.get(key) == 1 for key in keys)

    @staticmethod
    def _date(date_text: Any) -> datetime | None:
        if not date_text:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
            try:
                return datetime.strptime(str(date_text), fmt)
            except ValueError:
                continue
        return None

    def validate_input(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        race_info = payload.get("レース情報")
        horses = payload.get("出走馬", payload.get("馬", payload.get("horses")))
        if not isinstance(race_info, dict):
            raise KeibaEngineError("入力JSONにオブジェクト形式の「レース情報」が必要です")
        if not isinstance(horses, list) or not horses:
            raise KeibaEngineError("入力JSONに1頭以上の配列形式の「出走馬」が必要です")

        missing_race = [key for key in REQUIRED_RACE_FIELDS if not race_info.get(key)]
        if missing_race:
            raise KeibaEngineError(f"レース情報の必須項目が不足しています: {', '.join(missing_race)}")
        if self._date(race_info.get("開催日")) is None:
            raise KeibaEngineError("開催日は YYYY-MM-DD、YYYY/MM/DD、またはYYYY年MM月DD日で指定してください")

        seen_numbers: set[Any] = set()
        for index, horse in enumerate(horses, 1):
            if not isinstance(horse, dict):
                raise KeibaEngineError(f"出走馬[{index}]はオブジェクトである必要があります")
            missing = [key for key in REQUIRED_HORSE_FIELDS if horse.get(key) in (None, "")]
            if missing:
                raise KeibaEngineError(f"出走馬[{index}]の必須項目が不足しています: {', '.join(missing)}")
            if horse["馬番"] in seen_numbers:
                raise KeibaEngineError(f"馬番が重複しています: {horse['馬番']}")
            seen_numbers.add(horse["馬番"])
        return race_info, horses

    def is_summer_mode(self, race_info: dict[str, Any]) -> bool:
        if race_info.get("開催場") not in LOCAL_COURSES:
            return False
        date = self._date(race_info.get("開催日"))
        if date is None:
            return False
        # テンプレート記載の「6月中旬〜9月初旬」を具体化。
        return (date.month == 6 and date.day >= 15) or date.month in (7, 8) or (
            date.month == 9 and date.day <= 10
        )

    def get_priority(self, race_info: dict[str, Any]) -> list[str]:
        if self.is_summer_mode(race_info):
            return self.template.get("夏競馬モード", {}).get("評価優先順位", [])
        return self.template.get("評価優先順位", [])

    def get_learning_bias(self) -> dict[str, float]:
        values = self.learning_log.get("累積傾向分析", {}).get("内部補正値_累積", {})
        saved = {key: self._number(value) for key, value in values.items()} if isinstance(values, dict) else {}
        aggregated = self.aggregate_learning_bias()
        # ログが追加された後に累積欄が未更新でも、新しい集計値を優先する。
        return aggregated or saved

    def get_weights(self, race_info: dict[str, Any]) -> dict[str, float]:
        if self.is_summer_mode(race_info):
            configured = self.template.get("エンジン設定", {}).get("夏競馬重み")
            return self._normalize_weights(configured if isinstance(configured, dict) else SUMMER_WEIGHTS)
        race_type = race_info.get("レースタイプ")
        configured = self.template.get("レースタイプ評価", {}).get("重み設定", {}).get(race_type)
        if isinstance(configured, dict):
            weights = {
                RACE_TYPE_KEY_MAP[key]: self._number(value)
                for key, value in configured.items()
                if key in RACE_TYPE_KEY_MAP
            }
            if weights and sum(weights.values()) > 0:
                return self._normalize_weights(weights)
        return self._normalize_weights(self.get_configured_default_weights())

    def _normalize_weights(self, weights: dict[str, Any]) -> dict[str, float]:
        fields = self.configured_score_fields()
        normalized = {field: self._number(weights.get(field), 0) for field in fields}
        total = sum(normalized.values())
        if total <= 0:
            fallback = {field: DEFAULT_WEIGHTS.get(field, 0) for field in fields}
            total = sum(fallback.values()) or 1
            return {key: value / total for key, value in fallback.items()}
        return {key: value / total for key, value in normalized.items()}

    def _apply_rule_adjustments(
        self, horse: dict[str, Any], race_info: dict[str, Any], scores: dict[str, float]
    ) -> tuple[dict[str, float], list[str]]:
        reasons: list[str] = []
        course = race_info.get("開催場", "")
        track = str(race_info.get("馬場", race_info.get("馬場状態", "")))
        distance = str(race_info.get("距離", ""))

        def add(field: str, amount: float, reason: str) -> None:
            if field not in scores:
                return
            scores[field] = self._clamp(scores[field] + amount)
            reasons.append(f"{reason}: {field}{amount:+g}")

        if self._truthy(horse, "G1連対歴", "G1連対実績"):
            add("能力評価", 5, "G1連対実績")
        if self._truthy(horse, "前走敗因明確", "前走不利"):
            add("再現性評価", 5, "前走敗因・不利を考慮")
        if self._truthy(horse, "距離短縮歓迎"):
            add("距離適性", 5, "距離短縮歓迎")
        if self._truthy(horse, "距離延長歓迎"):
            add("距離適性", 10, "距離延長歓迎")
        if self._truthy(horse, "折り合い優秀", "持続力型"):
            add("距離適性", 5, "距離適性加点")
        if self._truthy(horse, "逃げ馬", "単騎逃げ") and self._number(race_info.get("逃げ馬数"), 99) <= 1:
            add("展開評価", 10, "逃げ馬0〜1頭")
        if self._truthy(horse, "初ブリンカー") and self._truthy(horse, "調教良好") and self._truthy(horse, "馬体重良化"):
            add("展開評価", 5, "初ブリンカー＋調教＋馬体重良化")
            add("再現性評価", 5, "初ブリンカー＋調教＋馬体重良化")

        if self.is_summer_mode(race_info):
            if course in ("函館", "札幌") and self._truthy(horse, "洋芝適性", "洋芝実績"):
                add("開催場適性", 10, "洋芝適性")
            if self._truthy(horse, "滞在競馬実績"):
                add("開催場適性", 5, "滞在競馬実績")
            if course in ("函館", "札幌") and self._truthy(horse, "開幕週先行", "先行馬"):
                add("展開評価", 10, "函館・札幌開幕週先行")
            if course in ("函館", "福島", "小倉") and self._truthy(horse, "小回り適性"):
                add("開催場適性", 8, "小回り適性")
            if course == "新潟" and "1000" in distance and self._truthy(horse, "外枠"):
                add("展開評価", 10, "新潟千直外枠")

        if any(value in track for value in ("稍重", "重", "不良")):
            if self._truthy(horse, "道悪実績", "道悪適性"):
                add("開催場適性", 10, "道悪適性")
            if self._truthy(horse, "逃げ馬", "先行馬"):
                add("展開評価", 7, "道悪の逃げ・先行")
            if self._truthy(horse, "持続力型"):
                add("再現性評価", 10, "道悪の持続力")
            if self._truthy(horse, "高速瞬発力型"):
                add("開催場適性", -7, "道悪の高速瞬発力型")

        for field in self.configured_score_fields():
            manual = self._number(horse.get(f"{field}補正"), 0)
            if manual:
                add(field, manual, "入力指定補正")
        return scores, reasons

    def calculate_risk(self, horse: dict[str, Any]) -> tuple[float, str]:
        if "リスク補正" in horse:
            risk = self._clamp(self._number(horse.get("リスク補正")), 0, 30)
        else:
            total_risk = self._number(horse.get("リスク評価"), 0)
            for key in ("展開崩壊リスク", "位置取りリスク", "馬場不安", "再現性不安", "G1プレッシャー"):
                total_risk += self._number(horse.get(key), 0)
            risk = 0 if total_risk < 30 else 5 if total_risk < 45 else 10
        return risk, "危険域" if risk >= 10 or self._number(horse.get("リスク評価")) >= 60 else "許容"

    def classify_horse(self, horse: dict[str, Any]) -> str:
        score = self._number(horse.get("総合評価"))
        course_score = self._number(horse.get("補正後評価", {}).get("開催場適性"))
        ability = self._number(horse.get("補正後評価", {}).get("能力評価"))
        pace = self._number(horse.get("補正後評価", {}).get("展開評価"))
        distance = self._number(horse.get("補正後評価", {}).get("距離適性"))
        popular = self._number(horse.get("人気"), 99)

        p1 = self._truthy(horse, "能力保険", "G1連対歴", "G1連対実績") or (
            ability >= 85 and popular >= 8
        )
        p2 = self._truthy(horse, "適性保険", "ローカル巧者", "洋芝適性") or (
            course_score >= 80 and popular >= 8
        ) or (distance >= 80 and pace >= 80)

        if score >= 85 and horse.get("リスク域") != "危険域":
            return "S群"
        if score >= 75 or course_score >= 90:
            return "A群"
        if p1:
            return "P1群"
        if p2:
            return "P2群"
        return "B群"

    def score_horse(self, horse: dict[str, Any], race_info: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(horse)
        fields = self.configured_score_fields()
        scores = {field: self._clamp(self._number(result.get(field), 70)) for field in fields}
        scores, adjustment_reasons = self._apply_rule_adjustments(result, race_info, scores)
        weights = self.get_weights(race_info)
        risk, risk_zone = self.calculate_risk(result)
        final = sum(scores[field] * weights.get(field, 0) for field in fields) - risk

        result["補正後評価"] = {key: round(value, 1) for key, value in scores.items()}
        result["適用補正"] = adjustment_reasons
        result["使用重み"] = weights
        result["リスク補正"] = risk
        result["リスク域"] = risk_zone
        result["総合評価"] = round(self._clamp(final), 1)
        result["分類"] = self.classify_horse(result)
        return result

    def build_trio_formation(self, scored: list[dict[str, Any]]) -> dict[str, Any]:
        if not scored:
            return {}
        axis = scored[0]["馬番"]
        second_horses = [horse for horse in scored[1:] if horse["分類"] in ("S群", "A群")][:3]
        if not second_horses:
            second_horses = scored[1:4]
        third_horses = [
            horse for horse in scored[1:]
            if horse["分類"] in ("S群", "A群", "P1群", "P2群")
        ][:7]
        if not third_horses:
            third_horses = scored[1:8]
        second = [horse["馬番"] for horse in second_horses]
        third = [horse["馬番"] for horse in third_horses]
        combinations = {
            tuple(sorted((axis, number2, number3), key=str))
            for number2, number3 in itertools.product(second, third)
            if len({axis, number2, number3}) == 3
        }
        return {
            "券種": "三連複フォーメーション",
            "1列目": [axis],
            "2列目": second,
            "3列目": third,
            "推定点数": len(combinations),
            "組合せ": [list(combo) for combo in sorted(combinations, key=lambda values: [str(v) for v in values])],
            "方針": "軸1頭固定、S/A群を本線、P1/P2群は相手保険",
        }

    def build_wide_candidates(self, scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(scored) < 2:
            return []
        axis = scored[0]
        candidates = sorted(
            scored[1:],
            key=lambda horse: (
                self._number(horse["補正後評価"].get("再現性評価")) * 0.6
                + self._number(horse["補正後評価"].get("期待値評価")) * 0.4
            ),
            reverse=True,
        )[:3]
        return [
            {"組合せ": [axis["馬番"], horse["馬番"]], "相手馬": horse["馬名"], "分類": horse["分類"]}
            for horse in candidates
        ]

    def purchase_decision(self, scored: list[dict[str, Any]]) -> dict[str, Any]:
        if not scored:
            return {"購入": "NO BET", "ランク": "C", "理由": "評価対象馬なし"}
        axis = scored[0]
        score = self._number(axis["総合評価"])
        risk = axis.get("リスク域")
        if risk == "危険域" or score < 60:
            return {"購入": "NO BET", "ランク": "C", "理由": "軸馬が強制停止条件に該当"}
        rank = "S+" if score >= 85 else "S" if score >= 75 else "A" if score >= 68 else "B"
        return {
            "購入": "GO" if rank in ("S+", "S", "A") else "NO BET",
            "ランク": rank,
            "最終評価": score,
            "理由": f"本命軸 {axis['馬名']} の総合評価とリスク判定に基づく",
        }

    def learning_warnings(self) -> list[str]:
        bias = self.get_learning_bias()
        sorted_bias = sorted(bias.items(), key=lambda item: item[1], reverse=True)
        return [f"{name}（累積補正値 {value:g}）" for name, value in sorted_bias if value >= 3]

    def evaluate_race(self, race_info: dict[str, Any], horses: list[dict[str, Any]]) -> dict[str, Any]:
        scored = [self.score_horse(horse, race_info) for horse in horses]
        scored.sort(key=lambda horse: horse["総合評価"], reverse=True)
        groups = {
            group: [horse for horse in scored if horse["分類"] == group]
            for group in ("S群", "A群", "P1群", "P2群", "B群")
        }
        return {
            "エンジン情報": {
                "システム名": self.template.get("system_name", "競馬予想マスター"),
                "テンプレートバージョン": self.template_version(),
                "実行日時": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "互換性診断": self.diagnostics,
            "レース情報": race_info,
            "夏競馬モード": self.is_summer_mode(race_info),
            "評価優先順位": self.get_priority(race_info),
            "使用重み": self.get_weights(race_info),
            "学習ログ由来の重点注意": self.learning_warnings(),
            "本命軸": scored[0] if scored else None,
            **groups,
            "全馬評価": scored,
            "購入判断": self.purchase_decision(scored),
            "推奨三連複フォーメーション": self.build_trio_formation(scored),
            "推奨ワイド候補": self.build_wide_candidates(scored),
        }

    def run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        race_info, horses = self.validate_input(payload)
        return self.evaluate_race(copy.deepcopy(race_info), copy.deepcopy(horses))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="予想テンプレート_v1.8.jsonを使用してレースを評価します")
    base = Path(__file__).resolve().parent
    parser.add_argument("input", nargs="?", help="レース情報と出走馬を含む入力JSON")
    parser.add_argument("-o", "--output", help="結果JSONの保存先。省略時は標準出力")
    parser.add_argument("--template", default=str(base / "予想テンプレート_v1.8.json"), help="予想テンプレートJSON")
    parser.add_argument("--learning-log", default=str(base / "学習ログ.json"), help="学習ログJSON")
    parser.add_argument("--health-check", action="store_true", help="テンプレートとログの互換性診断だけを実行")
    parser.add_argument("--refresh-learning-summary", action="store_true", help="学習ログの累積補正値を再集計して保存")
    parser.add_argument("--backup-dir", help="実行前にテンプレートと学習ログをバックアップするフォルダ")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        engine = KeibaEngine(args.template, args.learning_log)
        if args.backup_dir:
            for path in engine.create_backup(args.backup_dir):
                print(f"バックアップを保存しました: {path}")
        if args.refresh_learning_summary:
            engine.refresh_learning_summary()
            engine.save_json(engine.learning_log_path, engine.learning_log)
            print(f"学習ログの累積補正値を再集計しました: {engine.learning_log_path}")
        if args.health_check:
            print(json.dumps({
                "テンプレートバージョン": engine.template_version(),
                "評価項目": engine.configured_score_fields(),
                "ログ件数": len(engine.learning_log.get("学習ログ", [])),
                "累積補正値": engine.get_learning_bias(),
                "診断": engine.diagnostics,
            }, ensure_ascii=False, indent=2))
            return 0
        if not args.input:
            if args.refresh_learning_summary:
                return 0
            raise KeibaEngineError("予想実行には入力JSONを指定してください")
        payload = engine.load_json(args.input)
        result = engine.run_payload(payload)
        if args.output:
            engine.save_json(args.output, result)
            print(f"予想結果を保存しました: {Path(args.output).resolve()}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeibaEngineError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
