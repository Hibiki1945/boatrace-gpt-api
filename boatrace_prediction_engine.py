"""Claude版の展示・場・風補正ロジックをGPT Actions API用に切り出した評価器。"""
from __future__ import annotations

import re
from statistics import mean
from typing import Any

VENUES: dict[str, list[float]] = {
    "桐生": [50.2, 11.8, 13.6, 13.7, 8.6, 2.4], "戸田": [44.5, 16.2, 16.1, 14.1, 6.7, 2.7],
    "江戸川": [47.0, 18.4, 14.5, 11.8, 6.6, 2.6], "平和島": [46.8, 15.6, 14.7, 13.1, 7.4, 3.1],
    "多摩川": [53.0, 14.0, 13.3, 10.7, 7.1, 2.3], "浜名湖": [52.6, 13.3, 15.5, 10.6, 7.0, 1.6],
    "蒲郡": [57.6, 12.3, 12.2, 11.3, 5.4, 1.6], "常滑": [58.9, 11.5, 10.7, 11.3, 6.6, 1.8],
    "津": [58.0, 12.2, 12.0, 9.7, 6.5, 2.0], "三国": [53.0, 14.9, 14.4, 10.5, 5.9, 1.7],
    "びわこ": [52.3, 13.4, 14.6, 10.9, 7.4, 2.0], "住之江": [57.9, 14.0, 11.6, 9.7, 5.6, 1.7],
    "尼崎": [57.7, 12.1, 13.3, 9.6, 5.9, 1.7], "鳴門": [46.6, 15.0, 15.8, 12.7, 8.3, 2.2],
    "丸亀": [57.2, 12.9, 12.2, 9.8, 6.1, 2.3], "児島": [57.7, 12.8, 12.4, 9.5, 5.2, 2.6],
    "宮島": [56.1, 13.3, 12.5, 10.1, 6.9, 1.7], "徳山": [63.2, 12.4, 10.5, 8.6, 4.3, 1.2],
    "下関": [62.4, 12.1, 11.0, 8.7, 4.3, 2.0], "若松": [57.1, 12.2, 11.7, 10.0, 6.7, 2.8],
    "芦屋": [57.8, 11.1, 10.5, 11.9, 6.9, 2.2], "福岡": [56.9, 14.4, 14.8, 9.1, 4.2, 1.1],
    "唐津": [56.2, 14.9, 12.6, 10.0, 5.1, 1.7], "大村": [63.0, 11.9, 11.7, 7.3, 5.2, 1.3],
}

WIND = {
    "無風": [58.1, 14.0, 11.3, 10.0, 5.1, 1.5], "向かい風1m": [57.2, 13.4, 12.2, 9.8, 5.6, 1.9],
    "向かい風2m": [54.6, 13.8, 12.3, 10.9, 6.5, 2.0], "向かい風3m": [53.1, 13.7, 13.2, 11.4, 6.5, 2.2],
    "向かい風4m": [52.6, 13.8, 12.9, 11.8, 6.5, 2.4], "向かい風5m以上": [48.4, 14.0, 14.4, 13.1, 7.5, 2.7],
    "追い風1m": [58.3, 14.7, 10.8, 9.6, 5.0, 1.7], "追い風2m": [56.4, 15.8, 11.5, 9.9, 4.7, 1.7],
    "追い風3m": [53.3, 16.1, 12.4, 11.0, 5.3, 1.8], "追い風4m": [51.3, 15.8, 13.8, 11.5, 5.7, 1.9],
    "追い風5m以上": [47.0, 17.8, 14.2, 12.6, 6.5, 2.1], "左横風1m": [59.3, 13.3, 11.2, 9.8, 5.1, 1.4],
    "左横風2m": [58.0, 13.6, 11.2, 10.6, 5.1, 1.5], "左横風3m以上": [55.8, 13.8, 12.2, 11.2, 5.5, 1.6],
    "右横風1m": [57.5, 13.6, 11.2, 10.3, 5.6, 1.7], "右横風2m": [54.3, 13.9, 12.7, 10.4, 6.7, 2.0],
    "右横風3m以上": [52.0, 15.1, 12.7, 11.6, 5.6, 2.4],
}

# [差の下限, 差の上限, 1着補正, 2着補正, 3着補正, 3連対補正]
TABLES = {
    1: [(-999, -.4, -24, 4, -5, -25), (-.4, -.2, -20, 0, 1, -19), (-.2, 0, -12, 4, 1, -7), (0, .2, -10, 4, 1, -5), (.2, .4, -4, 1, 0, -3), (.4, .6, 2, 0, 0, 2), (.6, .8, 6, -3, 1, 5), (.8, 999, 10, -2, -2, 6)],
    2: [(-999, -.4, -1, -9, -3, -14), (-.4, -.2, -6, -2, 5, -3), (-.2, 0, -2, -2, -1, -5), (0, .2, -4, 0, 1, -3), (.2, .4, 1, 0, 1, 3), (.4, .6, 6, 4, -1, 9), (.6, .8, 10, 5, -3, 12), (.8, 999, 8, 11, 1, 20)],
    3: [(-999, -.8, -8, -2, -4, -14), (-.8, -.6, -1, -9, -9, -19), (-.6, -.4, -2, -3, 0, -5), (-.4, -.2, -3, -1, -1, -4), (-.2, 0, -2, 1, -1, -2), (0, .2, 0, 0, 3, 3), (.2, .4, 5, 0, 4, 9), (.4, .6, 3, 6, -1, 9), (.6, .8, 13, 6, -4, 15), (.8, 999, 7, 14, 1, 22)],
    4: [(-999, -.8, -6, -7, -7, -20), (-.8, -.6, -4, -8, 3, -9), (-.6, -.4, -2, -3, -3, -9), (-.4, -.2, -1, -3, 0, -4), (-.2, 0, -1, 1, 0, 0), (0, .2, 1, 3, 2, 5), (.2, .4, 4, 5, 1, 10), (.4, .6, 6, 8, 1, 15), (.6, .8, 6, 8, 3, 18), (.8, 999, 5, 0, 13, 18)],
    5: [(-999, -.8, -1, -2, -9, -12), (-.8, -.6, -3, -1, -3, -7), (-.6, -.4, -2, -2, 0, -4), (-.4, -.2, 1, 0, -2, -1), (-.2, 0, 1, 1, -1, -3), (0, .2, 1, 2, 1, 4), (.2, .4, 1, 0, 10, 11), (.4, .6, 1, 4, 5, 11), (.6, .8, 9, 5, 1, 15), (.8, 999, 13, 10, 3, 26)],
    6: [(-999, -.8, -1, -3, -7, -11), (-.8, -.6, -1, 1, -2, -3), (-.6, -.4, 0, -2, 0, -1), (-.4, -.2, 0, -1, -1, -3), (-.2, 0, 0, 1, -2, -1), (0, .2, 0, 1, 4, 5), (.2, .4, 0, 0, 3, 5), (.4, .6, 0, 14, 6, 20), (.6, .8, 0, 14, 6, 20), (.8, 999, 11, 4, 9, 25)],
}

def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} は数値で指定してください")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} は数値で指定してください") from exc

def _adjustment(boat: int, diff: float) -> tuple[float, float, float, float]:
    for lo, hi, *values in TABLES[boat]:
        if lo <= diff < hi:
            return tuple(float(v) for v in values)  # type: ignore[return-value]
    return 0., 0., 0., 0.


RACER_CATEGORIES = ("今期", "直近6ヶ月", "直近3ヶ月", "直近1ヶ月", "当地", "一般戦", "SG/G1", "女子戦")
ST_PERIODS = ("今期", "直近3ヶ月", "直近1ヶ月", "初日", "最終日", "ナイター")


def make_row_reader(text: str):
    """コピーした表のラベル直後から6艇分を読む。UIには依存しない。"""
    cursor = 0

    def read_row(label: str, allow_dash: bool = False) -> list[float | None] | None:
        nonlocal cursor
        index = text.find(label, cursor)
        if index < 0:
            return None
        start = index + len(label)
        pattern = r"-?(?:\d+\.\d+|\.\d+)|[-−ー]|\d+" if allow_dash else r"-?(?:\d+\.\d+|\.\d+|\d+)"
        values: list[float | None] = []
        for match in re.finditer(pattern, text[start:]):
            token = match.group()
            values.append(None if allow_dash and token in {"-", "−", "ー"} else float(token))
            if len(values) == 6:
                cursor = start + match.end()
                return values
        return None

    return read_row


def parse_tenji(text: str) -> dict[str, Any]:
    read = make_row_reader(text)
    course = read("進入", True)
    tenji, isshu, mawari = read("展示", True), read("周回", True), read("周り足", True)
    read("直線", True)
    read("ST", True)
    weight = read("体重", True)
    read("調整重量", True)
    tilt = read("チルト", True)
    if not tenji or not isshu or not mawari or any(v is None for v in tenji + isshu + mawari):
        # BOATCAST形式: 周回タイムをアンカーに、前後の数値を拾う。
        tokens = [float(value) for value in re.findall(r"-?(?:\d+\.\d+|\.\d+|\d+)", text)]
        anchors = [index for index, value in enumerate(tokens) if 30 <= value <= 45][:6]
        if len(anchors) != 6:
            raise ValueError("展示・周回・周り足の6艇分を読み取れませんでした")
        boats: list[dict[str, Any]] = []
        allowed_tilts = {-0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0}
        for index, anchor in enumerate(anchors):
            lap = tokens[anchor]
            around = tokens[anchor + 1] if anchor + 1 < len(tokens) and 4.5 <= tokens[anchor + 1] <= 8.5 else None
            exhibition = tokens[anchor + 3] if anchor + 3 < len(tokens) and 5.5 <= tokens[anchor + 3] <= 7.8 else None
            tilt_value = next((tokens[pos] for pos in range(anchor - 1, max(-1, anchor - 5), -1) if tokens[pos] in allowed_tilts), None)
            if exhibition is None or around is None:
                raise ValueError("BOATCAST形式から展示・周回・周り足を読み取れませんでした")
            boats.append({"boat": index + 1, "course": index + 1, "tenji": exhibition, "isshu": lap, "mawari": around, "weight": None, "tilt": tilt_value})
        return {"boats": boats, "解析形式": "BOATCAST"}
    return {"boats": [{
        "boat": i + 1,
        "course": int(course[i]) if course and course[i] in range(1, 7) else i + 1,
        "tenji": tenji[i], "isshu": isshu[i], "mawari": mawari[i],
        "weight": weight[i] if weight else None, "tilt": tilt[i] if tilt else None,
    } for i in range(6)], "解析形式": "表形式"}


def parse_st(text: str) -> dict[str, list[float | None] | None]:
    result: dict[str, list[float | None] | None] = {}
    for label in (*ST_PERIODS, "F持"):
        match = re.search(re.escape(label) + r"(?P<body>[\s\S]*?)(?=(?:今期|直近[136]ヶ月|初日|最終日|ナイター|F持)|$)", text)
        tokens = re.findall(r"\d+\.\d+|\.\d+|[-−ー]", match.group("body") if match else "")
        result[label] = [None if x in {"-", "−", "ー"} else float(x) for x in tokens[:6]] if len(tokens) >= 6 else None
    return result


def parse_motor(text: str) -> dict[int, dict[str, float | None]]:
    read = make_row_reader(text)
    number = read("番号")
    read("ランク"); read("貢献P")
    rate, win1, ren2, ren3 = read("勝率"), read("1着率"), read("2連対率"), read("3連対率")
    if not any((rate, win1, ren2, ren3)):
        raise ValueError("モーター表を読み取れませんでした")
    rows: dict[int, dict[str, float | None]] = {}
    for i in range(6):
        rows[i + 1] = {"number": number[i] if number else None, "rate": rate[i] if rate else None,
                       "win1": win1[i] if win1 else None, "ren2": ren2[i] if ren2 else None,
                       "ren3": ren3[i] if ren3 else None}
    return rows


def _six_rates(body: str) -> list[float | None] | None:
    # コピー元の出走数（例: (27)）を誤って率として読まないため、%付き数値だけを優先する。
    values = re.findall(r"(?:\d+(?:\.\d+)?\s*%|[-−ー])", body)
    if len(values) < 6:
        return None
    return [None if x in {"-", "−", "ー"} else float(x.rstrip("% ")) for x in values[:6]]


def parse_racer(text: str) -> dict[str, dict[str, list[float | None] | None]]:
    """枠別成績の1着率・2連対率・3連対率を区分別に返す。"""
    text = re.sub(r"直近\s*([136])ヶ月", r"直近\1ヶ月", text)
    sections: dict[str, str] = {}
    for metric, next_metric in (("win1", "2連対率"), ("ren2", "3連対率"), ("ren3", None)):
        label = {"win1": "1着率", "ren2": "2連対率", "ren3": "3連対率"}[metric]
        start = text.find(label)
        end = text.find(next_metric, start + len(label)) if next_metric else len(text)
        sections[metric] = text[start + len(label):end] if start >= 0 else ""
    result: dict[str, dict[str, list[float | None] | None]] = {key: {} for key in sections}
    for metric, section in sections.items():
        for category in RACER_CATEGORIES:
            label = "SG" if category == "SG/G1" else re.escape(category)
            match = re.search(label + r"(?P<body>[\s\S]*?)(?=(?:今期|直近[136]ヶ月|当地|一般戦|SG|女子戦)|$)", section)
            result[metric][category] = _six_rates(match.group("body")) if match else None
    if not any(value for metrics in result.values() for value in metrics.values()):
        raise ValueError("枠別成績を読み取れませんでした")
    return result


def parse_kimari(text: str) -> dict[str, Any]:
    """決まり手（6ヶ月・1年）と逃げシミュレーションを構造化する。"""
    output: dict[str, Any] = {}
    def numbers_after(body: str, label: str, count: int, start: int = 0) -> tuple[list[float] | None, int]:
        index = body.find(label, start)
        if index < 0:
            return None, start
        values = re.findall(r"\d+\.\d+", body[index + len(label):])
        return ([float(value) for value in values[:count]] if len(values) >= count else None), index + len(label)

    for period in ("直近6ヶ月", "直近1年"):
        start = text.find(period)
        if start < 0:
            continue
        next_starts = [text.find(label, start + len(period)) for label in ("直近6ヶ月", "直近1年", "逃げシミュレーション")]
        end = min((pos for pos in next_starts if pos >= 0), default=len(text))
        segment = text[start + len(period):end]
        nige, cursor = numbers_after(segment, "逃げ", 2)
        sashi, cursor = numbers_after(segment, "差され", 6, cursor)
        makuri, cursor = numbers_after(segment, "捲られ", 6, cursor)
        makurizashi, _ = numbers_after(segment, "捲られ差", 6, cursor)
        if nige:
            output[period] = {
                "nige": nige[0], "nigashi": nige[1],
                "sasare": sashi[0] if sashi else None, "sashi": sashi[1:] if sashi else None,
                "makurare": makuri[0] if makuri else None, "makuri": makuri[1:] if makuri else None,
                "makuraresashi": makurizashi[0] if makurizashi else None, "makurizashi": makurizashi[1:] if makurizashi else None,
            }
    sim = re.search(r"逃げシミュレーション(?P<body>[\s\S]*?)(?=決まり手|$)", text)
    if sim:
        body = sim.group("body")
        def rates(label: str, count: int) -> list[float] | None:
            match = re.search(re.escape(label) + r"(?P<body>[\s\S]*?)(?=逃がし|出目|決まり手|$)", body)
            values = re.findall(r"\d+\.\d+", match.group("body") if match else "")
            return [float(v) for v in values[:count]] if len(values) >= count else None
        head = rates("逃がし2着率", 7)
        third = rates("逃がし3着率", 5)
        deme = rates("出目確率", 5)
        if head:
            output["nige_sim"] = {"win1": head[0], "nige_rate": head[1], "second": head[2:], "third": third, "deme": deme}
    return output


def build_payload(venue: str, wind: str, pasted: dict[str, str], racer_category: str = "今期", comparison_category: str = "直近6ヶ月", f_hold_boats: list[int] | None = None, kimari_period: str = "直近6ヶ月") -> dict[str, Any]:
    """手動貼り付け群を evaluate() 用の6艇データへ変換する。"""
    parsed = parse_tenji(pasted["tenji"])
    boats = parsed["boats"]
    parser_warnings: list[str] = []
    try:
        motors = parse_motor(pasted["motor"]) if pasted.get("motor") else {}
    except ValueError as exc:
        motors = {}
        parser_warnings.append(f"モーター解析を省略: {exc}")
    try:
        racers = parse_racer(pasted["racer"]) if pasted.get("racer") else {}
    except ValueError as exc:
        racers = {}
        parser_warnings.append(f"枠別成績解析を省略: {exc}")
    try:
        st = parse_st(pasted["st"]) if pasted.get("st") else {}
    except ValueError as exc:
        st = {}
        parser_warnings.append(f"平均ST解析を省略: {exc}")
    for row in boats:
        boat = row["boat"]
        if motor := motors.get(boat):
            row["motor_ren2"], row["motor_ren3"] = motor["ren2"], motor["ren3"]
        if racers:
            # パーサーが区分を見つけられない場合はNoneを返すため、6艇分の未評価配列へ安全にフォールバックする。
            win1 = racers["win1"].get(racer_category) or [None] * 6
            ren2 = racers["ren2"].get(racer_category) or [None] * 6
            ren3 = racers["ren3"].get(racer_category) or [None] * 6
            six_win1 = racers["win1"].get(comparison_category) or [None] * 6
            six_ren2 = racers["ren2"].get(comparison_category) or [None] * 6
            six_ren3 = racers["ren3"].get(comparison_category) or [None] * 6
            row["racer_win1"], row["racer_ren2"], row["racer_ren3"] = win1[boat - 1], ren2[boat - 1], ren3[boat - 1]
            row["racer_6m_win1"], row["racer_6m_ren2"], row["racer_6m_ren3"] = six_win1[boat - 1], six_ren2[boat - 1], six_ren3[boat - 1]
        row["f_hold"] = boat in (f_hold_boats or [])
        if st.get("今期"):
            f_st = st.get("F持")
            row["avg_st"] = f_st[boat - 1] if row["f_hold"] and f_st and f_st[boat - 1] is not None else st["今期"][boat - 1]
    return {"venue": venue, "wind": wind, "boats": boats, "kimari": parse_kimari(pasted["kimari"]) if pasted.get("kimari") else {}, "kimari_period": kimari_period, "解析警告": parser_warnings}


def _boat_comment(row: dict[str, Any]) -> str:
    criteria = row["総合判定"]["内訳"]
    strengths = [name for name, value in criteria.items() if value]
    trend = row.get("今期_vs_直近6ヶ月", {}).get("判定")
    text = f"{row['艇']}号艇は{row['総合判定']['印']}評価。"
    if strengths:
        text += f"強みは{'・'.join(strengths)}。"
    else:
        text += "明確な加点材料は限定的。"
    if trend == "上向き":
        text += "成績トレンドは上向き。"
    elif trend == "下降傾向":
        text += "成績トレンドは下降傾向。"
    if row["根拠"]:
        text += " " + "。".join(row["根拠"]) + "。"
    if row["注意"]:
        text += " 注意: " + "・".join(row["注意"]) + "。"
    return text


def _race_comment(rows: list[dict[str, Any]], nige: dict[str, Any] | None) -> str:
    leaders = "・".join(f"{row['艇']}号艇({row['総合判定']['印']})" for row in rows[:3])
    text = f"総合評価の上位は{leaders}。"
    one = next((row for row in rows if row["艇"] == 1), None)
    if one and nige:
        text += f"1号艇の逃げ補正後は{nige['逃げ補正後']:.1f}%で、"
        if nige["逃げ補正後"] >= 60:
            text += "逃げ残りを軸に検討できる水準。"
        else:
            text += "展示補正で下がっており、逃げ一辺倒にはしにくい状況。"
    return text + " これは数値評価であり、最終判断では進入・オッズ・場優先度を確認してください。"

def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    """6艇分の手入力または抽出済み数値を評価し、説明可能な順位を返す。"""
    venue = str(payload.get("venue", "")).strip()
    wind = str(payload.get("wind", "無風")).strip()
    boats = payload.get("boats")
    if venue not in VENUES:
        raise ValueError("venue は24場の正式名称で指定してください")
    if wind not in WIND:
        raise ValueError("wind は対応する風区分で指定してください")
    if not isinstance(boats, list) or len(boats) != 6:
        raise ValueError("boats は1号艇から6号艇までの6件が必要です")

    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in boats:
        if not isinstance(raw, dict):
            raise ValueError("boats の各要素はオブジェクトで指定してください")
        boat = int(_number(raw.get("boat"), "boat"))
        course = int(_number(raw.get("course", boat), "course"))
        if boat not in range(1, 7) or course not in range(1, 7) or boat in seen:
            raise ValueError("boat と course は1〜6、boat は重複不可です")
        seen.add(boat)
        tenji, isshu, mawari = (_number(raw.get(k), k) for k in ("tenji", "isshu", "mawari"))
        if not 5.0 <= tenji <= 8.0 or not 15 <= isshu <= 45 or not 4 <= mawari <= 15:
            raise ValueError("tenji / isshu / mawari の値域を確認してください")
        normalized.append({"boat": boat, "course": course, "tenji": tenji, "isshu": isshu, "mawari": mawari, **raw})

    avg_t, avg_i, avg_m = (mean(row[k] for row in normalized) for k in ("tenji", "isshu", "mawari"))
    wind_base = WIND[wind]
    rows: list[dict[str, Any]] = []
    for row in normalized:
        boat, course = row["boat"], row["course"]
        # 小さい展示・周回・回り足ほど良い、という原画面と同じ方向で合計差を作る。
        sum_score = (avg_t - row["tenji"]) + (avg_i - row["isshu"]) + (avg_m - row["mawari"])
        w1, w2, w3, top3 = _adjustment(boat, sum_score)
        base = VENUES[venue][course - 1]
        wind_adj = wind_base[course - 1] - WIND["無風"][course - 1]
        racer_w1 = row.get("racer_win1")
        racer_r2 = row.get("racer_ren2")
        racer_r3 = row.get("racer_ren3")
        racer_1 = _number(racer_w1, "racer_win1") + w1 if racer_w1 is not None else None
        racer_2 = _number(racer_r2, "racer_ren2") + w1 + w2 if racer_r2 is not None else None
        racer_3 = _number(racer_r3, "racer_ren3") + top3 if racer_r3 is not None else None
        warnings: list[str] = []
        if row.get("f_hold"):
            warnings.append("F持ち注意")
        tilt = row.get("tilt")
        if tilt is not None and _number(tilt, "tilt") >= 1:
            warnings.append("チルト1.0以上")
        st = row.get("avg_st")
        if st is not None and _number(st, "avg_st") >= .20:
            warnings.append("平均STが遅め")
        final1 = base + wind_adj + w1
        rows.append({
            "艇": boat, "進入": course, "展示差合計": round(sum_score, 3), "場別基準1着率": base,
            "風補正": round(wind_adj, 1), "艇別補正": {"1着": w1, "2着": w2, "3着": w3, "3連対": top3},
            "計算1着指標": round(final1, 1), "選手補正後": {"1着率": None if racer_1 is None else round(racer_1, 1), "2連対率": None if racer_2 is None else round(racer_2, 1), "3連対率": None if racer_3 is None else round(racer_3, 1)},
            "注意": warnings, "根拠": [], "補足": [],
        })
    motor_values = [_number(row["motor_ren2"], "motor_ren2") for row in normalized if row.get("motor_ren2") is not None]
    racer_values = [row["選手補正後"]["1着率"] for row in rows if row["選手補正後"]["1着率"] is not None]
    st_values = [_number(row["avg_st"], "avg_st") for row in normalized if row.get("avg_st") is not None]
    motor_average = mean(motor_values) if len(motor_values) >= 2 else None
    racer_average = mean(racer_values) if len(racer_values) >= 2 else None
    st_average = mean(st_values) if len(st_values) >= 2 else None
    raw_by_boat = {row["boat"]: row for row in normalized}
    top_motor_boats = {row["boat"] for row in sorted((x for x in normalized if x.get("motor_ren2") is not None), key=lambda x: _number(x["motor_ren2"], "motor_ren2"), reverse=True)[:2]}
    for row in rows:
        raw = raw_by_boat[row["艇"]]
        motor = _number(raw["motor_ren2"], "motor_ren2") if raw.get("motor_ren2") is not None else None
        racer = row["選手補正後"]["1着率"]
        st_value = _number(raw["avg_st"], "avg_st") if raw.get("avg_st") is not None else None
        racer2 = row["選手補正後"]["2連対率"]
        racer3 = row["選手補正後"]["3連対率"]
        racer2_values = [x["選手補正後"]["2連対率"] for x in rows if x["選手補正後"]["2連対率"] is not None]
        racer3_values = [x["選手補正後"]["3連対率"] for x in rows if x["選手補正後"]["3連対率"] is not None]
        racer2_average = mean(racer2_values) if len(racer2_values) >= 2 else None
        racer3_average = mean(racer3_values) if len(racer3_values) >= 2 else None
        criteria = {
            "枠別成績": bool((racer is not None and racer_average is not None and racer >= racer_average + 1) or (racer2 is not None and racer2_average is not None and racer2 >= racer2_average + 2) or (racer3 is not None and racer3_average is not None and racer3 >= racer3_average + 3)),
            "展示タイム": row["展示差合計"] >= 0.1,
            "モーター": bool(row["艇"] in top_motor_boats or (raw.get("motor_ren3") is not None and _number(raw["motor_ren3"], "motor_ren3") >= 60)),
            "風": wind != "無風" and row["風補正"] >= 0.5,
        }
        good_count = sum(criteria.values())
        row["総合判定"] = {"印": "◎" if good_count >= 3 else "○" if good_count == 2 else "△" if good_count == 1 else "×", "良材料数": good_count, "内訳": criteria}
        if motor is not None:
            row["モーター"] = {"2連対率": motor, "3連対率": raw.get("motor_ren3")}
        if criteria["モーター"] and not criteria["展示タイム"]:
            row["注意"].append("タイム不発でもモーター良・警戒")
        if st_value is not None and st_average is not None and st_value - st_average >= 0.03:
            row["注意"].append("平均STが他艇より0.03以上遅い")
        elif st_value is not None and st_average is not None and st_average - st_value >= 0.03:
            row["根拠"].append("スリット先行候補")
        comparison = {
            "1着率": {"今期": raw.get("racer_win1"), "直近6ヶ月": raw.get("racer_6m_win1")},
            "2連対率": {"今期": raw.get("racer_ren2"), "直近6ヶ月": raw.get("racer_6m_ren2")},
            "3連対率": {"今期": raw.get("racer_ren3"), "直近6ヶ月": raw.get("racer_6m_ren3")},
        }
        deltas: list[float] = []
        for metric in comparison.values():
            if metric["今期"] is not None and metric["直近6ヶ月"] is not None:
                metric["差"] = round(_number(metric["今期"], "今期") - _number(metric["直近6ヶ月"], "直近6ヶ月"), 1)
                deltas.append(metric["差"])
            else:
                metric["差"] = None
        trend_score = (deltas[0] * .5 + deltas[1] * .3 + deltas[2] * .2) if len(deltas) == 3 else None
        trend = "上向き" if trend_score is not None and trend_score >= 3 else "下降傾向" if trend_score is not None and trend_score <= -3 else "横ばい"
        row["今期_vs_直近6ヶ月"] = {"各率": comparison, "トレンドスコア": None if trend_score is None else round(trend_score, 1), "判定": trend}
        if trend == "上向き":
            row["根拠"].append("今期成績が直近6ヶ月より上向き")
        elif trend == "下降傾向":
            row["注意"].append("今期成績が直近6ヶ月より下降傾向")
        r3 = row["選手補正後"]["3連対率"]
        r1_delta = (racer - racer_average) if racer is not None and racer_average is not None else None
        r2_delta = (racer2 - racer2_average) if racer2 is not None and racer2_average is not None else None
        r3_delta = (r3 - racer3_average) if r3 is not None and racer3_average is not None else None
        if r1_delta is not None and r3_delta is not None and r1_delta <= -2 and r3_delta >= 2:
            if criteria["展示タイム"]:
                row["根拠"].append(f"1着率は低いが3連対率{r3:.1f}%＋タイム良で2・3着残し有力")
            else:
                row["根拠"].append(f"1着率低めでも3連対率{r3:.1f}%で3着残しの目")
        if r2_delta is not None and r2_delta >= 3 and criteria["展示タイム"]:
            row["根拠"].append(f"2連対率{racer2:.1f}%上位で相手筆頭級")
        if r1_delta is not None and r3_delta is not None and r1_delta >= 3 and r3_delta <= -2:
            row["補足"].append(f"1着率上位だが3連対率{r3:.1f}%は平凡、買うなら頭")
        if r2_delta is not None and r1_delta is not None and r2_delta >= 3 and r1_delta < 2:
            row["根拠"].append("2連対率上位で2着軸候補")
        if r3_delta is not None and r3_delta <= -5:
            row["注意"].append("3連対率が低く紐でも過信禁物")
        # Claude版と同じく、総合AI評価は4項目を主軸にし、場別コース率は同印内の参考値に留める。
        racer_delta = (racer - racer_average) if racer is not None and racer_average is not None else 0.0
        motor_delta = (motor - motor_average) if motor is not None and motor_average is not None else 0.0
        row["総合スコア"] = round(good_count * 10 + racer_delta * 0.3 + row["展示差合計"] * 5 + motor_delta * 0.1 + row["風補正"] * 0.5 + row["計算1着指標"] * 0.05, 1)
    rows.sort(key=lambda r: r["総合スコア"], reverse=True)
    nige = payload.get("kimari", {}).get("nige_sim")
    nige_adjusted = None
    if isinstance(nige, dict) and rows:
        by_boat = {row["艇"]: row for row in rows}
        one = by_boat.get(1)
        if one:
            w1 = one["艇別補正"]["1着"]
            second = [{"艇": boat, "元値": value, "補正後": round(value + by_boat[boat]["艇別補正"]["2着"], 1)} for boat, value in enumerate(nige.get("second", []), start=2) if boat in by_boat]
            third = [{"艇": boat, "元値": value, "補正後": round(value + by_boat[boat]["艇別補正"]["3着"], 1)} for boat, value in enumerate(nige.get("third", []), start=2) if boat in by_boat]
            deme = [{"艇": boat, "元値": value} for boat, value in enumerate(nige.get("deme", []), start=2) if boat in by_boat]
            nige_adjusted = {"1着": nige.get("win1"), "逃げ": nige.get("nige_rate"), "逃げ補正後": round(nige.get("nige_rate", 0) + w1, 1), "2着": second, "3着": third, "出目": deme}
            for item in second:
                if item["元値"] >= 30:
                    by_boat[item["艇"]]["根拠"].append(f"逃がし2着{item['元値']:.1f}%（1-{item['艇']}本線級）")
    km = payload.get("kimari", {}).get(payload.get("kimari_period", "直近6ヶ月"))
    if isinstance(km, dict):
        by_boat = {row["艇"]: row for row in rows}
        one = by_boat.get(1)
        if one:
            nige_rate = km.get("nige")
            if nige_rate is not None and nige_rate >= 40:
                one["根拠"].append(f"決まり手の逃げ率{nige_rate}%")
            elif nige_rate is not None and nige_rate <= 25:
                one["注意"].append(f"決まり手の逃げ率{nige_rate}%と低調")
            for key, attack_name, defend_key, defend_name, threshold in (
                ("sashi", "差し", "sasare", "差され", (15, 15)),
                ("makuri", "捲り", "makurare", "捲られ", (20, 10)),
                ("makurizashi", "捲り差し", "makuraresashi", "捲られ差", (15, 8)),
            ):
                attacks, defense = km.get(key), km.get(defend_key)
                if not isinstance(attacks, list) or defense is None:
                    continue
                attacker_index, attacker_value = max(enumerate(attacks, start=2), key=lambda pair: -1 if pair[1] is None else pair[1])
                attacker = by_boat.get(attacker_index)
                attacker_good = bool(attacker and (attacker["総合判定"]["内訳"]["展示タイム"] or attacker["総合判定"]["内訳"]["枠別成績"]))
                if attacker_value is not None and defense >= threshold[0] and attacker_value >= threshold[1]:
                    one["注意"].append(f"{defend_name}{defense}%×{attacker_index}号艇の{attack_name}{attacker_value}%で要警戒")
                    by_boat[attacker_index]["根拠"].append(f"{attack_name}{attacker_value}%で1号艇を脅かす")
                elif attacker_value is not None and defense >= threshold[0] * 2 / 3 and attacker_value >= threshold[1] * 0.8:
                    one["注意"].append(f"{defend_name}{defense}%・{attacker_index}号艇の{attack_name}{attacker_value}%に注意")
                    by_boat[attacker_index]["根拠"].append(f"{attack_name}{attacker_value}%")
                elif attacker_value is not None and attacker_good and attacker_value >= threshold[1] * 0.6:
                    one["注意"].append(f"{attacker_index}号艇が気配上位で{attack_name}{attacker_value}%、数字以上に警戒")
                    by_boat[attacker_index]["根拠"].append(f"気配良く{attack_name}一撃も")
                else:
                    good_attackers = [row for row in rows if row["艇"] >= 2 and (row["総合判定"]["内訳"]["展示タイム"] or row["総合判定"]["内訳"]["枠別成績"])]
                    if good_attackers:
                        good = max(good_attackers, key=lambda row: row["総合判定"]["良材料数"])
                        value = attacks[good["艇"] - 2]
                        if value is not None and defense <= threshold[0] * 0.5 and value <= threshold[1] * 0.5:
                            one["補足"].append(f"{good['艇']}号艇は気配上位だが{attack_name}{value}%・{defend_name}{defense}%と低く、{attack_name}決着は薄めか")
    for row in rows:
        row["評価コメント"] = _boat_comment(row)
    return {
        "評価器": "claude-remix-v1", "前提": {"場": venue, "風": wind, "入力完全性": "手入力・公式抽出値を同一計算式で評価"},
        "順位": rows,
        "逃げシミュレーション": nige_adjusted,
        "レース評価コメント": _race_comment(rows, nige_adjusted),
        "注意": [*payload.get("解析警告", []), "これは数値評価であり購入推奨ではありません。場優先度・オッズ・進入・直前情報でGO/NO BETを最終判定してください。"],
    }
