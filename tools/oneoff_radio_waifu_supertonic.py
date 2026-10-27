"""Create short, natural Russian female stream voices with Supertone/Supertonic 3.
New voice family; NOT pitch-shifted or edited Silero. Commercial-use-aware licence metadata.
"""
import os, sys, json, math, shutil, subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import imageio_ffmpeg
from huggingface_hub import snapshot_download

ROOT=Path.cwd()
ENGINE=ROOT/"supertonic-engine"
MODEL=ROOT/"supertone-assets"
OUT=ROOT/"radio_waifu_new_voice"
OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ENGINE/"py"))
from helper import load_text_to_speech, load_voice_style

print("DOWNLOADING public archived TTS model", flush=True)
snapshot_download(
 repo_id="supertone-oss-archive/supertonic-3",
 revision="aafc6e32416a594460b32413efc49d7fe4ce6d46",
 local_dir=str(MODEL),
 allow_patterns=["onnx/*","voice_styles/F*.json","LICENSE*","README.md"],
 max_workers=5
)
print("LOADING ONNX MODEL",flush=True)
engine=load_text_to_speech(str(MODEL/"onnx"),False)
rate=int(engine.sample_rate)
print("MODEL LOADED, samplerate",rate,flush=True)

def create(stem,voice,text,steps=12,speed=1.0):
 style=load_voice_style([str(MODEL/"voice_styles"/f"{voice}.json")],verbose=False)
 wav,durations=engine(text,"ru",style,steps,speed)
 x=np.asarray(wav[0,:round(float(durations[0])*rate)],dtype=np.float32)
 # Do not shift pitch, add reverb, fake breathing, or modify timbre.
 x=np.nan_to_num(x)
 assert len(x)>int(rate*.5),(stem,len(x))
 x-=float(x.mean())
 peak=float(np.max(np.abs(x)))
 assert peak>.005, (stem,peak)
 # Present in alert with clear headroom. Avoid compression and clipping.
 x=x*(10**(-8/20)/peak)
 pad=np.zeros(int(.10*rate),dtype=np.float32)
 x=np.concatenate([pad,x,np.zeros(int(.08*rate),dtype=np.float32)])
 wav_file=OUT/(stem+".wav")
 sf.write(wav_file,x,rate,subtype="PCM_16")
 mp3_file=OUT/(stem+".mp3")
 cmd=[imageio_ffmpeg.get_ffmpeg_exe(),"-hide_banner","-loglevel","error","-y","-i",str(wav_file),"-ac","2","-codec:a","libmp3lame","-b:a","256k",str(mp3_file)]
 p=subprocess.run(cmd,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr.decode())
 assert mp3_file.stat().st_size>20000,stem
 print("FINISHED",mp3_file.name,"duration",round(len(x)/rate,2),"secs","peak dB -8",flush=True)
 return {"name":mp3_file.name,"voice":voice,"text":text,"seconds":round(len(x)/rate,2),"bytes":mp3_file.stat().st_size}

tracks=[]
for name,voice,speed in [
 ("RADIO_WAIFU_01_SOFT", "F1", .98),
 ("RADIO_WAIFU_02_CLEAR", "F2", 1.03),
 ("RADIO_WAIFU_03_CHEERFUL", "F3", 1.04)]:
 tracks.append(create(name,voice,"Спасибо за поддержку!",speed=speed))
# Event-specific lines using primary voice F2; no overlap with ongoing donor voiceover.
tracks.append(create("RADIO_WAIFU_FOLLOWER", "F2", "Спасибо за поддержку! Рада видеть тебя на нашей частоте!",speed=1.02))
tracks.append(create("RADIO_WAIFU_DONATION", "F2", "Спасибо за поддержку! Ты просто чудо!",speed=1.03))
# 3-voice audition with 0.65s pauses. No previous Silero files.
preview=[]
for i,t in enumerate(tracks[:3]):
 data,sr=sf.read(str(OUT/t["name"]).replace(".mp3",".wav"),dtype="float32")
 preview.append(data)
 if i<2:preview.append(np.zeros(round(.65*rate),dtype=np.float32))
a=np.concatenate(preview)
sf.write(OUT/"RADIO_WAIFU_THREE_VOICES_PREVIEW.wav",a,rate,subtype="PCM_16")
p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-hide_banner","-loglevel","error","-y","-i",str(OUT/"RADIO_WAIFU_THREE_VOICES_PREVIEW.wav"),"-codec:a","libmp3lame","-b:a","192k",str(OUT/"RADIO_WAIFU_THREE_VOICES_PREVIEW.mp3")],capture_output=True)
if p.returncode:raise RuntimeError(p.stderr.decode())
(OUT/"RADIO_WAIFU_THREE_VOICES_PREVIEW.wav").unlink()
(OUT/"README_RU.txt").write_text(
 "RADIO WAIFU — НОВЫЙ ГОЛОС ДЛЯ ДОНАТОВ И ФОЛЛОВЕРОВ\n\n"
 "Новая модель Supertonic 3, русский язык, женские пресеты F1/F2/F3.\n"
 "01 SOFT — спокойный нежный женский тембр.\n"
 "02 CLEAR — звонкий, разборчивый женский тембр.\n"
 "03 CHEERFUL — немного более энергичный женский тембр.\n"
 "FOLLOWER — расширенная фраза для нового фолловера.\n"
 "DONATION — расширенная фраза для доната.\n\n"
 "Все звуки без намеренной имитации конкретных людей, без эффектов робота, радио и перегруза.\n"
 "MP3 256 кбит/с + WAV 16-bit для каждого оповещения. Уровень около -8 dBFS peak.\n"
 "DonationAlerts: звук обычной вариации -> один из MP3. Twitch/Kick followers: отдельное событие.\n"
 "Перед выходом в эфир проверь реальное воспроизведение и комфортную громкость.\n\n"
 "Источник: Supertone Supertonic 3 (архивированный весовой файл).\n"
 "Модель: https://huggingface.co/supertone-oss-archive/supertonic-3\n"
 "Лицензия весов: OpenRAIL-M. Коммерческое применение допускается с ограничениями по допустимому использованию и атрибуцией.\n"
 "Код: MIT. Учитывайте лицензию при распространении результатов.\n"
 "Это автоматически синтезированная речь; естественность на слух требует прослушивания человеком.\n",
 encoding="utf-8"
)
(OUT/"metadata.json").write_text(json.dumps(tracks,ensure_ascii=False,indent=2),encoding="utf-8")
print("SUCCESS",len(tracks),"clips",flush=True)
