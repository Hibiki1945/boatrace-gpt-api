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
import keiba_engine_complete as keiba_engine
import keiba_source_scraper as keiba_sources


DEFAULT_PROMPT_PATH = str(Path(__file__).resolve().with_name("boatrace_place_prompt.txt"))
DEFAULT_KEIBA_TEMPLATE_PATH = str(Path(__file__).resolve().with_name("予想テンプレート_v1.8.json"))
DEFAULT_KEIBA_LEARNING_LOG_PATH = str(Path(__file__).resolve().with_name("学習ログ.json"))


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


def keiba_source_data_from_params(params: dict[str, list[str]]) -> dict[str, Any]:
    jra_url = first_param(params, "jra_url")
    netkeiba_url = first_param(params, "netkeiba_url")
    include_result = first_param(params, "include_result", "false")
    if not jra_url:
        raise ValueError("jra_url は必須です。JRA公式の出馬表・オッズ・結果ページURLを指定してください")
    return keiba_sources.get_keiba_source_data(
        jra_url=jra_url,
        netkeiba_url=netkeiba_url,
        include_result=str(include_result).lower() in {"1", "true", "yes", "on"},
    )


def keiba_evaluate_payload(payload: dict[str, Any], template_path: str, learning_log_path: str) -> dict[str, Any]:
    race_payload = payload.get("race_payload", payload)
    if not isinstance(race_payload, dict):
        raise ValueError("race_payload は「レース情報」と「出走馬」を含むJSONオブジェクトにしてください")
    engine = keiba_engine.KeibaEngine(template_path, learning_log_path)
    result = engine.run_payload(race_payload)
    result["APIメタ"] = {
        "用途": "競馬予想テンプレート_v1.8による採点",
        "注意": "このエンドポイントは入力済みのレース情報・出走馬データを評価します。公式Web情報の取得は /keiba/race-data を先に使用してください。",
    }
    return result


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
                    "このAPIは、ユーザーが指定した競艇・競馬レース情報を取得・評価するために公式ページ等へアクセスします。"
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

            if parsed.path == "/keiba/race-data":
                self.send_json(keiba_source_data_from_params(params))
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
        parsed = urlparse(self.path)
        try:
            if not self.authorized():
                self.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path != "/keiba/evaluate":
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 2_000_000:
                raise ValueError("JSON本文を2MB以下で指定してください")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            self.send_json(
                keiba_evaluate_payload(
                    payload,
                    self.server.keiba_template_path,  # type: ignore[attr-defined]
                    self.server.keiba_learning_log_path,  # type: ignore[attr-defined]
                )
            )
        except json.JSONDecodeError:
            self.send_json({"error": "リクエスト本文はUTF-8のJSONで指定してください"}, HTTPStatus.BAD_REQUEST)
        except (ValueError, keiba_engine.KeibaEngineError, keiba_sources.KeibaSourceError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": "internal error", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
    parser.add_argument("--keiba-template", default=os.environ.get("KEIBA_TEMPLATE_PATH", DEFAULT_KEIBA_TEMPLATE_PATH))
    parser.add_argument("--keiba-learning-log", default=os.environ.get("KEIBA_LEARNING_LOG_PATH", DEFAULT_KEIBA_LEARNING_LOG_PATH))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BoatraceActionHandler)
    server.default_prompt = args.prompt  # type: ignore[attr-defined]
    server.keiba_template_path = args.keiba_template  # type: ignore[attr-defined]
    server.keiba_learning_log_path = args.keiba_learning_log  # type: ignore[attr-defined]
    print(f"Serving on http://{args.host}:{args.port}")
    print("Set BOATRACE_ACTION_API_KEY to require X-API-Key authentication.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
