#!/usr/bin/env python3
"""Build the EBS Morning Special (NYT News Coverage) unified study page.

One page shows every archived day with a date picker (no page navigation).

Flow:
  1. Read data/latest.json (newest day, written by the updater/agent)
  2. Archive it as data/days/<slug>.json (accumulates; never backfilled)
  3. Generate per-sentence English audio into audio/<slug>/
  4. Regenerate index.html: all days embedded, date picker + prev/next,
     hash routing (#YYYY-MM-DD). Also writes data/index.json.
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
  .picker { display:flex; gap:8px; align-items:center; padding:16px 0 10px; flex-wrap:wrap; position:sticky; top:0; background:var(--bg); z-index:10; border-bottom:1px solid var(--line); }
  .picker select { flex:1; min-width:150px; padding:9px 12px; border:1px solid var(--accent); border-radius:10px; background:#fff; color:var(--ink); font-size:15px; font-weight:600; font-family:inherit; }
  .picker button { border:1px solid var(--accent); background:#fff; color:var(--accent); border-radius:10px; padding:9px 12px; font-size:14px; cursor:pointer; font-weight:600; }
  .picker button:hover:not(:disabled) { background:var(--accent); color:#fff; }
  .picker button:disabled { opacity:.35; cursor:default; }
  header { border-bottom:2px solid var(--accent); padding:18px 0; }
  .kicker { font-size:12px; letter-spacing:1.5px; color:var(--accent); font-weight:700; text-transform:uppercase; }
  h1 { font-size:27px; margin:8px 0 6px; line-height:1.3; }
  .byline { color:var(--kr); font-size:14px; }
  .fav { flex:0 0 42px; height:42px; border:none; background:transparent; color:#c9a86a; font-size:24px; cursor:pointer; line-height:1; padding:0; }
  .fav:hover { transform:scale(1.18); color:#e0a400; }
  .fav.on { color:#e0a400; }
  .favlink { margin-left:auto; border:1px solid var(--accent); background:#fff; color:var(--accent); border-radius:999px; padding:9px 15px; font-size:14px; font-weight:600; text-decoration:none; }
  .favlink:hover { background:var(--accent); color:#fff; }
  .item { display:flex; gap:14px; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:15px; margin-bottom:12px; }
  .play { flex:0 0 44px; height:44px; border-radius:50%; border:none; background:var(--accent); color:#fff; font-size:15px; cursor:pointer; transition:transform .1s; }
  .play:hover { transform:scale(1.08); }
  .play.playing { background:#2e7d5b; }
  .play.paused { background:#c98a2b; }
  .text { flex:1; }
  .num { font-size:11px; font-weight:700; color:var(--accent); margin-right:6px; }
  .en { font-size:17px; font-weight:500; margin-bottom:4px; }
  .kr { color:var(--kr); font-size:15px; }
  .foot { text-align:center; color:var(--kr); font-size:12px; margin-top:30px; }
  .foot a { color:var(--accent); }
  @media (max-width:520px) { h1 { font-size:22px; } .en { font-size:16px; } .wrap { padding:0 14px 70px; } }
"""

JS = r"""
const DAYS = __DAYS__;
let idx = 0, rate = 1, current = null, currentBtn = null;
const view = document.getElementById('dayView');
const sel = document.getElementById('daySelect');

function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }

function buildSelect(){
  DAYS.forEach((d,i)=>{
    const o=document.createElement('option');
    o.value=i; o.textContent=(i===0? d.date+'  (최신)' : d.date);
    sel.appendChild(o);
  });
}

const ICON_PLAY='&#9654;', ICON_PAUSE='&#10074;&#10074;';
const FAV_KEY='ebs_ms_favs';
function getFavs(){ try{ return JSON.parse(localStorage.getItem(FAV_KEY)||'[]'); }catch(e){ return []; } }
function setFavs(v){ localStorage.setItem(FAV_KEY, JSON.stringify(v)); }
function isFav(id){ return getFavs().some(f=>f.id===id); }
function toggleFav(d, n, btn){
  const id=d.slug+':'+n;
  let favs=getFavs();
  const i=favs.findIndex(f=>f.id===id);
  if(i>=0){ favs.splice(i,1); } else { favs.push({id:id, slug:d.slug, date:d.date, title_en:d.title_en, en:d.sentences[n-1].en, kr:d.sentences[n-1].kr, n:n}); }
  setFavs(favs);
  btn.innerHTML = i>=0 ? '&#9734;' : '&#9733;';
  btn.classList.toggle('on', i<0);
}
function resetBtns(){ document.querySelectorAll('.play').forEach(b=>{b.classList.remove('playing','paused'); b.innerHTML=ICON_PLAY;}); }
function stop(){
  document.querySelectorAll('audio').forEach(a=>{a.pause();a.currentTime=0;});
  if(current)current.removeEventListener('ended',onEnded);
  current=null;currentBtn=null;resetBtns();
}
function onEnded(){
  if(currentBtn){currentBtn.classList.remove('playing','paused');currentBtn.innerHTML=ICON_PLAY;}
  current=null;currentBtn=null;
}
function toggle(i,btn){
  const a=document.getElementById('a'+i);
  if(!a)return;
  // 같은 문장: 재생 중이면 일시정지, 일시정지 상태면 이어서 재생
  if(current===a && !a.paused){ a.pause(); btn.classList.remove('playing'); btn.classList.add('paused'); btn.innerHTML=ICON_PLAY; return; }
  if(current===a && a.paused){ a.playbackRate=rate; a.play().catch(()=>{}); btn.classList.remove('paused'); btn.classList.add('playing'); btn.innerHTML=ICON_PAUSE; return; }
  // 다른 문장: 정지 후 새로 재생
  stop();
  current=a;currentBtn=btn;a.playbackRate=rate;
  btn.classList.add('playing'); btn.innerHTML=ICON_PAUSE;
  a.addEventListener('ended',onEnded);a.play().catch(()=>{});
}

function render(i, push){
  i=Math.max(0,Math.min(DAYS.length-1,i));
  stop();
  idx=i;
  const d=DAYS[i];
  const rows=d.sentences.map((s,n)=>'<div class="item">'
    +'<button class="play" data-i="'+(n+1)+'" aria-label="Play">&#9654;</button>'
    +'<div class="text"><div class="en"><span class="num">'+(n+1)+'.</span>'+esc(s.en)+'</div>'
    +'<div class="kr">'+esc(s.kr)+'</div></div>'
    +'<button class="fav" data-i="'+(n+1)+'" aria-label="즐겨찾기">&#9734;</button>'
    +'<audio id="a'+(n+1)+'" preload="none" src="audio/'+d.slug+'/s'+String(n+1).padStart(2,'0')+'.m4a"></audio>'
    +'</div>').join('');
  view.innerHTML='<header>'
    +'<div class="kicker">EBS 모닝스페셜 · News Coverage from The New York Times</div>'
    +'<h1>'+esc(d.title_en)+'</h1>'
    +'<div class="byline">'+esc(d.author)+' · '+esc(d.copyright)+' · '+esc(d.date)+'</div>'
    +'</header>'
    +rows
    +'<div class="foot">출처: EBS 최수진의 모닝스페셜 방송 내용 게시판 · <a href="'+esc(d.source_url)+'" target="_blank" rel="noopener">원문 보기</a><br>'
    +'본 텍스트는 학습용으로 정리한 것으로 원문과 다를 수 있습니다.</div>';

  view.querySelectorAll('.play').forEach(b=>b.addEventListener('click',()=>toggle(parseInt(b.dataset.i),b)));
  view.querySelectorAll('.fav').forEach(b=>{
    const n=parseInt(b.dataset.i);
    const on=isFav(d.slug+':'+n);
    b.innerHTML=on?'&#9733;':'&#9734;';
    b.classList.toggle('on',on);
    b.addEventListener('click',()=>toggleFav(d,n,b));
  });

  sel.value=i;
  document.getElementById('prevDay').disabled = i>=DAYS.length-1;
  document.getElementById('nextDay').disabled = i<=0;
  if(push!==false) history.replaceState(null,'','#'+d.slug);
  window.scrollTo({top:0,behavior:'smooth'});
}

buildSelect();
sel.addEventListener('change',()=>render(parseInt(sel.value)));
document.getElementById('prevDay').addEventListener('click',()=>render(idx+1));
document.getElementById('nextDay').addEventListener('click',()=>render(idx-1));
document.getElementById('todayBtn').addEventListener('click',()=>render(0));

const start = DAYS.findIndex(d=>d.slug===location.hash.slice(1));
render(start>=0?start:0, false);
window.addEventListener('hashchange',()=>{ const i=DAYS.findIndex(d=>d.slug===location.hash.slice(1)); if(i>=0&&i!==idx)render(i,false); });
"""


def slugify(date_str):
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", date_str or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return re.sub(r"[^0-9A-Za-z]+", "-", date_str).strip("-") or "day"


def gen_audio(texts, outdir):
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


def build_index(days):
    payload = [{"slug": d["slug"], "date": d.get("date", ""), "title_en": d.get("title_en", ""),
                "author": d.get("author", ""), "copyright": d.get("copyright", ""),
                "source_url": d.get("source_url", ""), "sentences": d.get("sentences", [])}
               for d in days]
    js = JS.replace("__DAYS__", json.dumps(payload, ensure_ascii=False))
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>모닝스페셜 NYT News Coverage (최신 + 지난 방송)</title>
<style>{CSS}</style></head><body><div class="wrap">
<div class="picker">
  <button id="prevDay" title="이전 방송">&#9664;</button>
  <select id="daySelect" aria-label="날짜 선택"></select>
  <button id="nextDay" title="다음 방송">&#9654;</button>
  <button id="todayBtn">최신</button>
  <a class="favlink" href="favorites.html">&#9733; 즐겨찾기</a>
</div>
<div id="dayView"></div>
</div><script>{js}</script></body></html>"""


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

    days = []
    for fn in os.listdir(days_dir):
        if fn.endswith(".json"):
            with open(os.path.join(days_dir, fn), encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("slug", fn[:-5])
            days.append(d)
    days.sort(key=lambda d: d["slug"], reverse=True)

    for d in days:
        gen_audio([s["en"] for s in d["sentences"]], os.path.join(REPO, "audio", d["slug"]))

    write(os.path.join(REPO, "index.html"), build_index(days))
    write(os.path.join(REPO, "data", "index.json"), json.dumps(
        [{"slug": d["slug"], "date": d.get("date"), "title_en": d.get("title_en"),
          "sentences": len(d.get("sentences", []))} for d in days],
        ensure_ascii=False, indent=1))

    for junk in (os.path.join(REPO, "archive"), os.path.join(REPO, "d")):
        if os.path.isdir(junk):
            shutil.rmtree(junk)

    total = 0
    for root, _, fs in os.walk(os.path.join(REPO, "audio")):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in fs)
    print(f"Built unified index.html: {len(days)} days, latest={days[0]['slug']}, audio {total/1e6:.2f} MB")

    if args.push:
        ok = git_push(f"Update {days[0].get('date','')}")
        print("Pushed." if ok else "Push failed.", file=sys.stderr)
        sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
