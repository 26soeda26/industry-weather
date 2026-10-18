"""
Industry Weather — 業界の「市場天気予報」を公開情報だけで作るツール

使い方:
    python weather.py "車載用抵抗器" --customers "自動車,産業機器"

業界名を渡すと、Claude が Web 検索で公開情報（政府統計・業界団体データ・
上場企業の決算資料・業界ニュース）を集め、
  短期（半年先）／中期（3〜4年先）／長期（2030〜2040年）
の3つに分けて「晴れ・曇り・雨」の天気図形式でまとめ、HTML で保存します。
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys

import anthropic

MODEL = os.environ.get("WEATHER_MODEL", "claude-sonnet-5-5")

WEATHER_ICON = {"晴れ": "☀️", "晴れ時々曇り": "🌤️", "曇り": "☁️", "曇り時々雨": "🌦️", "雨": "🌧️"}

PROMPT = """あなたは業界アナリストです。次の業界について、Web検索で公開情報を集め、
需要の見通しを「天気予報」の形でまとめてください。

業界: {industry}
主な顧客業界: {customers}
本日: {today}

ルール:
- 使ってよいのは誰でも見られる公開情報だけです（政府統計、業界団体の統計、
  上場企業の決算説明資料、信頼できる業界ニュース）。
- 根拠には、実際に検索結果で見つけたページのURLだけを書いてください。
  見つからない場合は推測で URL を作らず、根拠を減らしてください。
- 天気は「晴れ」「晴れ時々曇り」「曇り」「曇り時々雨」「雨」のどれかです。
- 3つの期間：short＝半年先、mid＝3〜4年先、long＝2030〜2040年。

最後に、次の形式の JSON だけを ```json ブロックで出力してください:
{{
  "headline": "今月の見出し（30字以内）",
  "forecasts": {{
    "short": {{"weather": "...", "title": "一言でいうと", "summary": "3〜4文", "drivers": [{{"point": "根拠となる事実", "url": "https://..."}}]}},
    "mid":   {{ 同じ形 }},
    "long":  {{ 同じ形 }}
  }},
  "watch": ["来月以降に注目すべきこと", "..."]
}}
"""


def ask_claude(industry: str, customers: str) -> tuple[dict, list[dict]]:
    client = anthropic.Anthropic()
    messages = [{
        "role": "user",
        "content": PROMPT.format(industry=industry, customers=customers,
                                 today=dt.date.today().isoformat()),
    }]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}]

    content = []
    for _ in range(5):  # 検索が長引いたとき（pause_turn）は続きを依頼する
        resp = client.messages.create(model=MODEL, max_tokens=8000,
                                      messages=messages, tools=tools)
        content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": resp.content})

    # 実際に検索でヒットした情報源を控えておく
    sources, seen = [], set()
    for block in content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                if r.url not in seen:
                    seen.add(r.url)
                    sources.append({"url": r.url, "title": r.title})

    text = "".join(b.text for b in content if b.type == "text")
    match = re.search(r"```json\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not match:
        sys.exit("レポートのJSONを読み取れませんでした。もう一度実行してください。")
    return json.loads(match.group(1)), sources


def render_html(industry: str, data: dict, sources: list[dict]) -> str:
    e = html.escape
    labels = {"short": "短期（半年先）", "mid": "中期（3〜4年先）", "long": "長期（2030〜2040年）"}
    found = {s["url"] for s in sources}

    cards = []
    for key, label in labels.items():
        f = data["forecasts"][key]
        drivers = "".join(
            f'<li>{e(d["point"])}'
            + (f' <a href="{e(d["url"])}" target="_blank">出典</a>' if d.get("url") in found else "")
            + "</li>"
            for d in f.get("drivers", [])
        )
        cards.append(f"""
      <section class="card">
        <div class="term">{label}</div>
        <div class="icon">{WEATHER_ICON.get(f["weather"], "❔")}</div>
        <div class="weather">{e(f["weather"])}</div>
        <h2>{e(f["title"])}</h2>
        <p>{e(f["summary"])}</p>
        <ul>{drivers}</ul>
      </section>""")

    watch = "".join(f"<li>{e(w)}</li>" for w in data.get("watch", []))
    src = "".join(f'<li><a href="{e(s["url"])}" target="_blank">{e(s["title"] or s["url"])}</a></li>'
                  for s in sources)
    today = dt.date.today().strftime("%Y年%m月号")

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(industry)} 市場天気予報 {today}</title>
<style>
  body {{ font-family: "Hiragino Sans", "Noto Sans JP", sans-serif; background:#f4f6fa; color:#1c2333; margin:0; }}
  header {{ background:#14284b; color:#fff; padding:28px 16px; text-align:center; }}
  header small {{ opacity:.7; letter-spacing:.1em; }}
  header h1 {{ margin:6px 0; font-size:1.6rem; }}
  .headline {{ font-size:1.1rem; margin-top:8px; }}
  main {{ max-width:1000px; margin:0 auto; padding:20px 16px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }}
  .card {{ background:#fff; border-radius:10px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  .term {{ font-size:.85rem; color:#5a6478; font-weight:bold; }}
  .icon {{ font-size:3rem; margin:8px 0 0; }}
  .weather {{ font-weight:bold; color:#14284b; }}
  h2 {{ font-size:1.05rem; margin:10px 0 6px; }}
  p, li {{ font-size:.92rem; line-height:1.7; }}
  a {{ color:#2a62c9; }}
  .box {{ background:#fff; border-radius:10px; padding:16px 20px; margin-top:16px; }}
  footer {{ text-align:center; font-size:.8rem; color:#7a8396; padding:20px; }}
</style></head>
<body>
  <header>
    <small>INDUSTRY WEATHER · {today}</small>
    <h1>{e(industry)} 市場天気予報</h1>
    <div class="headline">{e(data.get("headline", ""))}</div>
  </header>
  <main>
    <div class="grid">{"".join(cards)}</div>
    <div class="box"><h3>来月以降の注目点</h3><ul>{watch}</ul></div>
    <div class="box"><h3>参照した公開情報</h3><ol>{src}</ol></div>
  </main>
  <footer>公開情報のみをもとに自動生成しています。投資・経営判断の際は原典をご確認ください。</footer>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="業界の市場天気予報を作る")
    ap.add_argument("industry", help='業界名（例: "車載用抵抗器"）')
    ap.add_argument("--customers", default="指定なし", help='主な顧客業界（例: "自動車,産業機器"）')
    args = ap.parse_args()

    print(f"「{args.industry}」の公開情報を集めています…（数分かかります）")
    data, sources = ask_claude(args.industry, args.customers)

    os.makedirs("output", exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", args.industry).strip("_")
    path = os.path.join("output", f"{slug}_{dt.date.today():%Y%m}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(args.industry, data, sources))
    print(f"できました → {path}")


if __name__ == "__main__":
    main()
