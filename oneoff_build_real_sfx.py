"""Build 6 distinct royalty-free horror donation alert mixes from Mixkit source recordings."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import requests

SAMPLE_RATE = 48000
OUTPUT = Path("out")
OUTPUT.mkdir(exist_ok=True)
wanted = {
    "monster growl": "scream",
    "zombie monster growl": "monster",
    "creepy demon heavy breathing": "monster",
    "angry monster scream": "scream",
    "giant monster roar": "scream",
    "creature long screech": "monster",
    "golem stomp c": "horror",
    "horror impact": "impact",
    "glitch roar": "glitch",
    "broken radio frequency signal": "terror",
    "movie trailer whoosh hit": "terror",
    "giant monster footstep": "monster",
}
pages = {}
sources = {}
clips = {}
for title, page in wanted.items():
    if page not in pages:
        r = requests.get(f"https://mixkit.co/free-sound-effects/{page}/", timeout=40)
        r.raise_for_status()
        pages[page] = r.text
    site = pages[page]
    pattern = r'<h2[^>]*class="[^"]*item-grid-card__title[^"]*"[^>]*>\s*' + re.escape(title) + r'\s*</h2>'
    m = re.search(pattern, site, flags=re.I | re.S)
    if not m:
        raise RuntimeError(f"Cannot verify Mixkit sound title {title!r} on {page}")
    links = re.findall(
        r'https://assets\.mixkit\.co/active_storage/sfx/\d+/\d+-preview\.mp3',
        site[max(0, m.start()-12000):m.start()],
    )
    if not links:
        raise RuntimeError(f"Cannot locate sample URL for {title}")
    url = links[-1]
    audio = requests.get(url, timeout=45)
    audio.raise_for_status()
    if len(audio.content) < 2000:
        raise RuntimeError(f"Bad audio {title}: {len(audio.content)} bytes")
    cmd = [
        "ffmpeg","-v","error","-i","pipe:0","-ar",str(SAMPLE_RATE),
        "-ac","2","-f","f32le","-acodec","pcm_f32le","pipe:1",
    ]
    proc = subprocess.run(cmd, input=audio.content, capture_output=True, check=True)
    decoded = np.frombuffer(proc.stdout, dtype="<f4").reshape(-1,2).copy()
    clips[title] = decoded
    sources[title] = {
        "catalog":f"https://mixkit.co/free-sound-effects/{page}/",
        "preview":url,
        "original_bytes":len(audio.content),
    }
    print("GOT", title, len(decoded)/SAMPLE_RATE, url, flush=True)

tiers = [
    (55,3.36,1.52,"monster growl","creepy demon heavy breathing","golem stomp c"),
    (111,3.15,1.44,"zombie monster growl","giant monster footstep","movie trailer whoosh hit"),
    (222,3.24,1.53,"creepy demon heavy breathing","broken radio frequency signal","horror impact"),
    (333,3.24,1.62,"angry monster scream","giant monster footstep","golem stomp c"),
    (444,3.33,1.62,"creature long screech","broken radio frequency signal","horror impact"),
    (555,3.42,1.80,"giant monster roar","creepy demon heavy breathing","glitch roar"),
]

def add(mix, title, second, loudness, time, fadein, fadeout):
    sound=clips[title]
    start=int(second*SAMPLE_RATE)
    available=len(mix)-start
    n=min(len(sound),int(time*SAMPLE_RATE),available)
    if n<1:return
    x=sound[:n].copy()
    p=np.max(np.abs(x))
    if p<=.001:return
    x/=p
    fa=min(int(fadein*SAMPLE_RATE),n)
    fb=min(int(fadeout*SAMPLE_RATE),n)
    if fa:x[:fa]*=np.linspace(0,1,fa)[:,None]
    if fb:x[-fb:]*=np.linspace(1,0,fb)[:,None]
    mix[start:start+n]+=x*loudness

def mp3(filename, waveform, bitrate="256k"):
    proc=subprocess.run([
        "ffmpeg","-y","-v","error","-f","f32le","-ar",str(SAMPLE_RATE),
        "-ac","2","-i","pipe:0","-codec:a","libmp3lame","-b:a",bitrate,str(filename)
    ],input=waveform.astype("<f4").tobytes(),capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode())

tracks=[]
manifest=[]
for amount,duration,hit,scream,cue,impact in tiers:
    mix=np.zeros((round(duration*SAMPLE_RATE),2),dtype=np.float32)
    # Genuine recorded footsteps, breaths or radio cue: 26 dB quieter than impact.
    add(mix,cue,max(.04,hit-1.08),.052,.8,.075,.12)
    # Sudden recorded creature scream + clean physical impact, no synthesizer.
    add(mix,scream,hit,.50,duration-hit-.08,.005,.20)
    add(mix,impact,hit+.015,.20,.62,.004,.18)
    peak=float(np.max(np.abs(mix)))
    assert peak>0.001
    mix*=10**(-4/20)/peak
    fade=min(len(mix),int(.09*SAMPLE_RATE))
    mix[-fade:]*=np.linspace(1,0,fade)[:,None]
    outfile=OUTPUT/f"RADIO_SILENCE_{amount}_REAL_JUMPSCARE.mp3"
    mp3(outfile,mix)
    manifest.append(dict(amount=amount,duration=duration,hit_second=hit,voices=[scream,cue,impact],path=outfile.name,peak=float(np.max(np.abs(mix)))))
    tracks.append(mix)
    print("DONE",amount,outfile.stat().st_size,flush=True)

gap=np.zeros((round(.7*SAMPLE_RATE),2),dtype=np.float32)
preview=np.concatenate([chunk for i,mix in enumerate(tracks) for chunk in ([mix,gap] if i+1<len(tracks) else [mix])])
mp3(OUTPUT/"RADIO_SILENCE_ALL_6_REAL_JUMPSCARES_PREVIEW.mp3",preview,"192k")
readme="""RADIO SILENCE — НОВЫЕ СКРИМЕРЫ, 55 / 111 / 222 / 333 / 444 / 555 ₽

Эти файлы собраны из настоящих записанных SFX Mixkit, а не синтезированного шума.
Каждый звук — тихое предупреждение, резкий крик/рёв точно на нужном кадре GIF, короткое затухание.
Ограничение по уровню — около −4 dBFS. Начальная громкость DonationAlerts — 25–35%.
Обычные донаты и штатную аниме-девочку не менять.

Использованные записанные эффекты: файл SOURCES.json.
Условия Mixkit Sound Effects Free License:
https://mixkit.co/license/modal/sfxFree/
Бесплатно для коммерческих проектов и интернет-трансляций.
Композитные оповещения — часть стрима, а не библиотека для перепродажи;
нельзя распространять исходные стоковые эффекты сами по себе.

В DonationAlerts каждая сумма — отдельная вариация типа «Платные сообщения»
с условием «Сумма равна». В «Звук» ставится соответствующий MP3.
"""
(OUTPUT/"README_RU.txt").write_text(readme,encoding="utf-8")
(OUTPUT/"SOURCES.json").write_text(json.dumps({"license":"https://mixkit.co/license/modal/sfxFree/","sources":sources,"tracks":manifest},ensure_ascii=False,indent=2),encoding="utf-8")
print("ALL SIX COMPLETED",flush=True)
