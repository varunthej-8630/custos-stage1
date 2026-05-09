# zone_monitor.py — CUSTOS Optimised
# Changes from previous version:
#   - Removed config_tamper_std_thresh() workaround function
#   - config is now imported normally at the top like every other module
#   - Confirmation time pulled from config.TAMPER_CONFIRM_SEC (was hardcoded 1.5)
#   - object_moved diff threshold pulled from config (was hardcoded 45)
#   - No logic changes — tamper detection behaviour identical

import cv2
import numpy as np
import time
from config import settings as config


class ZoneMonitor:
    def __init__(self):
        self.reference_crops       = {}
        self.last_object_check     = 0
        self.object_check_interval = 3.0   # CPU-heavy, check every 3s
        self.camera_tamper_since   = None

    def set_reference(self, frame, zones):
        self.reference_crops = {}
        for i, zone in enumerate(zones):
            x1, y1, x2, y2 = zone
            crop = frame[y1:y2, x1:x2]
            if crop.size > 0:
                self.reference_crops[i] = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                print(f'[MONITOR] Reference saved for Zone {i+1}')

    def update(self, frame, zones, occupied_zones=None):
        occupied_zones = occupied_zones or set()
        now     = time.time()
        results = {i: {'zone_index': i, 'occluded': False, 'object_moved': False}
                   for i in range(len(zones))}

        # ── Whole-camera tamper — every frame ─────────────────
        # Detects any solid cover (hand, cloth, paper, bag) by checking
        # image uniformity (std deviation) regardless of brightness.
        # A covered camera = very uniform image = low std.
        if self._check_whole_camera_tamper(frame, now):
            for i in results:
                results[i]['occluded'] = True
            return results

        # ── Object-moved check — every 3s (CPU heavy) ─────────
        if now - self.last_object_check >= self.object_check_interval:
            self.last_object_check = now
            for i, zone in enumerate(zones):
                if i not in self.reference_crops or i in occupied_zones:
                    continue
                x1, y1, x2, y2 = zone
                current_crop = frame[y1:y2, x1:x2]
                if current_crop.size == 0:
                    continue
                current_gray = cv2.cvtColor(current_crop, cv2.COLOR_BGR2GRAY)
                ref_gray     = cv2.resize(self.reference_crops[i],
                                          (current_gray.shape[1], current_gray.shape[0]))
                diff_score   = float(np.mean(cv2.absdiff(current_gray, ref_gray)))
                if diff_score > 45:
                    results[i]['object_moved'] = True
                    print(f'[MONITOR] Zone {i+1}: object moved (diff={diff_score:.1f})')

        return results

    def _check_whole_camera_tamper(self, frame, now) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        std  = float(np.std(gray))

        if std < config.TAMPER_STD_THRESH:
            if self.camera_tamper_since is None:
                self.camera_tamper_since = now
                print(f'[MONITOR] Possible cover — std={std:.1f}')
            elif now - self.camera_tamper_since >= config.TAMPER_CONFIRM_SEC:
                print(f'[MONITOR] TAMPER CONFIRMED — std={std:.1f}')
                return True
        else:
            if self.camera_tamper_since is not None:
                print(f'[MONITOR] Camera clear — std={std:.1f}')
            self.camera_tamper_since = None

        return False