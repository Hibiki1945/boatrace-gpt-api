#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BOAT RACE公式情報スクレイピング補助ツール。

例:
  python boatrace_official_scraper.py --date 20260619 --place 戸田 --race 12 --prompt "C:\\Users\\...\\全24場ごとの攻略情報を踏まえたプロンプト.txt"

出力:
  outputs/boatrace_YYYYMMDD_場コード_Rレース番号.json

外部ライブラリ不要。BOAT RACE公式ページのHTMLから、本文テキストと表データを
できるだけ壊れにくい形で保存し、24場攻略プロンプトの該当場情報もマージする。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


場コード = {
    "桐生": "01",
    "戸田": "02",
    "江戸川": "03",
    "平和島": "04",
    "多摩川": "05",
    "浜名湖": "06",
    "蒲郡": "07",
    "常滑": "08",
    "津": "09",
    "三国": "10",
    "びわこ": "11",
    "住之江": "12",
    "尼崎": "13",
    "鳴門": "14",
    "丸亀": "15",
    "児島": "16",
    "宮島": "17",
    "徳山": "18",
    "下関": "19",
    "若松": "20",
    "芦屋": "21",
    "福岡": "22",
    "唐津": "23",
    "大村": "24",
}

コード場名 = {v: k for k, v in 場コード.items()}


DEFAULT_PRIORITY_PATH = Path(__file__).resolve().with_name("boatrace_venue_priority.json")

公式ページ種別 = {
    "出走表": "racelist",
    "直前情報": "beforeinfo",
    "3連単オッズ": "odds3t",
    "レース結果": "raceresult",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def 正規化日付(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        raise ValueError("--date は YYYYMMDD または YYYY-MM-DD 形式で指定してください")
    return digits


def 解決場コード(place: str) -> tuple[str, str]:
    text = place.strip().replace("競艇場", "").replace("ボートレース", "")
    if text in 場コード:
        return 場コード[text], text
    if re.fullmatch(r"\d{1,2}", text):
        code = text.zfill(2)
        if code in コード場名:
            return code, コード場名[code]
    raise ValueError(f"未対応の場指定です: {place}")


def 公式URL(page_kind: str, date: str, jcd: str, race_no: int | None = None) -> str:
    if page_kind == "レース場データ":
        return "https://www.boatrace.jp/owpc/pc/data/stadium?" + urlencode({"jcd": jcd})
    endpoint = 公式ページ種別[page_kind]
    params = {"hd": date, "jcd": jcd}
    if race_no is not None:
        params["rno"] = str(race_no)
    return f"https://www.boatrace.jp/owpc/pc/race/{endpoint}?" + urlencode(params)


def 取得(url: str, timeout: int = 20) -> tuple[str, dict[str, str]]:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CodexBoatraceScraper/1.0; +local)",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
        },
    )
    with urlopen(req, timeout=timeout) as res:
        body = res.read()
        headers = {k: v for k, v in res.headers.items()}
        content_type = res.headers.get("Content-Type", "")
    charset_match = re.search(r"charset=([\w\-.]+)", content_type, re.I)
    candidates = []
    if charset_match:
        candidates.append(charset_match.group(1))
    candidates.extend(["utf-8", "cp932", "shift_jis", "euc_jp"])
    for enc in candidates:
        try:
            return body.decode(enc), headers
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace"), headers


class 表抽出HTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_cell = False
        self._skip_depth = 0
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "table":
            self._table_stack += 1
            if self._table_stack == 1:
                self._current_table = []
        elif tag == "tr" and self._table_stack:
            self._current_row = []
        elif tag in {"td", "th"} and self._table_stack:
            self._in_cell = True
            self._current_cell = []
        elif tag in {"br", "p", "li", "div", "section", "article", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"td", "th"} and self._table_stack and self._current_cell is not None:
            cell = 正規化空白(" ".join(self._current_cell))
            if self._current_row is not None:
                self._current_row.append(cell)
            self._current_cell = None
            self._in_cell = False
        elif tag == "tr" and self._table_stack and self._current_row is not None:
            row = [c for c in self._current_row if c != ""]
            if row and self._current_table is not None:
                self._current_table.append(row)
            self._current_row = None
        elif tag == "table" and self._table_stack:
            if self._table_stack == 1 and self._current_table is not None:
                if self._current_table:
                    self.tables.append(self._current_table)
                self._current_table = None
            self._table_stack -= 1
        elif tag in {"p", "li", "div", "section", "article", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data)
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(text)
        self.text_parts.append(text)


def 正規化空白(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def 本文行へ(html_text: str) -> tuple[list[str], list[list[list[str]]]]:
    parser = 表抽出HTMLParser()
    parser.feed(html_text)
    raw = html.unescape("".join(parser.text_parts))
    lines = []
    for line in raw.splitlines():
        line = 正規化空白(line)
        if line:
            lines.append(line)
    return lines, parser.tables


def 周辺行(lines: list[str], keywords: list[str], radius: int = 2) -> list[str]:
    hit_indexes: set[int] = set()
    for i, line in enumerate(lines):
        if any(k in line for k in keywords):
            for n in range(max(0, i - radius), min(len(lines), i + radius + 1)):
                hit_indexes.add(n)
    return [lines[i] for i in sorted(hit_indexes)]


def 直前気象抽出(lines: list[str]) -> dict[str, str]:
    joined = " ".join(lines)
    keys = ["天候", "気温", "水温", "波高", "風向", "風速"]
    data: dict[str, str] = {}
    for key in keys:
        match = re.search(rf"{key}\s*[:：]?\s*([^\s]+(?:\s*[m℃度])?)", joined)
        if match:
            data[key] = match.group(1)
    return data


def 重要行抽出(page_kind: str, lines: list[str]) -> list[str]:
    keywords_by_kind = {
        "出走表": ["登録番号", "選手名", "級別", "全国", "当地", "モーター", "ボート", "F", "L", "平均ST"],
        "直前情報": ["展示", "チルト", "部品交換", "スタート展示", "気温", "水温", "風向", "風速", "波高"],
        "3連単オッズ": ["3連単", "オッズ", "人気"],
        "レース結果": ["着", "決まり手", "払戻", "進入", "ST", "3連単", "返還"],
        "レース場データ": ["水質", "干満差", "コース", "1着率", "決まり手", "逃げ", "差し", "まくり"],
    }
    return 周辺行(lines, keywords_by_kind.get(page_kind, []), radius=3)


def 攻略プロンプト解析(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    result: dict[str, Any] = {}
    pattern = re.compile(r"【(?P<場名>[^】]+?)競艇場用のプロンプト】(?P<body>.*?)(?=【[^】]+?競艇場用のプロンプト】|\Z)", re.S)
    for match in pattern.finditer(text):
        place = match.group("場名").strip()
        body = match.group("body")
        premises: list[str] = []
        priorities: list[str] = []
        mode = "前提"
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "評価優先順位" in line:
                mode = "優先順位"
                continue
            if line.startswith("・"):
                item = line.lstrip("・").strip()
                if mode == "前提":
                    premises.append(item)
                else:
                    priorities.append(item)
            elif re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", line):
                priorities.append(re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", line).strip())
        result[place] = {
            "場名": place,
            "攻略前提": premises,
            "評価優先順位": priorities,
            "原文": 正規化空白(body),
        }
    return result


def 場優先度読み込み(path: Path | None, place_name: str) -> dict[str, Any]:
    """構造化した場優先度を読み、未設定でも予想処理を止めない。"""
    if path is None or not path.exists():
        return {
            "場名": place_name,
            "取得状態": "未設定",
            "基本購入判断": "判定不可",
            "注意事項": ["場優先度設定が未読込のため、購入判断は保守的に行う"],
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "場名": place_name,
            "取得状態": "読込失敗",
            "基本購入判断": "判定不可",
            "注意事項": [f"場優先度設定の読込に失敗: {exc}"],
        }

    places = data.get("競艇場別優先度", {})
    priority = places.get(place_name)
    if not isinstance(priority, dict):
        return {
            "場名": place_name,
            "取得状態": "未設定",
            "基本購入判断": "判定不可",
            "注意事項": ["この場の場優先度が未設定のため、NO BET寄りに扱う"],
        }
    return {"取得状態": "設定済み", **priority}


@dataclass
class 取得ページ:
    種別: str
    url: str
    取得成功: bool
    取得時刻: str
    エラー: str | None
    本文重要行: list[str]
    本文全文行数: int
    表データ: list[list[list[str]]]
    直前気象: dict[str, str] | None = None


def ページ取得(page_kind: str, url: str) -> 取得ページ:
    now = utc_now_iso()
    try:
        source, _headers = 取得(url)
        lines, tables = 本文行へ(source)
        return 取得ページ(
            種別=page_kind,
            url=url,
            取得成功=True,
            取得時刻=now,
            エラー=None,
            本文重要行=重要行抽出(page_kind, lines),
            本文全文行数=len(lines),
            表データ=tables,
            直前気象=直前気象抽出(lines) if page_kind == "直前情報" else None,
        )
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return 取得ページ(
            種別=page_kind,
            url=url,
            取得成功=False,
            取得時刻=now,
            エラー=str(exc),
            本文重要行=[],
            本文全文行数=0,
            表データ=[],
            直前気象=None,
        )


def 予想用JSON作成(args: argparse.Namespace) -> dict[str, Any]:
    date = 正規化日付(args.date)
    jcd, place_name = 解決場コード(args.place)
    race_no = int(args.race)

    pages = ["出走表", "直前情報", "3連単オッズ", "レース場データ"]
    if args.include_result:
        pages.append("レース結果")

    official: dict[str, Any] = {}
    for page in pages:
        url = 公式URL(page, date, jcd, race_no if page != "レース場データ" else None)
        got = ページ取得(page, url)
        official[page] = got.__dict__

    prompt_data: dict[str, Any] = {}
    if args.prompt:
        prompt_path = Path(args.prompt)
        all_prompt = 攻略プロンプト解析(prompt_path)
        prompt_data = all_prompt.get(place_name, {})

    priority_arg = getattr(args, "priority", None)
    priority_path = Path(priority_arg) if priority_arg else DEFAULT_PRIORITY_PATH
    venue_priority = 場優先度読み込み(priority_path, place_name)

    return {
        "データ種別": "競艇予想用スクレイピング結果",
        "作成時刻": utc_now_iso(),
        "レース識別": {
            "開催日": date,
            "場コード": jcd,
            "ボートレース場": place_name,
            "レース番号": race_no,
            "レースID": f"{date}_{jcd}_{race_no:02d}",
        },
        "公式取得情報": official,
        "場別攻略情報": prompt_data,
        "場優先度": venue_priority,
        "テンプレート反映メモ": {
            "優先反映先": [
                "ウェブ参照ルール",
                "競艇場別補正",
                "1号艇信頼度評価",
                "展示評価",
                "進入予想",
                "展開予想",
                "着順予想",
                "舟券変換ルール"
            ],
            "注意": [
                "予想時はレース結果を取得しない。検証時のみ --include-result を付ける",
                "公式ページのHTML構造変更に備え、表データと重要行を両方保存する",
                "取得できない項目は手入力またはユーザー提供情報として補完する"
            ]
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOAT RACE公式情報と24場攻略プロンプトをJSON化します")
    parser.add_argument("--date", required=True, help="開催日。例: 20260619 または 2026-06-19")
    parser.add_argument("--place", required=True, help="場名または場コード。例: 戸田 / 02")
    parser.add_argument("--race", required=True, type=int, choices=range(1, 13), help="レース番号 1-12")
    parser.add_argument("--prompt", help="全24場ごとの攻略情報プロンプト.txt のパス")
    parser.add_argument(
        "--priority",
        default=str(DEFAULT_PRIORITY_PATH),
        help="boatrace_venue_priority.json のパス",
    )
    parser.add_argument("--include-result", action="store_true", help="検証用に結果ページも取得する")
    parser.add_argument("--out", help="出力JSONパス。未指定ならスクリプトと同じフォルダに保存")
    args = parser.parse_args(argv)

    try:
        data = 予想用JSON作成(args)
    except ValueError as exc:
        print(f"入力エラー: {exc}", file=sys.stderr)
        return 2

    if args.out:
        out_path = Path(args.out)
    else:
        rid = data["レース識別"]["レースID"]
        out_path = Path(__file__).resolve().parent / f"boatrace_{rid}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
