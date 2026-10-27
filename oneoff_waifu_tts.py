"""One-time RADIO WAIFU Russian female voice assets for stream alert usage.
Generates with MIT-licensed Silero v5 CIS Base: see https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS
No paid TTS APIs, no uploaded/user voices.
"""
import os, json, subprocess, math
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import imageio_ffmpeg

SR=48000
OUT=Path('waifu_voice_out')
OUT.mkdir(exist_ok=True)
torch.set_num_threads(min(os.cpu_count() or 4,4))
print('Loading Silero v5 CIS Base NoStress model (MIT)...',flush=True)
model, example = torch.hub.load(
    repo_or_dir='snakers4/silero-models',
    model='silero_tts',
    language='ru',
    speaker='v5_cis_base_nostress',
    trust_repo=True,
)
print('Model loaded; generating voices',flush=True)
try:
    model.to('cpu')
except Exception: pass

# Russian stress-mark syntax documented by the base model: '+' before stressed vowel.
lines=[
    ('RADIO_WAIFU_SUPPORT_MAIN','ru_ekaterina','Спас+ибо за подд+ержку!','универсальная: донаты и фолловеры'),
    ('RADIO_WAIFU_NEW_FOLLOWER','ru_ekaterina','Спас+ибо за подд+ержку! Р+ада в+идеть теб+я на н+ашей частот+е!','новый фолловер'),
    ('RADIO_WAIFU_DONATION','ru_ekaterina','Спас+ибо за подд+ержку! Т+ы просто ч+удо!','донат'),
    ('RADIO_WAIFU_SUPPORT_ALT','ru_zara','Спас+ибо за подд+ержку!','альтернативный женский голос'),
]

FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
metadata=[]
for filename,speaker,phrase,usage in lines:
    print('VOICE', filename,speaker,phrase,flush=True)
    try:
        with torch.inference_mode():
            tensor=model.apply_tts(text=phrase,speaker=speaker,sample_rate=SR)
    except Exception as e:
        print("ERROR",filename,repr(e),flush=True)
        raise
    a=np.asarray(tensor.detach().cpu().numpy() if hasattr(tensor,'detach') else tensor,dtype=np.float32).reshape(-1)
    assert len(a)>SR*.5, f'no speech {filename}'
    a=np.nan_to_num(a)
    # Basic cleanup and gentle, warm streaming-alert polish without static or distortion.
    a-=np.mean(a)
    # Slight high-pass (10 Hz); remove DC via first-order filter.
    alpha=math.exp(-2*math.pi*45/SR)
    hp=np.empty_like(a)
    prev_x=prev_y=0.0
    for i in range(len(a)):
        prev_y=alpha*(prev_y+a[i]-prev_x)
        hp[i]=prev_y
        prev_x=a[i]
    a=hp
    # 110 ms pre-roll gives the alert image a chance to appear before speech starts
    pad=np.zeros(int(.11*SR),dtype=np.float32)
    a=np.concatenate([pad,a])
    # 100 ms clean fade tail
    fade=min(int(.075*SR),len(a))
    a[-fade:]*=np.linspace(1,0,fade).astype(np.float32)
    peak=float(np.max(np.abs(a)))
    assert peak>0.005, "Silent TTS"
    a*=10**(-5/20)/peak
    # Export original clean voice in WAV and streaming MP3
    sf.write(OUT/f'{filename}.wav',a,SR,subtype='PCM_16')
    proc=subprocess.run([FFMPEG,'-y','-v','error','-i',str(OUT/f'{filename}.wav'),'-codec:a','libmp3lame','-b:a','256k',str(OUT/f'{filename}.mp3')],capture_output=True)
    if proc.returncode:raise RuntimeError(proc.stderr.decode())
    print('OK',filename,'duration',round(len(a)/SR,2),'bytes', (OUT/f'{filename}.mp3').stat().st_size,flush=True)
    metadata.append(dict(file=filename+'.mp3',speaker=speaker,original_text=phrase.replace('+',''),usage=usage,duration=round(len(a)/SR,3),peak_dbfs=-5))

readme="""RADIO WAIFU — ГОТОВЫЕ ОЗВУЧКИ ДЛЯ ОПОВЕЩЕНИЙ

Голос: синтезированный русский женский голос Silero v5 CIS Base NoStress.
Без платных подписок и без имитации голоса реального человека.
Основной голос: ru_ekaterina. Дополнительно — ru_zara.

1) RADIO_WAIFU_SUPPORT_MAIN.mp3 — «Спасибо за поддержку!»
   Универсально для донатов, фолловеров, поддержек на любых платформах.
2) RADIO_WAIFU_NEW_FOLLOWER.mp3 — более длинная реплика для нового фолловера.
3) RADIO_WAIFU_DONATION.mp3 — благодарность за донат.
4) RADIO_WAIFU_SUPPORT_ALT.mp3 — альтернативный вариант универсальной реплики.

Используй MP3 в DonationAlerts/OBS/настроенном боте там, где возникает событие.
GIF RADIO WAIFU можно оставить текущий; звуковые файлы меняются отдельно.
Громкость начни с 45-60%, тестируй вне трансляции. Файлы с пиками -5 dBFS.
Опционально WAV для дальнейшего монтажа и обработки.

Модель Silero V5 CIS Base и V5 CIS Base NoStress опубликована под MIT:
https://github.com/snakers4/silero-models/blob/master/LICENSE_CIS
https://github.com/snakers4/silero-models#v5-cis-base-models
MIT допускает коммерческое использование, включая монетизируемый стрим.
Copyright (c) 2025-present Silero Team; полные условия лицензии — по ссылке.

Текст звуков составлен специально для RADIO SILENCE / RADIO WAIFU.
"""
(OUT/'README_RU.txt').write_text(readme,encoding='utf-8')
(OUT/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUCCESS',flush=True)
