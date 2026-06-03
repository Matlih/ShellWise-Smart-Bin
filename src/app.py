import time
import cv2
from ultralytics import YOLO

from src.config.loader import config
from src.bins.state import init as init_bins, check_full, check_lid
from src.hardware.lifecycle import connect, setup, cleanup
from src.vision.processing import get_detected_labels
from src.vision.camera import init_camera

def app(headless=None):
    model = YOLO(config["model"], task=config.get("modelTask", "detect"))
    camera = init_camera(config)
    if headless is None:
        headless = bool(config.get("headless", False))

    window_name = config.get("windowName", "Preview")

    pi = connect()
    hardware_enabled = pi is not None
    bins = config["bins"]
    bin_state = init_bins(bins)

    if hardware_enabled:
        setup(
            pi,
            bins,
            config["closedAngle"],
            config["servoMoveDelay"],
        )

    infer_n_frames = max(1, int(config.get("inferEveryNFrames", 1)))
    infer_imgsz = int(config.get("inferenceImageSize", 640))
    poll_interval = float(config.get("sensorPollInterval", 0.12))

    frame_count = 0
    last_results = None
    last_detected_labels = set()
    next_sensor_time = 0.0

    try:
        while True:
            success, frame = camera.read()
            if not success:
                print("Camera frame read failed.")
                break

            frame_count += 1
            should_infer = last_results is None or (frame_count % infer_n_frames == 0)

            if should_infer:
                last_results = model.predict(frame, verbose=False, imgsz=infer_imgsz)
                last_detected_labels = get_detected_labels(last_results, model.names, config["minConfidence"])

            now = time.monotonic()
            if hardware_enabled:
                for bin_item in bins:
                    state = bin_state[bin_item["name"]]
                    bin_context = {
                        "pi": pi,
                        "bin_item": bin_item,
                        "state": state,
                        "detected_labels": last_detected_labels,
                        "open_angle": config["openAngle"],
                        "closed_angle": config["closedAngle"],
                        "move_delay": config["servoMoveDelay"],
                        "close_delay": config.get("servoCloseDelay", 0.0),
                        "now": now,
                    }

                    if now >= next_sensor_time:
                        check_full(bin_context)

                    check_lid(bin_context)

                if now >= next_sensor_time:
                    next_sensor_time = now + poll_interval

            if not headless:
                annotated = last_results[0].plot() if (should_infer and last_results) else frame
                cv2.imshow(window_name, annotated)

                key = cv2.waitKey(1)
                if key == 27:
                    break
                
                try:
                    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except cv2.error:
                    pass

    except KeyboardInterrupt:
        print("Program stopped by user.")

    finally:
        camera.release()
        if not headless:
            cv2.destroyAllWindows()
        if hardware_enabled:
            cleanup(pi, bins)
