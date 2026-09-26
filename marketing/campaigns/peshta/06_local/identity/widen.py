import cv2,numpy as np,os,glob,itertools,json,subprocess,sys
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
from face2 import best_face
M="/Users/ai/Desktop/work/projects/hbd-bot/promo_peshta/final_polat_peshta_reel.mp4"
det=cv2.FaceDetectorYN.create(os.path.join(HERE,"yunet.onnx"),"",(320,320),score_threshold=0.5)
rec=cv2.FaceRecognizerSF.create(os.path.join(HERE,"sface.onnx"),"")
cuts=[float(x) for x in open(os.path.join(HERE,"cuts.txt")) if x.strip()]
b=[0.0]+cuts+[43.0]
shots=[(b[i],b[i+1],b[i+1]-b[i]) for i in range(len(b)-1) if b[i+1]-b[i]>=0.6]
print(f"shots >=0.6s: {len(shots)}  (was 10 at >=1.0s taking only the longest)")
out=[]
od=os.path.join(HERE,"wide"); os.makedirs(od,exist_ok=True)
for t0,t1,d in shots:
    tag=f"w{t0:07.2f}".replace(".","_")
    for o in glob.glob(os.path.join(od,tag+"_*.png")): os.remove(o)
    subprocess.run(["ffmpeg","-loglevel","error","-ss",f"{t0+0.03:.3f}","-to",f"{t1-0.03:.3f}","-i",M,
                    "-vf","fps=12",os.path.join(od,tag+"_%03d.png"),"-y"],check=True)
    ps=sorted(glob.glob(os.path.join(od,tag+"_*.png")))
    feats=[];nm=0
    for p in ps:
        im=cv2.imread(p)
        if im is None: continue
        box,how,nf=best_face(im,det)
        if box is None: continue
        feats.append(rec.feature(rec.alignCrop(im,box)))
        if nf>1: nm+=1
    if len(feats)<2: continue
    vals=[rec.match(feats[i],feats[j],cv2.FaceRecognizerSF_FR_COSINE) for i,j in itertools.combinations(range(len(feats)),2)]
    out.append({"t0":round(t0,2),"t1":round(t1,2),"dur":round(d,2),"faces":len(feats),
                "pairs":len(vals),"multi_pct":round(100*nm/len(feats),1),"mean":round(float(np.mean(vals)),4)})
single=[r for r in out if r["multi_pct"]<20]
print(f"\nshots with >=2 faces detected: {len(out)}   single-subject (<20% multi): {len(single)}")
print(f"{'window':>16} {'dur':>5} {'faces':>6} {'pairs':>6} {'multi%':>7} {'mean':>7}")
for r in sorted(single,key=lambda r:r['t0']):
    print(f"{r['t0']:7.2f}-{r['t1']:6.2f} {r['dur']:5.2f} {r['faces']:6d} {r['pairs']:6d} {r['multi_pct']:6.0f}% {r['mean']:7.3f}")
if single:
    ms=[r["mean"] for r in single]; tp=sum(r["pairs"] for r in single)
    print(f"\nSINGLE-SUBJECT NOISE FLOOR: n={len(single)} shots, {tp} pairs")
    print(f"  means: {', '.join(f'{v:.3f}' for v in sorted(ms))}")
    print(f"  mean={np.mean(ms):.3f}  min={min(ms):.3f}  median={np.median(ms):.3f}")
    print(f"  => THRESHOLD ~{min(ms):.2f} (use the MIN, not the mean: a keyframe set scoring")
    print(f"     below the weakest genuine continuous shot is drifting for sure.)")
json.dump({"all":out,"single":single},open(os.path.join(HERE,"widened_floor.json"),"w"),indent=1)
