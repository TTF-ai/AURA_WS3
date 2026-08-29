from insightface.app import FaceAnalysis
import cv2

app = FaceAnalysis(name="buffalo_s")

app.prepare(ctx_id=0)

cap = cv2.VideoCapture(0)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

frame_count = 0

while True:

    ret, frame = cap.read()

    faces = app.get(frame)

    print("Faces:", len(faces))

    for face in faces:

        box = face.bbox.astype(int)

        cv2.rectangle(
            frame,
            (box[0], box[1]),
            (box[2], box[3]),
            (0,255,0),
            2
        )
    
    # frame_count += 1
    
    # if frame_count % 3 != 0:
    # 	continue

    cv2.imshow("Detector", frame)

    if cv2.waitKey(1)==27:
        break
