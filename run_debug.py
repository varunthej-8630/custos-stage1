# main.py — CUSTOS standalone debug entry point
# Use this for local testing WITHOUT the web dashboard.
# For production / demos: use web_server.py instead.

import cv2, time, os, collections, threading, queue
from config import settings as config
from engine.detector      import ObjectDetector
from engine.tracker       import PersonTracker
from engine.zone_selector import ZoneSelector
from engine.zone_monitor  import ZoneMonitor
from engine.risk_engine   import RiskEngine
from web.alert_manager import AlertManager
from engine.utils         import iou


# ── RECORDING THREAD ──────────────────────────────────────────
class RecordingThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.frame_queue = queue.Queue(maxsize=60)
        self.writer      = None
        self.rec_path    = None
        self.rec_start   = None
        self.running     = True
        self._lock       = threading.Lock()

    def run(self):
        while self.running:
            try:
                frame = self.frame_queue.get(timeout=1)
                with self._lock:
                    if self.writer:
                        self.writer.write(frame)
                        if time.time() - self.rec_start >= config.RECORDING_CHUNK_MIN * 60:
                            self.writer.release()
                            self.writer   = None
                            self.rec_path = None
            except queue.Empty:
                continue
            except Exception as e:
                print(f'[REC] Error: {e}')

    def start_recording(self, frame):
        os.makedirs(config.RECORDING_DIR, exist_ok=True)
        ts   = time.strftime('%Y%m%d_%H%M%S')
        path = f'{config.RECORDING_DIR}/rec_{ts}.mp4'
        h, w = frame.shape[:2]
        with self._lock:
            self.writer    = cv2.VideoWriter(
                path, cv2.VideoWriter_fourcc(*'mp4v'), 20, (w, h))
            self.rec_path  = path
            self.rec_start = time.time()
        print(f'[REC] Recording started: {path}')

    def write(self, frame):
        try:
            self.frame_queue.put_nowait(frame.copy())
        except queue.Full:
            pass

    def stop(self):
        self.running = False
        with self._lock:
            if self.writer:
                self.writer.release()
                self.writer = None


# ── HELPERS ───────────────────────────────────────────────────
def cleanup_old_recordings():
    if not os.path.exists(config.RECORDING_DIR):
        return
    cutoff = time.time() - config.RECORDING_KEEP_HOURS * 3600
    for f in os.listdir(config.RECORDING_DIR):
        fpath = os.path.join(config.RECORDING_DIR, f)
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
            os.remove(fpath)
            print(f'[REC] Deleted old: {f}')


def save_pretamper_clip(buffer, fps=20):
    """Save rolling pre-tamper buffer to disk. Returns path or None."""
    os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)
    if not buffer:
        return None
    ts     = time.strftime('%Y%m%d_%H%M%S')
    path   = os.path.join(config.SNAPSHOT_DIR, f'pretamper_{ts}.mp4')
    h, w   = buffer[0].shape[:2]
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    for f in buffer:
        writer.write(f)
    writer.release()
    print(f'[TAMPER] Pre-tamper clip: {path}')
    return path


# ── MAIN ──────────────────────────────────────────────────────
def main():
    print('=' * 55)
    print('   CUSTOS — standalone debug mode')
    print('   For demos use: python web_server.py')
    print('=' * 55)

    print(f'[CAMERA] Opening: {config.CAMERA_SOURCE}')
    cap = cv2.VideoCapture(config.CAMERA_SOURCE)
    if not cap.isOpened():
        print('[ERROR] Cannot open camera. Check CAMERA_SOURCE in config.py')
        return
    print('[CAMERA] Connected!')

    print(f'[CAMERA] Warming up ({config.CAMERA_WARMUP_FRAMES} frames)...')
    for _ in range(config.CAMERA_WARMUP_FRAMES):
        cap.read()

    print('[ZONES] Draw your protection zones...')
    selector          = ZoneSelector()
    zones, zone_types = selector.select_zones(cap)

    if len(zones) == 0:
        print('[WARNING] No zones drawn — guarding entire frame.')
        ret, first_frame = cap.read()
        if ret:
            h, w   = first_frame.shape[:2]
            zones  = [[0, 0, w, h]]
            zone_types = [config.ZONE_TYPE_WATCH]
            selector.zones      = zones
            selector.zone_types = zone_types

    detector = ObjectDetector()
    tracker  = PersonTracker()
    monitor  = ZoneMonitor()
    risk     = RiskEngine()
    alerts   = AlertManager()

    ret, ref_frame = cap.read()
    if ret:
        monitor.set_reference(ref_frame, zones)

    rec_thread = None
    if config.RECORDING_ENABLED:
        rec_thread = RecordingThread()
        rec_thread.start()
        ret, init_frame = cap.read()
        if ret:
            rec_thread.start_recording(init_frame)
        cleanup_old_recordings()

    buffer_maxlen = int(config.TAMPER_BUFFER_SEC * 20)
    pretamper_buf = collections.deque(maxlen=buffer_maxlen)
    tamper_active = False

    print('[SYSTEM] Guard is ACTIVE.')
    print('  Keys:  Q=quit   G=Guard mode   D=Day mode')
    print('-' * 55)

    frame_count = 0
    last_dets   = []
    fps_timer   = time.time()
    fps         = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print('[CAMERA] Signal lost — reconnecting...')
            time.sleep(2)
            cap.release()
            cap = cv2.VideoCapture(config.CAMERA_SOURCE)
            continue

        frame_count += 1
        pretamper_buf.append(frame.copy())

        if rec_thread:
            rec_thread.write(frame)

        if frame_count % 30 == 0:
            fps       = 30 / max(time.time() - fps_timer, 0.01)
            fps_timer = time.time()

        if frame_count % config.FRAME_SKIP == 0:
            last_dets = detector.detect(frame)
        dets = last_dets

        tracked = tracker.update(dets)

        # ── Zone analysis — using IoU (works for all zone heights) ──
        person_events = []
        for p in tracked:
            in_zone, matched_zone, zone_idx = selector.is_inside_any_zone(p['box'])
            tracker.update_zone_state(p['track_id'], in_zone)
            t_data = tracker.tracks.get(p['track_id'], {})

            person_events.append({
                'track_id':     p['track_id'],
                'in_zone':      in_zone,
                'zone_index':   zone_idx,
                'dwell_time':   t_data.get('zone_total_time', 0),
                'visit_count':  p['visit_count'],
                'is_crouching': p['is_crouching'],
                'is_pacing':    p['is_pacing'],
                'is_frozen':    p['is_frozen'],
                'is_erratic':   p['is_erratic'],
                'is_running':   p['is_running'],
                'movement':     p['movement'],
            })

        # ── Debug print every 3 seconds ───────────────────────
        # Remove this block once you confirm alerts are working
        if frame_count % 90 == 0:
            in_zone_count = sum(1 for e in person_events if e['in_zone'])
            print(f'[DEBUG] Score={risk.score:.1f}  '
                  f'Persons={len(tracked)}  '
                  f'InZone={in_zone_count}  '
                  f'Mode={risk.mode}')
            if risk.event_log:
                print(f'[DEBUG] Events: {risk.event_log}')

        occupied = {e['zone_index'] for e in person_events if e['in_zone']}
        tamper_results = monitor.update(frame, zones, occupied_zones=occupied)
        any_tamper     = any(v['occluded'] for v in tamper_results.values())

        if any_tamper and not tamper_active:
            tamper_active = True
            clip_path = save_pretamper_clip(list(pretamper_buf))
            alerts.send_tamper_alert(pre_tamper_clip_path=clip_path)
        elif not any_tamper:
            tamper_active = False

        if frame_count % 60 == 0:
            risk.auto_check_mode()

        zone_type_map = {i: zone_types[i] for i in range(len(zone_types))}
        score = risk.update(person_events, zone_types=zone_type_map, tamper=any_tamper)

        if frame_count % 150 == 0:
            print(f'[STATUS] FPS={fps:.1f}  Score={score:.0f}  '
                  f'Persons={len(tracked)}  Mode={risk.mode}  Zones={len(zones)}')

        alerts.check_and_send(frame, score, risk)

        # ── Draw overlay ──────────────────────────────────────
        if config.SHOW_PREVIEW:
            display = frame.copy()
            h_f, w_f = display.shape[:2]
            FD = cv2.FONT_HERSHEY_DUPLEX
            FS = cv2.FONT_HERSHEY_SIMPLEX

            for i, z in enumerate(zones):
                x1, y1, x2, y2 = z
                z_type  = zone_types[i] if i < len(zone_types) else config.ZONE_TYPE_WATCH
                is_high = z_type == config.ZONE_TYPE_HIGH
                col     = (40, 40, 255) if is_high else (40, 220, 120)

                ov = display.copy()
                cv2.rectangle(ov, (x1, y1), (x2, y2), col, -1)
                cv2.addWeighted(ov, 0.08, display, 0.92, 0, display)
                cv2.rectangle(display, (x1, y1), (x2, y2), col, 2)

                L = 18
                for (cx2, cy2, dx, dy) in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
                    cv2.line(display, (cx2, cy2), (cx2 + dx*L, cy2), col, 3)
                    cv2.line(display, (cx2, cy2), (cx2, cy2 + dy*L), col, 3)

                z_label = 'HIGH SEC' if is_high else 'OBSERVATION'
                badge = f"  {z_label}  ZONE {i+1}  "
                (bw, bh), _ = cv2.getTextSize(badge, FD, 0.5, 1)
                cv2.rectangle(display, (x1, y1), (x1 + bw + 4, y1 + bh + 10), col, -1)
                cv2.putText(display, badge, (x1 + 2, y1 + bh + 4), FD, 0.5, (0,0,0), 1, cv2.LINE_AA)

            for p in tracked:
                x1, y1, x2, y2 = p['box']
                in_z, _, zone_i = selector.is_inside_any_zone(p['box'])
                t_data = tracker.tracks.get(p['track_id'], {})
                dwell  = t_data.get('zone_total_time', 0)
                visits = p['visit_count']

                if p['is_crouching']:
                    col = (0, 130, 255)
                elif in_z:
                    zt  = zone_types[zone_i] if 0 <= zone_i < len(zone_types) else config.ZONE_TYPE_WATCH
                    col = (40, 40, 255) if zt == config.ZONE_TYPE_HIGH else (0, 200, 255)
                else:
                    col = (160, 255, 160)

                cv2.rectangle(display, (x1, y1), (x2, y2), col, 2)

                status = 'CROUCH' if p['is_crouching'] else (f'{dwell:.0f}s' if in_z else 'OK')
                info   = f" #{p['track_id']}  {status}  v:{visits} "
                (iw, ih), _ = cv2.getTextSize(info, FD, 0.45, 1)
                iy = max(y1 - ih - 8, 0)
                cv2.rectangle(display, (x1, iy), (x1 + iw + 4, iy + ih + 8), col, -1)
                cv2.putText(display, info, (x1 + 2, iy + ih + 2), FD, 0.45, (0,0,0), 1, cv2.LINE_AA)

            ov2 = display.copy()
            cv2.rectangle(ov2, (0, 0), (220, 52), (0, 0, 0), -1)
            cv2.addWeighted(ov2, 0.6, display, 0.4, 0, display)
            ts_str = time.strftime('%H:%M:%S')
            cv2.putText(display, ts_str, (12, 26), FD, 0.75, (200, 220, 255), 1, cv2.LINE_AA)
            cv2.putText(display, f'{fps:.0f} FPS', (130, 26), FS, 0.52, (120,120,120), 1, cv2.LINE_AA)
            cv2.putText(display, f'{len(tracked)} person(s)', (12, 46), FS, 0.42, (120,120,120), 1, cv2.LINE_AA)

            panel_w, panel_h = 220, 100
            px = w_f - panel_w - 8
            ov3 = display.copy()
            cv2.rectangle(ov3, (px, 8), (w_f - 8, 8 + panel_h), (0,0,0), -1)
            cv2.addWeighted(ov3, 0.7, display, 0.3, 0, display)
            cv2.rectangle(display, (px, 8), (w_f - 8, 8 + panel_h), (50,50,50), 1)

            sc = (80,255,100) if score<40 else (0,200,255) if score<70 else (50,50,255)
            bar_x1, bar_y1 = px + 10, 70
            bar_x2, bar_y2 = w_f - 18, 88
            cv2.rectangle(display, (bar_x1, bar_y1), (bar_x2, bar_y2), (40,40,40), -1)
            fill_x = int(bar_x1 + (bar_x2 - bar_x1) * score / 100)
            cv2.rectangle(display, (bar_x1, bar_y1), (fill_x, bar_y2), sc, -1)
            cv2.putText(display, 'RISK', (px + 12, 36), FD, 0.55, (180,180,180), 1, cv2.LINE_AA)
            cv2.putText(display, f'{score:.0f}', (px + 68, 62), FD, 1.5, sc, 2, cv2.LINE_AA)
            cv2.putText(display, '/100', (px + 152, 60), FS, 0.5, (120,120,120), 1, cv2.LINE_AA)

            mode_col = (80,255,100) if risk.mode == 'DAY' else (50,50,255)
            mode_lbl = f" {risk.mode} MODE "
            (mw, mh), _ = cv2.getTextSize(mode_lbl, FD, 0.48, 1)
            cv2.rectangle(display, (px + 10, 92), (px + 10 + mw + 4, 92 + mh + 8), mode_col, -1)
            cv2.putText(display, mode_lbl, (px + 12, 92 + mh + 2), FD, 0.48, (0,0,0), 1, cv2.LINE_AA)

            if any_tamper:
                ov4 = display.copy()
                cv2.rectangle(ov4, (0,0), (w_f, h_f), (0,0,180), -1)
                cv2.addWeighted(ov4, 0.25, display, 0.75, 0, display)
                cv2.rectangle(display, (0,0), (w_f, h_f), (0,0,255), 6)
                (tw,th), _ = cv2.getTextSize('! CAMERA TAMPERED !', FD, 1.4, 2)
                cv2.putText(display, '! CAMERA TAMPERED !',
                            ((w_f-tw)//2, h_f//2), FD, 1.4, (0,0,255), 2, cv2.LINE_AA)

            if risk.should_alert():
                cv2.rectangle(display, (0,0), (w_f, h_f), (0,0,200), 4)

            hint = "  Q quit    G guard mode    D day mode  "
            (hw, hh), _ = cv2.getTextSize(hint, FS, 0.4, 1)
            ov5 = display.copy()
            cv2.rectangle(ov5, (0, h_f - hh - 14), (w_f, h_f), (0,0,0), -1)
            cv2.addWeighted(ov5, 0.55, display, 0.45, 0, display)
            cv2.putText(display, hint, (10, h_f - 6), FS, 0.4, (100,100,100), 1, cv2.LINE_AA)

            cv2.namedWindow('SmartGuard', cv2.WINDOW_NORMAL)
            cv2.setWindowProperty('SmartGuard', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.imshow('SmartGuard', display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == ord('Q'):
                print('[SYSTEM] Quitting...')
                break
            elif key == ord('g') or key == ord('G'):
                risk.set_mode('GUARD')
                print('[SYSTEM] Manual: GUARD MODE')
            elif key == ord('d') or key == ord('D'):
                risk.set_mode('DAY')
                print('[SYSTEM] Manual: DAY MODE')

    cap.release()
    if rec_thread:
        rec_thread.stop()
    cv2.destroyAllWindows()
    print('[SYSTEM] Waiting for pending Telegram sends...')
    alerts.shutdown()
    print('[SYSTEM] Smart Guard stopped.')


if __name__ == '__main__':
    main()