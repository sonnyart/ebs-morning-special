#!/usr/bin/env python3
"""Build the EBS Morning Special (NYT News Coverage) study site with a
date-based archive.

Flow:
  1. Read data/latest.json  (newest day; written by the updater/agent)
  2. Archive it as data/days/<slug>.json
  3. Generate per-sentence English audio into audio/<slug>/
  4. Regenerate the whole site:
       index.html            -> latest day
       archive/index.html    -> list of all days (newest first)
       d/<slug>.html         -> one page per day
       data/index.json       -> machine-readable day list
  5. Optionally git commit + push

Day JSON schema:
{
  "date": "2026.10.13. Tue.",
  "title_en": "...", "author": "...", "copyright": "c.2026...",
  "source_url": "https://...",
  "sentences": [{"en": "...", "kr": "..."}, ...]
}
"""
import argparse, html, json, os, re, shutil, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = "Samantha"
BITRATE = "32000"

CSS = """
  :root { --accent:#8a6d3b; --bg:#faf6ef; --card:#fff; --ink:#241f17; --kr:#6b6356; --line:#ece3d3; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Noto Sans KR','Apple SD Gothic Neo',-apple-system,sans-serif; background:var(--bg); color:var(--ink); line-height:1.65; }
  .wrap { max-width:820px; margin:0 auto; padding:0 18px 90px; }
  .nav { display:flex; gap:14px; align-items:center; padding:14px 0; font-size:14px; font-weight:600; flex-wrap:wrap; }
  .nav a { color:var(--accent); text-decoration:none; }
  .nav a:hover { text-decoration:underline; }
  .nav .sp { flex:1; }
  header { border-bottom:2px solid var(--accent); padding-bottom:18px; }
  .kicker { font-size:12px; letter-spacing:1.5px; color:var(--accent); font-weight:700; text-transform:uppercase; }
  h1 { font-size:27px; margin:8px 0 6px; line-height:1.3; }
  .byline { color:var(--kr); font-size:14px; }
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin:20px 0 22px; position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:5; }
  .toolbar button { border:1px solid var(--accent); background:#fff; color:var(--accent); border-radius:999px; padding:8px 16px; font-size:14px; cursor:pointer; font-weight:600; }
  .toolbar button:hover, .toolbar button.active { background:var(--accent); color:#fff; }
  .item { display:flex; gap:14px; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:15px; margin-bottom:12px; }
  .play { flex:0 0 44px; height:44px; border-radius:50%; border:none; background:var(--accent); color:#fff; font-size:15px; cursor:pointer; transition:transform .1s; }
  .play:hover { transform:scale(1.08); }
  .play.playing { background:#2e7d5b; }
  .text { flex:1; }
  .num { font-size:11px; font-weight:700; color:var(--accent); margin-right:6px; }
  .en { font-size:17px; font-weight:500; margin-bottom:4px; }
  .kr { color:var(--kr); font-size:15px; }
  .foot { text-align:center; color:var(--kr); font-size:12px; margin-top:30px; }
  .foot a { color:var(--accent); }
  .list-title { font-size:20px; margin:6px 0 18px; }
  .day { display:block; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:10px; text-decoration:none; color:var(--ink); }
  .day:hover { border-color:var(--accent); }
  .day .d { font-weight:700; color:var(--accent); font-size:14px; }
  .day .t { font-size:16px; margin-top:2px; }
  .day .m { color:var(--kr); font-size:12px; margin-top:4px; }
  @media (max-width:520px) { h1 { font-size:22px; } .en { font-size:16px; } .wrap { padding:0 14px 70px; } }
"""

JS = r"""
const audios = {};
document.querySelectorAll('audio').forEach(a => audios[a.id.slice(1)] = a);
let current = null, currentBtn = null, sequential = false, rate = 1;
function stop(){ Object.values(audios).forEach(a=>{a.pause();a.currentTime=0;}); if(currentBtn)currentBtn.classList.remove('playing'); if(current)current.removeEventListener('ended',onEnded); current=null;currentBtn=null;sequential=false; }
function playOne(i,btn){ stop(); const a=audios[i]; if(!a)return; current=a; currentBtn=btn; a.playbackRate=rate; btn.classList.add('playing'); a.addEventListener('ended',onEnded); a.play().catch(()=>{}); }
function onEnded(){ if(currentBtn)currentBtn.classList.remove('playing'); const fin=current?current.id.slice(1):null; current=null;currentBtn=null; if(sequential&&fin){ const n=parseInt(fin)+1; const b=document.querySelector('.play[data-i="'+n+'"]'); if(b)playOne(n,b); else sequential=false; } }
document.querySelectorAll('.play').forEach(b=>b.addEventListener('click',()=>playOne(parseInt(b.dataset.i),b)));
document.getElementById('stopAll').addEventListener('click',stop);
document.getElementById('playAll').addEventListener('click',()=>{stop();sequential=true;playOne(1,document.querySelector('.play[data-i="1"]'));});
document.querySelectorAll('.speed').forEach(b=>b.addEventListener('click',()=>{ rate=parseFloat(b.dataset.r); document.querySelectorAll('.speed').forEach(x=>x.classList.remove('active')); b.classList.add('active'); if(current)current.playbackRate=rate; }));
"""


def slugify(date_str):
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", date_str or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return re.sub(r"[^0-9A-Za-z]+", "-", date_str).strip("-") or "day"


def gen_audio(texts, outdir):
    """Generate audio unless the folder already holds the right clip count."""
    if os.path.isdir(outdir):
        have = [f for f in os.listdir(outdir) if re.fullmatch(r"s\d+\.m4a", f)]
        if len(have) == len(texts):
            return outdir
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)
    for i, t in enumerate(texts, 1):
        aiff = os.path.join(outdir, f"t{i:02d}.aiff")
        m4a = os.path.join(outdir, f"s{i:02d}.m4a")
        subprocess.run(["say", "-v", VOICE, "-o", aiff, t], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", f"aac@{BITRATE}", "-c", "1", aiff, m4a], check=True)
        os.remove(aiff)
    return outdir


def day_page(data, base, days, is_latest):
    slug = data["slug"]
    date = html.escape(data.get("date", ""))
    rows = []
    for i, s in enumerate(data.get("sentences", []), 1):
        src = f"{base}audio/{slug}/s{i:02d}.m4a"
        rows.append(f'''  <div class="item">
    <button class="play" data-i="{i}" aria-label="Play">&#9654;</button>
    <div class="text"><div class="en"><span class="num">{i}.</span>{html.escape(s["en"])}</div>
    <div class="kr">{html.escape(s["kr"])}</div></div>
    <audio id="a{i}" preload="none" src="{src}"></audio>
  </div>''')
    rows_html = "\n".join(rows)
    newest = days[0]["slug"] if days else slug
    latest_link = "" if is_latest else f'<span class="sp"></span><a href="{base}index.html">&#9654; 최신 방송</a>'
    nav = f'<div class="nav"><a href="{base}archive/index.html">&#8592; 지난 방송 목록</a>{latest_link}</div>'
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>모닝스페셜 NYT News Coverage · {date}</title>
<style>{CSS}</style></head><body><div class="wrap">
{nav}
<header>
  <div class="kicker">EBS 모닝스페셜 · News Coverage from The New York Times</div>
  <h1>{html.escape(data.get("title_en",""))}</h1>
  <div class="byline">{html.escape(data.get("author",""))} · {html.escape(data.get("copyright",""))} · {date}</div>
</header>
<div class="toolbar">
  <button id="playAll">&#9654; 모두 재생</button>
  <button id="stopAll">&#9632; 정지</button>
  <button class="speed" data-r="0.75">0.75x</button>
  <button class="speed active" data-r="1">1x</button>
  <button class="speed" data-r="1.25">1.25x</button>
</div>
{rows_html}
<div class="foot">출처: EBS 최수진의 모닝스페셜 방송 내용 게시판 · <a href="{html.escape(data.get('source_url',''))}" target="_blank" rel="noopener">원문 보기</a><br>
본 텍스트는 학습용으로 정리한 것으로 원문과 다를 수 있습니다.</div>
</div><script>{JS}</script></body></html>"""


def archive_page(days, base):
    items = []
    for d in days:
        n = len(d.get("sentences", []))
        items.append(f'''  <a class="day" href="{base}d/{d["slug"]}.html">
    <div class="d">{html.escape(d.get("date",""))}</div>
    <div class="t">{html.escape(d.get("title_en",""))}</div>
    <div class="m">문장 {n}개</div>
  </a>''')
    items_html = "\n".join(items)
    nav = f'<div class="nav"><a href="{base}index.html">&#9654; 최신 방송</a></div>'
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>지난 방송 · 모닝스페셜 NYT News Coverage</title>
<style>{CSS}</style></head><body><div class="wrap">
{nav}
<header><div class="kicker">EBS 모닝스페셜 · News Coverage from The New York Times</div>
<h1>지난 방송 모음</h1></header>
<div class="list-title">총 {len(days)}편</div>
{items_html}
</div></body></html>"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def git_push(commit_msg):
    for c in (["add", "-A"], ["commit", "-m", commit_msg], ["push", "origin", "HEAD"]):
        r = subprocess.run(["git", "-C", REPO] + c, capture_output=True, text=True)
        print("$ git", " ".join(c))
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            print("ERR:", r.stderr.strip(), file=sys.stderr)
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(REPO, "data", "latest.json"))
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()

    with open(args.json, encoding="utf-8") as f:
        latest = json.load(f)
    if not latest.get("sentences"):
        print("No sentences in JSON; aborting.", file=sys.stderr)
        sys.exit(1)

    latest["slug"] = slugify(latest.get("date", ""))
    days_dir = os.path.join(REPO, "data", "days")
    write(os.path.join(days_dir, latest["slug"] + ".json"),
          json.dumps(latest, ensure_ascii=False, indent=1))

    # load all archived days, newest first
    days = []
    for fn in os.listdir(days_dir):
        if fn.endswith(".json"):
            with open(os.path.join(days_dir, fn), encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("slug", fn[:-5])
            days.append(d)
    days.sort(key=lambda d: d["slug"], reverse=True)

    # audio for each day (skip when already generated)
    for d in days:
        gen_audio([s["en"] for s in d["sentences"]], os.path.join(REPO, "audio", d["slug"]))

    # pages
    write(os.path.join(REPO, "index.html"), day_page(days[0], "", days, True))
    write(os.path.join(REPO, "archive", "index.html"), archive_page(days, "../"))
    for d in days:
        write(os.path.join(REPO, "d", d["slug"] + ".html"), day_page(d, "../", days, d["slug"] == days[0]["slug"]))

    # machine-readable index
    write(os.path.join(REPO, "data", "index.json"), json.dumps(
        [{"slug": d["slug"], "date": d.get("date"), "title_en": d.get("title_en"),
          "sentences": len(d.get("sentences", []))} for d in days],
        ensure_ascii=False, indent=1))

    total = 0
    adir = os.path.join(REPO, "audio")
    for root, _, fs in os.walk(adir):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in fs)
    print(f"Built site: {len(days)} days, latest={days[0]['slug']}, audio {total/1e6:.2f} MB")

    if args.push:
        ok = git_push(f"Update {days[0].get('date','')}")
        print("Pushed." if ok else "Push failed.", file=sys.stderr)
        sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
