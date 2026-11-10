import subprocess, numpy as np, json
src="work/voice.mp3"
subprocess.run(["ffmpeg","-y","-v","error","-i",src,"-ac","1","-ar","16000","work/voice16k.wav"],check=True)
raw=subprocess.run(["ffmpeg","-v","error","-i","work/voice16k.wav","-f","s16le","-"],capture_output=True,check=True).stdout
x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
sr=16000; hop=160  # 10ms
n=len(x)//hop
rms=np.sqrt((x[:n*hop].reshape(n,hop)**2).mean(1)+1e-12)
db=20*np.log10(rms)
print("dur",len(x)/sr,"pct dB",{p:round(float(np.percentile(db,p)),1) for p in (1,5,10,25,50,75,90,95,99)})
# smooth over 30ms
k=np.ones(3)/3; dbs=np.convolve(db,k,'same')
noise=np.percentile(dbs,10); peak=np.percentile(dbs,95)
thr=noise+0.35*(peak-noise)
print("noise",noise,"peak",peak,"thr",thr)
act=dbs>thr
segs=[];i=0
while i<n:
    if act[i]:
        j=i
        while j<n and act[j]: j+=1
        segs.append([i*0.01,j*0.01]); i=j
    else: i+=1
# merge gaps <0.25s
m=[]
for s in segs:
    if m and s[0]-m[-1][1]<0.25: m[-1][1]=s[1]
    else: m.append(s)
m=[s for s in m if s[1]-s[0]>=0.2]
print(len(m),"segments; dur pct",np.percentile([s[1]-s[0] for s in m],[5,50,95]))
json.dump(m,open("work/segments.json","w"))
