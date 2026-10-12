#!/usr/bin/env python3
"""Build the EBS Morning Special (NYT News Coverage) study page.

Reads data/latest.json, generates per-sentence English audio (macOS `say`),
writes index.html, and optionally commits + pushes to GitHub Pages.

latest.json schema:
{
  "date": "2026.10.13. Tue.",
  "title_en": "...", "author": "...", "copyright": "c.2026 The New York Times Company",
  "source_url": "https://...",
  "sentences": [{"en": "...", "kr": "..."}, ...]
}
"""
import argparse, html, json, os, shutil, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = "Samantha"
BITRATE = "32000"

CSS = """
  :root { --accent:#8a6d3b; --bg:#faf6ef; --card:#fff; --ink:#241f17; --kr:#6b6356; --line:#ece3d3; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Noto Sans KR','Apple SD Gothic Neo',-apple-system,sans-serif; background:var(--bg); color:var(--ink); line-height:1.65; }
  .wrap { max-width:820px; margin:0 auto; padding:32px 18px 90px; }
  header { border-bottom:2px solid var(--accent); padding-bottom:18px; }
  .kicker { font-size:12px; letter-spacing:1.5px; color:var(--accent); font-weight:700; text-transform:uppercase; }
  h1 { font-size:27px; margin:8px 0 6px; line-height:1.3; }
  .byline { color:var(--kr); font-size:14px; }
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin:20px 0 22px; position:sticky; top:0; background:var(--bg); padding:10px 0; }
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
  @media (max-width:520px) { h1 { font-size:22px; } .en { font-size:16px; } .wrap { padding:22px 14px 70px; } }
"""

JS = r"""
const audios = {};
document.querySelectorAll('audio').forEach(a => audios[a.id.slice(1)] = a);
let current = null, currentBtn = null, sequential = false, rate = 1;
function fmt(p){ if(!isFinite(p)) return 0; return p; }
function stop(){ Object.values(audios).forEach(a=>{a.pause();a.currentTime=0;}); if(currentBtn)currentBtn.classList.remove('playing'); if(current)current.removeEventListener('ended',onEnded); current=null;currentBtn=null;sequential=false; }
function playOne(i,btn){ stop(); const a=audios[i]; if(!a)return; current=a; currentBtn=btn; a.playbackRate=rate; btn.classList.add('playing'); a.addEventListener('ended',onEnded); a.play().catch(()=>{}); }
function onEnded(){ if(currentBtn)currentBtn.classList.remove('playing'); const fin=current?current.id.slice(1):null; current=null;currentBtn=null; if(sequential&&fin){ const n=parseInt(fin)+1; const b=document.querySelector('.play[data-i="'+n+'"]'); if(b)playOne(n,b); else sequential=false; } }
document.querySelectorAll('.play').forEach(b=>b.addEventListener('click',()=>playOne(parseInt(b.dataset.i),b)));
document.getElementById('stopAll').addEventListener('click',stop);
document.getElementById('playAll').addEventListener('click',()=>{stop();sequential=true;playOne(1,document.querySelector('.play[data-i="1"]'));});
document.querySelectorAll('.speed').forEach(b=>b.addEventListener('click',()=>{ rate=parseFloat(b.dataset.r); document.querySelectorAll('.speed').forEach(x=>x.classList.remove('active')); b.classList.add('active'); if(current)current.playbackRate=rate; }));
"""


def gen_audio(texts, outdir):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)
    made = []
    for i, t in enumerate(texts, 1):
        aiff = os.path.join(outdir, f"t{i:02d}.aiff")
        m4a = os.path.join(outdir, f"s{i:02d}.m4a")
        subprocess.run(["say", "-v", VOICE, "-o", aiff, t], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", f"aac@{BITRATE}", "-c", "1", aiff, m4a], check=True)
        os.remove(aiff)
        made.append(m4a)
    return made


def build_html(data, outfile):
    date = html.escape(data.get("date", ""))
    title = html.escape(data.get("title_en", ""))
    author = html.escape(data.get("author", ""))
    copyr = html.escape(data.get("copyright", ""))
    src = html.escape(data.get("source_url", ""))
    sents = data.get("sentences", [])
    rows = []
    for i, s in enumerate(sents, 1):
        rows.append(f'''  <div class="item">
    <button class="play" data-i="{i}" aria-label="Play">&#9654;</button>
    <div class="text"><div class="en"><span class="num">{i}.</span>{html.escape(s["en"])}</div>
    <div class="kr">{html.escape(s["kr"])}</div></div>
    <audio id="a{i}" preload="none" src="audio/s{i:02d}.m4a"></audio>
  </div>''')
    rows_html = "\n".join(rows)
    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>모닝스페셜 NYT News Coverage · {date}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header>
  <div class="kicker">EBS 모닝스페셜 · News Coverage from The New York Times</div>
  <h1>{title}</h1>
  <div class="byline">{author} · {copyr} · {date}</div>
</header>
<div class="toolbar">
  <button id="playAll">&#9654; 모두 재생</button>
  <button id="stopAll">&#9632; 정지</button>
  <button class="speed" data-r="0.75">0.75x</button>
  <button class="speed active" data-r="1">1x</button>
  <button class="speed" data-r="1.25">1.25x</button>
</div>
{rows_html}
<div class="foot">출처: EBS 최수진의 모닝스페셜 방송 내용 게시판 · <a href="{src}" target="_blank" rel="noopener">원문 보기</a><br>
본 텍스트는 학습용으로 정리한 것으로 원문과 다를 수 있습니다.</div>
</div><script>{JS}</script></body></html>"""
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(doc)
    return outfile


def git_push(commit_msg):
    cmds = [
        ["git", "-C", REPO, "add", "-A"],
        ["git", "-C", REPO, "commit", "-m", commit_msg],
        ["git", "-C", REPO, "push", "origin", "HEAD"],
    ]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True)
        print("$", " ".join(c))
        print(r.stdout.strip())
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
        data = json.load(f)
    sents = data.get("sentences", [])
    if not sents:
        print("No sentences in JSON; aborting.", file=sys.stderr)
        sys.exit(1)

    audio_dir = os.path.join(REPO, "audio")
    gen_audio([s["en"] for s in sents], audio_dir)
    build_html(data, os.path.join(REPO, "index.html"))

    total = sum(os.path.getsize(os.path.join(audio_dir, f)) for f in os.listdir(audio_dir))
    print(f"Built index.html + {len(sents)} audio clips ({total/1e6:.2f} MB)")

    if args.push:
        ok = git_push(f"Update {data.get('date','')}")
        print("Pushed." if ok else "Push failed.", file=sys.stderr)
        sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
