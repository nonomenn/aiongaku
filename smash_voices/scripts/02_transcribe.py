import json, numpy as np, subprocess, os, sys
idx=[int(v) for v in sys.argv[2].split(",")] if len(sys.argv)>2 and sys.argv[2][0]!="r" else None
LANG=sys.argv[3] if len(sys.argv)>3 else None
OUT=sys.argv[1]
from faster_whisper import WhisperModel
segs=json.load(open("work/segments.json"))
raw=subprocess.run(["ffmpeg","-v","error","-i","work/voice16k.wav","-f","s16le","-"],capture_output=True,check=True).stdout
x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
sr=16000
m=WhisperModel(os.environ.get("WM","large-v3"),device="cpu",compute_type="int8",cpu_threads=4)
have=set(json.loads(l)["i"] for l in open(OUT)) if os.path.exists(OUT) else set()
out=open(OUT,"a")
for i,(s,e) in enumerate(segs):
    if idx is not None and i not in idx: continue
    if i in have: continue
    a=x[int(max(0,s-0.3)*sr):int((e+0.3)*sr)]
    a=a/ (np.abs(a).max()+1e-9)*0.9
    it,info=m.transcribe(a,beam_size=1,condition_on_previous_text=False,temperature=0,language=LANG,initial_prompt=os.environ.get('PROMPT') or None)
    t="".join(q.text for q in it).strip()
    out.write(json.dumps(dict(i=i,start=s,end=e,lang=info.language,prob=round(info.language_probability,3),text=t),ensure_ascii=False)+"\n"); out.flush()
