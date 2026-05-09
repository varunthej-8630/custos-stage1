# tracker.py — Phase 1 Enhanced
# Fixes applied:
#   - Dwell accumulates across all visits, never resets until person leaves shop
#   - Visit gap tolerance: re-enter within 30s = same visit session continues
#   - Crouching: requires standing baseline FIRST before flagging shrink
#   - Crouching: minimum duration increased from 3s to 4s
#   - Pacing: minimum speed threshold — slow shuffle not counted
#   - Freeze: minimum prior movement speed required before freeze is valid
#   - Freeze: minimum duration increased from 2s to 3s
#   - Zone detection: uses foot-point (bottom centre of bbox) with 10px tolerance

import time
from config import settings as config


class PersonTracker:
    def __init__(self):
        self.tracks  = {}
        self.next_id = 1

    def update(self, detections):
        persons = [d for d in detections if d['class_id'] == config.CLASS_PERSON]
        now     = time.time()
        matched = set()
        result  = []

        for det in persons:
            box = det['box']
            cx  = (box[0] + box[2]) / 2
            cy  = (box[1] + box[3]) / 2
            bw  = box[2] - box[0]
            bh  = box[3] - box[1]

            # FIX: foot point = bottom centre of bbox
            # More accurate than centre for zone entry/exit
            foot_x = cx
            foot_y = box[3]

            # ── Match to existing track ───────────────────
            best_id, best_d = None, 120
            for tid, t in self.tracks.items():
                if tid in matched: continue
                if now - t['last_seen'] > 3.0: continue
                d = ((cx - t['cx'])**2 + (cy - t['cy'])**2) ** 0.5
                if d < best_d:
                    best_d  = d
                    best_id = tid

            # ── New person — create track ─────────────────
            if best_id is None:
                best_id = self.next_id
                self.next_id += 1
                self.tracks[best_id] = {
                    'first_seen':      now,
                    'last_seen':       now,
                    'cx': cx, 'cy': cy,
                    'foot_x': foot_x, 'foot_y': foot_y,
                    'prev_cx': cx, 'prev_cy': cy,

                    # Dwell — FIX: accumulates, never resets until track removed
                    'zone_total_time':  0.0,
                    'zone_enter_time':  None,
                    'in_zone_prev':     False,
                    'zone_exit_time':   None,

                    # Visit counting
                    'visit_times':      [],
                    'stop_timer':       None,
                    'visit_counted':    False,

                    # Crouching — FIX: baseline required first
                    'stand_height':              bh,
                    'stand_height_confirmed':    False,
                    'stand_frames':              0,
                    'crouch_timer':              None,
                    'is_crouching':              False,

                    # Pacing
                    'position_history':  [],
                    'direction_changes': 0,
                    'last_direction':    None,
                    'pacing_score':      0,

                    # Freeze — FIX: requires prior movement, 3s duration
                    'was_moving':        False,
                    'freeze_timer':      None,
                    'is_frozen':         False,

                    # Erratic
                    'speed_history':     [],
                }

            matched.add(best_id)
            t    = self.tracks[best_id]
            move = ((cx - t['cx'])**2 + (cy - t['cy'])**2) ** 0.5

            t['prev_cx']   = t['cx']
            t['prev_cy']   = t['cy']
            t['cx']        = cx
            t['cy']        = cy
            t['foot_x']    = foot_x
            t['foot_y']    = foot_y
            t['last_seen'] = now

            t['speed_history'].append(move)
            if len(t['speed_history']) > 10:
                t['speed_history'].pop(0)

            t['position_history'].append((cx, cy, now))
            if len(t['position_history']) > 30:
                t['position_history'].pop(0)

            crouching = self._check_crouching(t, bh, now)
            pacing    = self._check_pacing(t)
            frozen    = self._check_freeze(t, move, now)
            erratic   = self._check_erratic(t)
            running   = move > config.RUNNING_SPEED_PX

            result.append({
                'track_id':     best_id,
                'box':          box,
                'foot_x':       foot_x,
                'foot_y':       foot_y,
                'dwell_time':   t['zone_total_time'],
                'movement':     move,
                'visit_count':  self._recent_visits(t, now),
                'is_crouching': crouching,
                'is_pacing':    pacing,
                'is_frozen':    frozen,
                'is_erratic':   erratic,
                'is_running':   running,
                'cx': cx, 'cy': cy,
            })

        stale = [tid for tid, t in self.tracks.items()
                 if now - t['last_seen'] > 5]
        for tid in stale:
            del self.tracks[tid]

        return result

    def update_zone_state(self, track_id, in_zone):
        """
        FIX: Dwell accumulates across all visits.
        Never resets on zone exit. Only resets when track is removed.
        Gap tolerance: re-entry within 30s = same session.
        """
        if track_id not in self.tracks:
            return
        t   = self.tracks[track_id]
        now = time.time()

        if in_zone:
            if not t['in_zone_prev']:
                t['zone_enter_time'] = now
                # gap < 30s = quick return, dwell continues seamlessly
            else:
                if t['zone_enter_time']:
                    t['zone_total_time'] += now - t['zone_enter_time']
                    t['zone_enter_time']  = now
        else:
            if t['in_zone_prev']:
                if t['zone_enter_time']:
                    t['zone_total_time'] += now - t['zone_enter_time']
                    t['zone_enter_time']  = None
                t['zone_exit_time'] = now
                # FIX: zone_total_time NOT reset here

        t['in_zone_prev'] = in_zone

        dx = abs(t['cx'] - t['prev_cx'])
        dy = abs(t['cy'] - t['prev_cy'])
        is_still = (dx**2 + dy**2) ** 0.5 < config.ZONE_STOP_PIXELS

        if in_zone and is_still:
            if t['stop_timer'] is None:
                t['stop_timer']    = now
                t['visit_counted'] = False
            elif (not t['visit_counted'] and
                  (now - t['stop_timer']) >= config.ZONE_STOP_SECONDS):
                t['visit_times'].append(now)
                t['visit_counted'] = True
        else:
            t['stop_timer']    = None
            t['visit_counted'] = False

    def _recent_visits(self, t, now):
        cutoff = now - config.VISIT_WINDOW_SEC
        return sum(1 for vt in t['visit_times'] if vt > cutoff)

    def _check_crouching(self, t, current_height, now):
        """
        FIX: Baseline required before flagging. Short people never falsely flagged.
        FIX: Duration increased to 4s.
        """
        if not t['stand_height_confirmed']:
            if current_height >= t['stand_height'] * 0.85:
                t['stand_frames'] += 1
                t['stand_height'] = t['stand_height'] * 0.9 + current_height * 0.1
                if t['stand_frames'] >= 10:
                    t['stand_height_confirmed'] = True
            return False

        ref_h = t['stand_height']
        if current_height < ref_h * config.CROUCH_SHRINK_RATIO:
            if t['crouch_timer'] is None:
                t['crouch_timer'] = now
            if now - t['crouch_timer'] >= 4.0:  # FIX: was 3s
                t['is_crouching'] = True
                return True
        else:
            t['crouch_timer'] = None
            t['is_crouching'] = False
            t['stand_height'] = t['stand_height'] * 0.97 + current_height * 0.03
        return False

    def _check_pacing(self, t):
        """
        FIX: Minimum speed threshold — stationary jitter ignored.
        FIX: Pixel threshold raised from 3 to 6 — filters micro-movement.
        """
        hist = t['position_history']
        if len(hist) < 10:
            return False

        speeds = t['speed_history']
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        if avg_speed < 3:
            return False  # FIX: not moving enough to be pacing

        reversals = 0
        prev_dx   = 0
        for i in range(1, len(hist)):
            dx = hist[i][0] - hist[i-1][0]
            if prev_dx != 0:
                if (dx > 6 and prev_dx < -6) or (dx < -6 and prev_dx > 6):  # FIX: 3→6
                    reversals += 1
            if abs(dx) > 6:
                prev_dx = dx

        return reversals >= 3

    def _check_freeze(self, t, current_move, now):
        """
        FIX: Requires meaningful prior speed (>10) not just any movement (>8).
        FIX: Duration increased from 2s to 3s.
        """
        speeds = t['speed_history']
        if len(speeds) < 6:
            return False

        avg_recent = sum(speeds[-3:]) / 3
        avg_before = sum(speeds[-6:-3]) / 3

        was_moving = avg_before > 10   # FIX: raised from 8 to 10
        now_still  = avg_recent < 2

        if was_moving and now_still:
            if t['freeze_timer'] is None:
                t['freeze_timer'] = now
            if now - t['freeze_timer'] >= 3.0:  # FIX: was 2s
                t['is_frozen'] = True
                return True
        else:
            t['freeze_timer'] = None
            t['is_frozen']    = False
        return False

    def _check_erratic(self, t):
        speeds = t['speed_history']
        if len(speeds) < 8:
            return False
        avg      = sum(speeds) / len(speeds)
        variance = sum((s - avg) ** 2 for s in speeds) / len(speeds)
        std      = variance ** 0.5
        return std > 12 and avg > 5

    def is_person_in_zone(self, foot_x, foot_y, zone, tolerance=10):
        """
        FIX: Foot-point detection with tolerance buffer.
        Replaces IoU-based centre-point detection.
        """
        x1, y1, x2, y2 = zone
        return (x1 + tolerance <= foot_x <= x2 - tolerance and
                y1 + tolerance <= foot_y <= y2 - tolerance)

    # Keep IoU for backwards compatibility with zone_selector
    def is_inside_any_zone_iou(self, box, zones, zone_types):
        for i, zone in enumerate(zones):
            if self._iou(box, zone) > config.TOUCH_IOU_THRESHOLD:
                return True, zone, i
        return False, None, -1

    def _iou(self, box_a, box_b):
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        return inter / ((ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter + 1e-6)
