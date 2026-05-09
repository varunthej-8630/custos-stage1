# risk_engine.py — CUSTOS Optimised
# Key changes from previous version:
#   - Signal weights tuned to 4 reliably detected behaviours:
#     RUNNING, ERRATIC, CROUCHING, PACING — these hit threshold solo
#   - Single-signal dampening removed for these 4 — was blocking real alerts
#   - LINGERING and FREEZE still dampened (less reliable, need corroboration)
#   - Score decay cleaned up: clear 3-state logic, no edge-case sluggishness
#   - Smoothing window reduced 3→2 frames for faster response
#   - Hysteresis window kept at 2s — prevents single-frame noise spikes

import time
from config import settings as config

# ── SIGNAL WEIGHTS ────────────────────────────────────────────
# Tuned so reliable signals can reach RISK_THRESHOLD (60) solo in OBSERVATION.
SIGNAL_WEIGHTS = {
    'running':   28,
    'erratic':   22,
    'crouching': 35,
    'pacing':    20,
    'lingering': 18,
    'frozen':    14,
    'circling':  18,
}

# These 4 count fully even when the only active signal in OBSERVATION zone
RELIABLE_SIGNALS = {'running', 'erratic', 'crouching', 'pacing'}


class RiskEngine:
    def __init__(self):
        self.score                  = 0.0
        self.last_update            = time.time()
        self.event_log              = []
        self.mode                   = 'DAY'
        self._last_activity         = time.time()
        self._raw_score_history     = []
        self._above_threshold_since = None

    def set_mode(self, mode: str):
        if mode in ('DAY', 'GUARD') and mode != self.mode:
            self.mode = mode
            print(f'[RISK] Mode → {mode}')

    def auto_check_mode(self):
        now  = time.time()
        idle = (now - self._last_activity) / 60
        if idle >= config.AUTO_GUARD_IDLE_MIN and self.mode != 'GUARD':
            self.mode = 'GUARD'
            print(f'[RISK] Auto GUARD MODE (idle {idle:.0f} min)')
            return
        hour     = time.localtime().tm_hour
        in_guard = (hour >= config.GUARD_MODE_START or hour < config.GUARD_MODE_END) \
                   if config.GUARD_MODE_START > config.GUARD_MODE_END \
                   else (config.GUARD_MODE_START <= hour < config.GUARD_MODE_END)
        sched = 'GUARD' if in_guard else 'DAY'
        if self.mode != sched:
            self.mode = sched
            print(f'[RISK] Schedule → {sched}')

    def register_activity(self):
        self._last_activity = time.time()

    def should_alert(self) -> bool:
        """Score must stay above threshold for 2 continuous seconds before alert fires."""
        now = time.time()
        if self.score >= config.RISK_THRESHOLD:
            if self._above_threshold_since is None:
                self._above_threshold_since = now
            return (now - self._above_threshold_since) >= 2.0
        else:
            self._above_threshold_since = None
            return False

    def update(self, person_events: list, zone_types: dict = None, tamper: bool = False) -> float:
        now     = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        self.event_log   = []

        if tamper:
            self.score = 100.0
            self.event_log.append('CAMERA TAMPERED!')
            return self.score

        zone_types = zone_types or {}
        anyone_in_high = any(
            e['in_zone'] and zone_types.get(e.get('zone_index', -1), '') == config.ZONE_TYPE_HIGH
            for e in person_events
        )
        anyone_in_zone = any(e['in_zone'] for e in person_events)

        if person_events:
            self.register_activity()

        prev_score = self.score
        
        # 3-state decay — fast drop when no one is in zone
        if anyone_in_high:
            decay = config.SCORE_DECAY_RATE * 0.4
        elif anyone_in_zone:
            decay = config.SCORE_DECAY_RATE * 3.5
        else:
            decay = config.SCORE_DECAY_RATE * 7.0
        self.score = max(0.0, self.score - decay * elapsed)

        delta = 0.0
        for e in person_events:
            if not e['in_zone']:
                continue

            zone_idx  = e.get('zone_index', -1)
            zone_type = zone_types.get(zone_idx, config.ZONE_TYPE_WATCH)
            dwell     = e.get('dwell_time', 0)
            pid       = e['track_id']

            # HIGH ZONE — immediate alert
            if zone_type == config.ZONE_TYPE_HIGH:
                if self.mode == 'GUARD':
                    delta += 100
                    self.event_log.append(f'[HIGH] #{pid} in zone — GUARD MODE')
                else:
                    delta += config.RISK_THRESHOLD
                    self.event_log.append(f'[HIGH] #{pid} entered restricted zone')
                continue

            # OBSERVATION ZONE — behaviour-based
            if dwell < config.WATCH_GRACE_SEC:
                continue

            active_signals = {}
            if e.get('is_running'):
                active_signals['running'] = SIGNAL_WEIGHTS['running']
                self.event_log.append(f'#{pid} RUNNING in zone')
            if e.get('is_erratic'):
                active_signals['erratic'] = SIGNAL_WEIGHTS['erratic']
                self.event_log.append(f'#{pid} erratic movement')
            if e.get('is_crouching'):
                active_signals['crouching'] = SIGNAL_WEIGHTS['crouching']
                self.event_log.append(f'#{pid} CROUCHING in zone')
            if e.get('is_pacing'):
                active_signals['pacing'] = SIGNAL_WEIGHTS['pacing']
                self.event_log.append(f'#{pid} PACING in zone')
            if e.get('is_frozen'):
                active_signals['frozen'] = SIGNAL_WEIGHTS['frozen']
                self.event_log.append(f'#{pid} froze suddenly')
            if dwell >= config.DWELL_LINGER_SEC:
                active_signals['lingering'] = SIGNAL_WEIGHTS['lingering']
                self.event_log.append(f'#{pid} lingering {dwell:.0f}s')
            visits = e.get('visit_count', 0)
            if visits >= config.VISIT_SUSPICIOUS:
                active_signals['circling'] = SIGNAL_WEIGHTS['circling']
                self.event_log.append(f'#{pid} returned {visits}x')

            if not active_signals:
                continue

            raw_delta      = sum(active_signals.values())
            reliable_count = sum(1 for s in active_signals if s in RELIABLE_SIGNALS)
            total_count    = len(active_signals)

            # Dampening: reliable signals count fully, unreliable need corroboration
            if reliable_count > 0:
                person_delta = min(raw_delta, 70)
            elif total_count >= 2:
                person_delta = min(raw_delta * 0.5, 35)
                # Don't let corroborated unreliable signals push score to 100 solo
                if self.score >= 85.0: person_delta = 0
            else:
                person_delta = min(raw_delta * 0.2, 8)
                # Unreliable solo signal (e.g. lingering) maxes out at 55 (below 60 threshold)
                if self.score >= 55.0: person_delta = 0

            delta += person_delta

        if self.mode == 'GUARD' and delta > 0:
            delta *= config.NIGHT_SCORE_MULT
            self.event_log.append(f'[GUARD ×{config.NIGHT_SCORE_MULT}]')

        raw_score = max(0.0, min(100.0, self.score + delta))

        # 2-frame smoothing. Skip on exit so score drops immediately.
        self._raw_score_history.append(raw_score)
        if len(self._raw_score_history) > 2:
            self._raw_score_history.pop(0)

        # Compare with prev_score so we bypass smoothing when score naturally drops
        if not anyone_in_high and raw_score < prev_score:
            self._raw_score_history.clear()
            self.score = raw_score
        else:
            self.score = sum(self._raw_score_history) / len(self._raw_score_history)

        return self.score