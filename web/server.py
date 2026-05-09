# web_server.py — CUSTOS Optimised
# Fixes: no bboxes on stream, auto-resolve, deduped _iou, env credentials, alert history immediate
import cv2, time, os, threading, collections
from config import settings as config
# Suppress OpenCV's verbose MSMF/DSHOW warning spam in the terminal
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
from flask import Flask, Response, render_template_string, jsonify, session, redirect, request
from flask_socketio import SocketIO
from engine.detector import ObjectDetector
from engine.tracker import PersonTracker
from engine.zone_monitor import ZoneMonitor
from engine.risk_engine import RiskEngine
from web.alert_manager import AlertManager
from engine.utils import iou
from authlib.integrations.flask_client import OAuth

app = Flask(__name__)
app.secret_key = os.getenv('CUSTOS_SECRET', 'custos_dev_secret_change_me')
socket = SocketIO(app, cors_allowed_origins='*', async_mode='threading',
                  ping_timeout=20, ping_interval=10)
ADMIN_USER = os.getenv('CUSTOS_USER', 'admin')
ADMIN_PASS = os.getenv('CUSTOS_PASS', 'Varunthej@8630')

# Google OAuth Setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

state = {
    'score': 0.0, 'mode': 'DAY', 'persons': 0, 'in_zone': 0,
    'alert_active': False, 'alert_resolved': False, 'tamper': False,
    'fps': 0.0, 'event_log': [], 'alerts': [], 'uptime_start': time.time(),
    'cam_w': 640, 'cam_h': 480,
}
state_lock = threading.Lock()
latest_frame = None
latest_frame_lock = threading.Lock()
pending_zones = None
pending_zones_lock = threading.Lock()
alert_history = collections.deque(maxlen=50)

def save_pretamper_clip(buffer, fps=20):
    os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)
    if not buffer: return None
    ts=time.strftime('%Y%m%d_%H%M%S'); fname=f'pretamper_{ts}.mp4'
    path=os.path.join(config.SNAPSHOT_DIR, fname); h,w=buffer[0].shape[:2]
    writer=cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'avc1'), fps, (w,h))
    for f in buffer: writer.write(f)
    writer.release(); print(f'[TAMPER] Clip: {path}')
    return path, fname

class DetectionThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running=True; self.zones=[]; self.zone_types=[]; self.monitoring=False
        self.cap=None; self._last_alert_logged=False; self._alert_was_active=False

    def run(self):
        global latest_frame

        def open_camera(source):
            """
            Try DSHOW backend first (Windows) — avoids MSMF grabFrame spam.
            Falls back to default backend if DSHOW fails (Linux/Mac compatible).
            """
            import platform
            if platform.system() == 'Windows':
                cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        print(f'[CAM] Opened with DSHOW backend')
                        return cap
                    cap.release()
                print('[CAM] DSHOW failed, trying default backend...')
            cap = cv2.VideoCapture(source)
            return cap

        self.cap = open_camera(config.CAMERA_SOURCE)
        if not self.cap.isOpened(): print('[CAM] ERROR — cannot open camera'); return
        print('[CAM] Ready')
        for _ in range(config.CAMERA_WARMUP_FRAMES): self.cap.read()
        # Capture real frame size so browser can map zones correctly
        ret_dim, dim_frame = self.cap.read()
        if ret_dim:
            h_cam, w_cam = dim_frame.shape[:2]
            with state_lock:
                state['cam_w'] = w_cam
                state['cam_h'] = h_cam
            print(f'[CAM] Frame size: {w_cam}x{h_cam}')
        detector=ObjectDetector(); tracker=PersonTracker(); monitor=ZoneMonitor()
        risk=RiskEngine(); alerts=AlertManager()
        pretamper_buf=collections.deque(maxlen=int(config.TAMPER_BUFFER_SEC*20))
        tamper_active=False; frame_count=0; last_dets=[]; fps_timer=time.time(); fps=0; ref_set=False

        _fail_count = 0
        while self.running:
            ret, frame=self.cap.read()
            if not ret:
                _fail_count += 1
                time.sleep(0.1)
                # After 30 consecutive failures (~3s) — camera died or was stolen
                # Release and reopen rather than spinning forever
                if _fail_count >= 30:
                    print(f'[CAM] Feed lost — reopening...')
                    self.cap.release()
                    time.sleep(1.0)
                    self.cap = open_camera(config.CAMERA_SOURCE)
                    _fail_count = 0
                continue
            _fail_count = 0
            frame_count+=1; pretamper_buf.append(frame.copy())
            if frame_count%30==0:
                fps=30/max(time.time()-fps_timer,0.01); fps_timer=time.time()

            global pending_zones
            with pending_zones_lock:
                if pending_zones is not None:
                    self.zones=pending_zones['zones']; self.zone_types=pending_zones['types']
                    self.monitoring=pending_zones['monitoring']; pending_zones=None
                    if self.zones and not ref_set:
                        monitor.set_reference(frame, self.zones); ref_set=True
                    print(f'[CAM] {len(self.zones)} zone(s) monitoring={self.monitoring}')

            # Clean feed — zones only, NO person bounding boxes
            display=frame.copy()
            for i,z in enumerate(self.zones):
                x1,y1,x2,y2=z
                is_high=i<len(self.zone_types) and self.zone_types[i]==config.ZONE_TYPE_HIGH
                col=(40,40,220) if is_high else (40,180,80)
                ov=display.copy(); cv2.rectangle(ov,(x1,y1),(x2,y2),col,-1)
                cv2.addWeighted(ov,0.12,display,0.88,0,display)
                cv2.rectangle(display,(x1,y1),(x2,y2),col,2)
                L=14
                for (ex,ey,dx,dy) in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
                    cv2.line(display,(ex,ey),(ex+dx*L,ey),col,3)
                    cv2.line(display,(ex,ey),(ex,ey+dy*L),col,3)
                lbl='HIGH SEC' if is_high else 'OBSERVATION'
                cv2.putText(display,f'Z{i+1} {lbl}',(x1+8,y1+18),cv2.FONT_HERSHEY_DUPLEX,0.45,col,1,cv2.LINE_AA)

            person_events=[]; any_tamper=False
            if self.monitoring and self.zones:
                if frame_count%config.FRAME_SKIP==0: last_dets=detector.detect(frame)
                tracked=tracker.update(last_dets)
                for p in tracked:
                    in_zone=False; zone_idx=-1
                    for i,zone in enumerate(self.zones):
                        if iou(p['box'],zone)>config.TOUCH_IOU_THRESHOLD:
                            in_zone=True; zone_idx=i; break
                    tracker.update_zone_state(p['track_id'],in_zone)
                    t_data=tracker.tracks.get(p['track_id'],{})
                    person_events.append({'track_id':p['track_id'],'in_zone':in_zone,'zone_index':zone_idx,
                        'dwell_time':t_data.get('zone_total_time',0),'visit_count':p['visit_count'],
                        'is_crouching':p['is_crouching'],'is_pacing':p['is_pacing'],'is_frozen':p['is_frozen'],
                        'is_erratic':p['is_erratic'],'is_running':p['is_running'],'movement':p['movement']})

                occupied={e['zone_index'] for e in person_events if e['in_zone']}
                tamper_results=monitor.update(frame,self.zones,occupied_zones=occupied)
                any_tamper=any(v['occluded'] for v in tamper_results.values())
                if any_tamper and not tamper_active:
                    tamper_active=True; clip_ts=time.strftime('%H:%M:%S')
                    res=save_pretamper_clip(list(pretamper_buf))
                    clip_path,clip_name=res if res else (None,None)
                    alerts.send_tamper_alert(pre_tamper_clip_path=clip_path)
                    alert_history.appendleft({'time':clip_ts,'score':100,'events':['CAMERA TAMPERED!'],
                        'zone':-1,'snapshot':'','clip':clip_name or '','resolved':False})
                    socket.emit('tamper',{'time':clip_ts,'clip':clip_name or ''})
                elif not any_tamper: tamper_active=False

                if frame_count%60==0: risk.auto_check_mode()
                zone_type_map={i:self.zone_types[i] for i in range(len(self.zone_types))}
                score=risk.update(person_events,zone_types=zone_type_map,tamper=any_tamper)
                alerts.check_and_send(frame,score,risk)

                alert_fired=risk.should_alert()
                if alert_fired and not self._last_alert_logged:
                    self._last_alert_logged=True; self._alert_was_active=True
                    snap_file=''
                    if os.path.exists(config.SNAPSHOT_DIR):
                        snaps=sorted([f for f in os.listdir(config.SNAPSHOT_DIR) if f.startswith('alert_') and f.endswith('.jpg')])
                        if snaps: snap_file=snaps[-1]
                    alert_history.appendleft({'time':time.strftime('%H:%M:%S'),'score':round(score),
                        'events':list(risk.event_log),'zone':self._dominant_zone(person_events),
                        'snapshot':snap_file,'clip':'','resolved':False})
                elif not alert_fired:
                    self._last_alert_logged=False
                    if self._alert_was_active:
                        self._alert_was_active=False
                        for entry in alert_history:
                            if not entry.get('resolved'): entry['resolved']=True; break
                        socket.emit('alert_resolved',{})

                h_f,w_f=display.shape[:2]
                sc_col=(80,255,100) if score<40 else (0,200,255) if score<70 else (50,50,255)
                fill=int(w_f*score/100)
                cv2.rectangle(display,(0,h_f-4),(w_f,h_f),(20,20,20),-1)
                cv2.rectangle(display,(0,h_f-4),(fill,h_f),sc_col,-1)
                with state_lock:
                    state['score']=round(score,1); state['mode']=risk.mode; state['persons']=len(tracked)
                    state['in_zone']=sum(1 for e in person_events if e['in_zone'])
                    state['alert_active']=alert_fired
                    state['alert_resolved']=not alert_fired and any(a.get('resolved') for a in alert_history)
                    state['tamper']=any_tamper; state['fps']=round(fps,1)
                    state['event_log']=list(risk.event_log); state['alerts']=list(alert_history)
            else:
                with state_lock:
                    state['score']=0.0; state['alert_active']=False; state['fps']=round(fps,1); state['persons']=0

            _,jpeg=cv2.imencode('.jpg',display,[cv2.IMWRITE_JPEG_QUALITY,72])
            with latest_frame_lock: latest_frame=jpeg.tobytes()
            # Always emit — every 6 frames (~5x/sec at 30fps) regardless of monitoring state
            # This ensures the browser always has a live connection signal
            if frame_count%6==0:
                with state_lock: s=dict(state)
                socket.emit('risk_update',{k:s[k] for k in
                    ['score','mode','persons','in_zone','alert_active','alert_resolved','tamper','fps','event_log','alerts','cam_w','cam_h']})
        self.cap.release()

    def _dominant_zone(self,person_events):
        for e in person_events:
            if e['in_zone'] and e['zone_index']>=0: return e['zone_index']
        return -1

    def stop(self):
        self.running=False
        if self.cap: self.cap.release()

    def switch_camera(self,index):
        if self.cap: self.cap.release()
        import platform
        if platform.system()=='Windows':
            self.cap=cv2.VideoCapture(index,cv2.CAP_DSHOW)
            if not self.cap.isOpened(): self.cap=cv2.VideoCapture(index)
        else:
            self.cap=cv2.VideoCapture(index)
        if not self.cap.isOpened():
            print(f'[CAM] Switch failed, falling back to index 0')
            self.cap=cv2.VideoCapture(0,cv2.CAP_DSHOW)

_detection_thread=None
def get_detection_thread():
    global _detection_thread
    if _detection_thread is None or not _detection_thread.is_alive():
        _detection_thread=DetectionThread(); _detection_thread.start()
    return _detection_thread

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        if request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASS:
            session['logged_in']=True
            session['user_name'] = 'Admin'
            return redirect('/')
        return render_template_string(LOGIN_HTML,error='Invalid credentials')
    return render_template_string(LOGIN_HTML,error='')

@app.route('/login/google')
def login_google():
    redirect_uri = request.url_root.rstrip('/') + '/auth/callback'
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if user_info:
            session['logged_in'] = True
            session['user_email'] = user_info.get('email')
            session['user_name'] = user_info.get('name')
            print(f"[AUTH] Google Login Successful: {user_info.get('email')}")
        return redirect('/')
    except Exception as e:
        print(f"[AUTH] Error: {e}")
        return render_template_string(LOGIN_HTML, error='Google Sign-In failed.')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect('/login')
    p=os.path.join(os.path.dirname(os.path.dirname(__file__)),'frontend','index.html')
    with open(p,'r',encoding='utf-8') as f: return f.read()

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with latest_frame_lock: frame=latest_frame
            if frame: yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+frame+b'\r\n'
            time.sleep(0.033)
    return Response(generate(),mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/state')
def get_state():
    with state_lock: s=dict(state)
    s['uptime']=int(time.time()-s['uptime_start']); return jsonify(s)

@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    from flask import send_from_directory
    d=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),config.SNAPSHOT_DIR)
    return send_from_directory(d,filename,conditional=True)

@app.route('/ping')
def ping():
    return jsonify({'status': 'ok', 'ts': time.time()})

@app.route('/list_evidence')
def list_evidence():
    d=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),config.SNAPSHOT_DIR)
    files=[]
    if os.path.exists(d):
        for f in sorted(os.listdir(d),reverse=True):
            if f.endswith(('.jpg','.mp4')): files.append({'name':f})
    return jsonify({'files':files})

@app.route('/list_cameras')
def list_cameras():
    import platform
    cameras=[]
    for i in range(5):
        backend = cv2.CAP_DSHOW if platform.system()=='Windows' else cv2.CAP_ANY
        cap=cv2.VideoCapture(i, backend)
        if cap.isOpened():
            ret,_=cap.read()
            if ret:
                cameras.append({'index':i,'name':'Built-in Camera' if i==0 else f'External Camera {i}',
                    'sub':f'{"Laptop" if i==0 else "USB"}  ·  Index {i}','icon':'💻' if i==0 else '📷'})
            cap.release()
    return jsonify({'cameras':cameras})

@app.route('/recordings/<path:filename>')
def serve_recording(filename):
    from flask import send_from_directory
    d=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),config.RECORDING_DIR)
    return send_from_directory(d,filename)

@socket.on('connect')
def on_connect(): get_detection_thread()

@socket.on('set_zones')
def on_set_zones(data):
    global pending_zones
    with pending_zones_lock:
        pending_zones={'zones':data.get('zones',[]),'types':data.get('types',[]),'monitoring':data.get('monitoring',False)}

@socket.on('set_camera')
def on_set_camera(data): get_detection_thread().switch_camera(data.get('index',0))

LOGIN_HTML='''<!DOCTYPE html><html><head><title>CUSTOS</title>
<style>*{margin:0;padding:0;box-sizing:border-box;}body{background:#09090c;display:flex;align-items:center;justify-content:center;height:100vh;font-family:'Times New Roman',serif;}
.box{background:#111116;border:1px solid #1f1f28;border-radius:8px;padding:40px;width:340px;}
h2{color:#f4f4f8;font-size:18px;margin-bottom:6px;}p{color:#6b6b7a;font-size:12px;margin-bottom:24px;}
label{display:block;color:#9494a8;font-size:11px;margin-bottom:6px;}
input{width:100%;background:#16161d;border:1px solid #27272f;border-radius:6px;padding:10px 12px;color:#e8e8f0;font-size:13px;margin-bottom:16px;outline:none;}
input:focus{border-color:#3b82f6;}button{width:100%;background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:11px;font-size:13px;cursor:pointer;}
button:hover{background:#2563eb;}.err{color:#ef4444;font-size:11px;margin-bottom:14px;}
.google-btn{background:#db4437;margin-top:4px;text-align:center;text-decoration:none;display:block;color:#fff;border-radius:6px;padding:11px;font-size:13px;cursor:pointer;}
.google-btn:hover{background:#c53929;}
.divider{text-align:center;color:#6b6b7a;font-size:11px;margin:20px 0;}
</style>
</head><body><div class="box"><h2>CUSTOS</h2><p>Asset Interaction Anomaly Detection</p>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST"><label>Username</label><input type="text" name="username" autofocus>
<label>Password</label><input type="password" name="password"><button type="submit">Login</button></form>
<div class="divider">─────── OR ───────</div>
<a href="/login/google" class="google-btn">Sign in with Google</a>
</div></body></html>'''

def start(host='0.0.0.0',port=5000,debug=False):
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend'),exist_ok=True); get_detection_thread()
    print(f'[SERVER] CUSTOS at http://localhost:{port}')
    print('[TUNNEL] Share: cloudflared tunnel --url http://localhost:5000')
    socket.run(app,host=host,port=port,debug=debug,use_reloader=False,allow_unsafe_werkzeug=True)

if __name__=='__main__': start()