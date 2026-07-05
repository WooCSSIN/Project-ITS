import cv2, numpy as np, os

vt = '/backend/app/video_test/'
files = sorted(os.listdir(vt))
print("Files:", files)

configs = [
    # (output_name, filename, polygon_points)
    ('nga_tu_so',  'Ngã Tư Sở.mp4',  [[140,400],[400,200],[550,200],[530,400]]),
    ('duong_lang', 'Đường Láng.mp4', [[150,400],[300,200],[580,200],[600,400]]),
    ('van_quan',   'Văn Quán.mp4',   [[0,400],[0,200],[600,200],[600,400]]),
    ('van_phu',    'Văn Phú.mp4',    [[0,400],[0,220],[600,180],[600,400]]),
]

for name, fname, pts in configs:
    path = vt + fname
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f'CANNOT OPEN: {fname}')
        continue
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total // 4))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print(f'NO FRAME: {fname}')
        continue
    frame = cv2.resize(frame, (600, 400))
    poly = np.array(pts, np.int32).reshape((-1, 1, 2))
    cv2.polylines(frame, [poly], True, (0, 255, 255), 3)
    for p in pts:
        cv2.circle(frame, tuple(p), 8, (0, 0, 255), -1)
        cv2.putText(frame, f'{p[0]},{p[1]}', (p[0]+5, p[1]-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,0), 1)
    out = f'/tmp/poly_{name}.jpg'
    cv2.imwrite(out, frame)
    print(f'SAVED: {out}')
