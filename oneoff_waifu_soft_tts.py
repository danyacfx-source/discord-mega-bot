"""One-off soft bright RADIO WAIFU Russian stream alert voice audition.
Model: Silero V5 CIS Base NoStress MIT, no commercial service needed.
"""
from pathlib import Path
import numpy as np
import torch
import soundfile as sf
import subprocess, json, math
import imageio_ffmpeg

torch.set_num_threads(4)
OUT=Path('waifu_soft_voice_out');OUT.mkdir(exist_ok=True)
SR=48000
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
model,info=torch.hub.load(repo_or_dir='snakers4/silero-models',model='silero_tts',language='ru',speaker='v5_cis_base_nostress',trust_repo=True)
model.to('cpu')
print("MODEL LOADED", flush=True)

# Five substantially DIFFERENT voices, rather than pitch-shift copies of the rough original ru_ekaterina.
voices=[
 ('01_MELODIC','ru_ramilia',1.047,'мелодичный и звонкий'),
 ('02_GENTLE','ru_aigul',1.034,'мягкий и нежный'),
 ('03_WARM','ru_albina',1.062,'тёплый и светлый'),
 ('04_BRIGHT','ru_vika',1.032,'яркий'),
 ('05_AIRY','ru_alfia2',1.045,'воздушный')
]
phrases=[
 ('SUPPORT','Спас+ибо за подд+ержку!'),
 ('FOLLOWER','Спас+ибо за подд+ержку! Р+ада в+идеть теб+я на н+ашей частот+е!'),
 ('DONATION','Спас+ибо за подд+ержку! Ты ч+удо!')
]
metadata=[]
def synth(stem,speaker,speedup,text,style):
 print("GENERATING",stem,speaker,flush=True)
 try:
  with torch.inference_mode():
   audio=model.apply_tts(text=text,speaker=speaker,sample_rate=SR)
 except Exception as e:
  print("FAIL",stem,repr(e),flush=True);raise
 x=np.asarray(audio.detach().cpu().numpy() if hasattr(audio,'detach') else audio,dtype=np.float32).reshape(-1)
 assert len(x)>5000,(stem,len(x))
 x=np.nan_to_num(x)
 x-=float(np.mean(x))
 x=np.concatenate([np.zeros(int(.11*SR),dtype=np.float32),x,np.zeros(int(.09*SR),dtype=np.float32)])
 peak=float(np.max(np.abs(x)))
 assert peak>0.015, (stem,peak)
 # Speech-focused stable loudness; NO radio crackle, saturation or synthetic "robot" FX.
 x=x*(10**(-8/20))/peak
 src=OUT/(stem+'_TEMP.wav');sf.write(src,x,SR,subtype='PCM_24')
 # Very subtle playback-rate change (<6.2%) brightens natural voice only a little.
 # De-essing? No: untouched natural high frequencies for a clear articulate voice.
 filter_spec=f"asetrate={int(SR*speedup)},aresample={SR},highpass=f=75,afade=t=in:st=0:d=0.05"
 mp3=OUT/(stem+'.mp3')
 proc=subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y','-i',str(src),'-af',filter_spec,'-ar',str(SR),'-ac','2','-c:a','libmp3lame','-b:a','256k',str(mp3)],capture_output=True)
 if proc.returncode:raise RuntimeError(proc.stderr.decode())
 src.unlink()
 assert mp3.stat().st_size>20000
 duration=(len(x)/SR)/speedup
 metadata.append(dict(file=mp3.name,voice=speaker,descriptor=style,text=text.replace('+',''),duration_seconds=round(duration,3),playback_speed_factor=speedup))
 print("DONE",mp3.name,"duration",round(duration,2),"MB",round(mp3.stat().st_size/1e6,3),flush=True)

for no,speaker,boost,desc in voices:
 synth(f"RADIO_WAIFU_{no}_THANK_YOU",speaker,boost,phrases[0][1],desc)
# Produce actual separate follower and donation complete phrases with 2 softest recommended timbres,
# without forcing one flavor: user can choose after audition.
for no,speaker,boost,desc in voices[:2]:
 synth(f"RADIO_WAIFU_{no}_FOLLOWER",speaker,boost,phrases[1][1],desc)
 synth(f"RADIO_WAIFU_{no}_DONATION",speaker,boost,phrases[2][1],desc)

(OUT/'README_RU.txt').write_text(
"""RADIO WAIFU — 5 свежих вариантов мягкой русской женской озвучки для донатов и фолловеров.

Сначала прослушай 01_MELODIC и 02_GENTLE — именно их я рекомендую для RADIO WAIFU.
Остальные — самостоятельные женские тембры, а не копии предыдущего грубого голоса.
Произносится «Спасибо за поддержку!».

Файлы *_FOLLOWER и *_DONATION — дополнительные фразы в тембрах 01 и 02.

Звук: 48 кГц, стерео MP3, 256 кбит/с, небольшой запас по пикам;
нет перегруза, радио-помех или музыки.
Длительность реплик зависит от артикуляции выбранного тембра.
Оформление GIF RADIO WAIFU не меняется.

Источник: Silero V5 CIS Base NoStress (MIT).
Лицензия: https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS
Коммерческое использование разрешено.
При желании другие варианты можно донастроить в OBS/DonationAlerts без подписок.
""",encoding='utf-8')
(OUT/'VOICE_METADATA.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
print('ALL COMPLETE',len(metadata),flush=True)
