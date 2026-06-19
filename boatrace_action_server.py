#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GPT Actions用のBOAT RACE公式スクレイピングAPI。

ローカル起動:
  python boatrace_action_server.py --host 127.0.0.1 --port 8787 --prompt "C:\\Users\\...\\全24場ごとの攻略情報を踏まえたプロンプト.txt"

動作確認:
  http://127.0.0.1:8787/health
  http://127.0.0.1:8787/boatrace/race-data?date=20260619&place=戸田&race=12

ChatGPTのGPT Actionsから使うには、このサーバーをHTTPSで公開し、
boatrace_gpt_action_openapi.json の servers.url を公開URLに差し替える。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import boatrace_official_scraper as scraper


DEFAULT_PROMPT_PATH = str(Path(__file__).resolve().with_name("boatrace_place_prompt.txt"))


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def first_param(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = params.get(name)
    if not values:
        return default
    return values[0]


def race_data_from_params(params: dict[str, list[str]], default_prompt: str | None) -> dict[str, Any]:
    date = first_param(params, "date")
    place = first_param(params, "place")
    race = first_param(params, "race")
    include_result = first_param(params, "include_result", "false")
    prompt = first_param(params, "prompt", default_prompt)

    if not date or not place or not race:
        raise ValueError("date, place, race は必須です")

    args = SimpleNamespace(
        date=date,
        place=place,
        race=int(race),
        prompt=prompt if prompt and Path(prompt).exists() else None,
        include_result=str(include_result).lower() in {"1", "true", "yes", "on"},
        out=None,
    )
    data = scraper.予想用JSON作成(args)
    data["APIメタ"] = {
        "用途": "GPT Actions完全実行用",
        "結果取得": args.include_result,
        "攻略プロンプト使用": bool(args.prompt),
    }
    return data


class BoatraceActionHandler(BaseHTTPRequestHandler):
    server_version = "PredictionActionServer/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        try:
            if parsed.path == "/health":
                self.send_json({"ok": True, "service": "boatrace-action-server"})
                return

            if parsed.path == "/privacy":
                self.send_text(
                    "このAPIは、ユーザーが指定した競艇レース情報を取得・評価するために公式ページ等へアクセスします。"
                    "入力されたレース情報は処理目的のみに使用し、このサーバーは個人情報を保存しません。"
                )
                return

            if not self.authorized():
                self.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return

            if parsed.path == "/boatrace/race-data":
                data = race_data_from_params(params, self.server.default_prompt)  # type: ignore[attr-defined]
                self.send_json(data)
                return

            if parsed.path == "/openapi.json":
                openapi_path = Path(__file__).resolve().with_name("boatrace_gpt_action_openapi.json")
                if openapi_path.exists():
                    self.send_json(json.loads(openapi_path.read_text(encoding="utf-8")))
                else:
                    self.send_json({"error": "openapi file not found"}, HTTPStatus.NOT_FOUND)
                return

            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": "internal error", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def authorized(self) -> bool:
        expected = os.environ.get("BOATRACE_ACTION_API_KEY")
        if not expected:
            return True
        actual = self.headers.get("X-API-Key", "")
        return actual == expected

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="GPT Actions用BOAT RACEスクレイピングAPI")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    parser.add_argument("--prompt", default=os.environ.get("BOATRACE_PROMPT_PATH", DEFAULT_PROMPT_PATH))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BoatraceActionHandler)
    server.default_prompt = args.prompt  # type: ignore[attr-defined]
    print(f"Serving on http://{args.host}:{args.port}")
    print("Set BOATRACE_ACTION_API_KEY to require X-API-Key authentication.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
