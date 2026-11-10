import sys
from faster_whisper import WhisperModel
m=WhisperModel(sys.argv[1],device="cpu",compute_type="int8")
print("ok")
