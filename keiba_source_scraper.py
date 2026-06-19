#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""競馬の参照URLから予想用の根拠データを取得する補助モジュール。

JRA公式を主情報とし、netkeibaはユーザーが指定した馬柱URLだけを補助確認する。
ログイン必須ページ・アクセス制限の回避・連続巡回は行わない。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import boatrace_official_scraper as html_tools


_CACHE_SECONDS = 600
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class KeibaSourceError(ValueError):
    """取得対象URLまたは外部サイトの応答が不正な場合の例外。"""


@dataclass
class SourcePage:
    種別: str
    URL: str
    ドメイン: str
    取得成功: bool
    キャッシュ利用: bool
    本文重要行: list[str]
    表データ: list[list[list[str]]]
    本文全文行数: int
    注意: list[str]
    エラー: str | None = None


def _validate_url(url: str, source_type: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise KeibaSourceError(f"{source_type}のURLはHTTPSで指定してください")
    host = (parsed.hostname or "").lower()
    if source_type == "JRA公式":
        allowed = host == "jra.go.jp" or host.endswith(".jra.go.jp")
    else:
        allowed = host == "netkeiba.com" or host.endswith(".netkeiba.com")
    if not allowed:
        raise KeibaSourceError(f"{source_type}に対応しないURLです: {host}")
    if "login" in parsed.path.lower() or "regist" in host:
        raise KeibaSourceError("ログイン・会員ページは取得対象外です")
    return url


def _keywords(source_type: str, include_result: bool) -> list[str]:
    if source_type == "JRA公式":
        keys = [
            "出馬表",
            "馬番",
            "馬名",
            "騎手",
            "オッズ",
            "馬場",
            "天候",
            "馬体重",
            "調教",
            "距離",
        ]
    else:
        keys = [
            "馬柱",
            "競走馬",
            "戦績",
            "着順",
            "距離",
            "競馬場",
            "騎手",
            "通過",
            "上がり",
        ]
    if include_result:
        keys.extend(["結果", "払戻", "着順", "ラップ", "通過順位"])
    return keys


def _fetch_one(source_type: str, url: str, include_result: bool) -> dict[str, Any]:
    cached = _cache.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        data = dict(cached[1])
        data["キャッシュ利用"] = True
        return data

    try:
        source, _headers = html_tools.取得(url, timeout=15)
        lines, tables = html_tools.本文行へ(source)
        page = SourcePage(
            種別=source_type,
            URL=url,
            ドメイン=urlparse(url).hostname or "",
            取得成功=True,
            キャッシュ利用=False,
            本文重要行=html_tools.周辺行(lines, _keywords(source_type, include_result), radius=2),
            表データ=tables,
            本文全文行数=len(lines),
            注意=[
                "JRA公式情報を主情報として扱う",
                "netkeibaは補助確認として扱う",
                "取得内容は予想時点の根拠として保存し、結果情報は検証時のみ使用する",
            ],
        )
    except Exception as exc:  # 外部サイトエラーを予想処理へ伝える
        page = SourcePage(
            種別=source_type,
            URL=url,
            ドメイン=urlparse(url).hostname or "",
            取得成功=False,
            キャッシュ利用=False,
            本文重要行=[],
            表データ=[],
            本文全文行数=0,
            注意=["外部情報を取得できなかったため、この情報源は未確認として扱う"],
            エラー=str(exc),
        )
    data = asdict(page)
    _cache[url] = (now, data)
    return data


def get_keiba_source_data(
    jra_url: str,
    netkeiba_url: str | None = None,
    include_result: bool = False,
) -> dict[str, Any]:
    """JRA公式URLと任意のnetkeiba馬柱URLから、根拠確認用のデータを返す。"""
    jra_url = _validate_url(jra_url, "JRA公式")
    result: dict[str, Any] = {
        "データ種別": "競馬予想用ソース取得結果",
        "取得方針": {
            "主情報": "JRA公式",
            "補助情報": "netkeibaのユーザー指定馬柱URL",
            "結果情報の扱い": "include_result=trueの検証時のみ使用",
            "netkeiba取得制限": "指定URLのみ、10分キャッシュ、ログイン回避・連続巡回・制限回避をしない",
        },
        "JRA公式": _fetch_one("JRA公式", jra_url, include_result),
        "netkeiba馬柱": None,
    }
    if netkeiba_url:
        result["netkeiba馬柱"] = _fetch_one(
            "netkeiba馬柱",
            _validate_url(netkeiba_url, "netkeiba馬柱"),
            include_result,
        )
    return result
