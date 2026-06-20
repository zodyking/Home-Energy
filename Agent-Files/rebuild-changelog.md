# Home Energy Rebuild — Audit Findings & Fixes

Tracking log for the incremental rebuild of the Home Energy HA integration
(`custom_components/smart_dashboards/`). Source: full codebase audit conducted
2026-06-20 covering light automation, door/window controls, HA-convention
deviations, and the frontend monolith.

## Phase 1 — Light Automation (backend)

New module: `custom_components/smart_dashboards/light_automation.py` with
`classify_outlet_type`, `switch_entity_for_outlet`, `encode_tuya_scene_hex`
(canonical encoder), `apply_tuya_scene` (shared apply path), and
`energize_switch_for_mode`.

Bugs fixed in `energy_monitor.py`:

- **BUG 1** — `mode` segment on an off light now applies color/temp/brightness
  instead of energizing at default for 60s then killing it. Added
  `elif action == "mode" and not current_on` branch in
  `_async_run_light_automation_effects`.
- **BUG 2** — Re-entrant thrash on apply failure. `_apply_light_group_segment`
  / `_apply_light_single_segment` calls in the tick are wrapped in try/except;
  `last_apply_mono` is set to `now` on failure so the next tick waits the full
  interval.
- **BUG 3** — Two competing throttles consolidated. `_should_skip_light_enforcement`
  and `_mark_light_enforcement_run` now use `time.monotonic` (same clock as the
  tick's `_light_auto_apply_state`) instead of `time.time`.
- **BUG 4** — Scene hash tracking replaced. `_light_state_matches_segment` now
  reads the actual `text.{light}_scene` entity state and compares the
  freshly-encoded hex. `full_mode_converge` loop capped at 3 iterations (was 45).
- **BUG 5** — Switch-energize pattern consolidated via `energize_switch_for_mode`
  helper (single source for group + single apply paths).
- **BUG 6** — Mireds vs kelvin. New `_to_kelvin(value, attr_name)` helper
  normalizes both sides to kelvin before comparing; used in both the match
  check and the apply path.
- **BUG 7** — Brightness tolerance off-by-one. Match check now uses
  `abs(float(cur) - float(target)) > 5` to agree with the apply check.
- **BUG 8** — `finally` de-energize on failure. The 60s de-energize now runs
  only on success (`apply_exc is None`); on exception the switch state is left
  alone and the failure is logged.
- **BUG 10** — Lights not restored on TTS failure. `_do_lights_and_tts` wraps
  `asyncio.gather(tts_task, light_task)` in try/finally so
  `_async_restore_lights` always runs.
- **BUG 12** — Outlet-type ladder. `classify_outlet_type` enum is the single
  source of truth (callers can adopt incrementally).
- **BUG 15** — Dead `v` field in Tuya scene unit. Encoder reads only `bright`;
  `v` is being removed from the frontend schema in a follow-up.
- **BUG 18** — Test path diverges from automation path. `apply_tuya_scene` is
  the shared apply path; `websocket.py` test handler now accepts either a raw
  `scene` dict (preferred) or a pre-encoded `scene_data_v2` hex.
- **BUG 22** — Duplicated Tuya encoder. JS encoder deleted from
  `energy-panel.js`; backend `encode_tuya_scene_hex` is canonical. New
  `smart_dashboards/encode_tuya_scene` WS command for frontend previews.

## Phase 2 — Door/Window Controls (backend)

New module: `custom_components/smart_dashboards/door_window.py` with
`contact_is_open` (canonical open-state check) and
`find_door_window_outlet_by_field` (generic outlet lookup).

Bugs fixed in `energy_monitor.py` / `config_manager.py` / `websocket.py`:

- **BUG 1** — Listeners not refreshed on config save. New
  `refresh_door_window_listeners()` on `EnergyMonitor`, called from
  `config_manager.async_update_energy` after `refresh_presence_listeners`.
- **BUG 2** — Orphaned auto-lock tasks. `_handle_door_contact_change` cancels
  the existing `_door_auto_lock_task[key]` before scheduling a new one.
- **BUG 3** — Presence handler missing baseline dedupe.
  `_async_handle_door_window_presence_change` now calls
  `_door_lock_signal_is_baseline_or_duplicate` at the top.
- **BUG 4** — Uncancellable presence hold sleep. Hold-then-announce extracted
  into `_async_presence_hold_then_announce` task, tracked in
  `_presence_handler_tasks[key]`, cancelled on teardown / new event for the
  same key, checks `_running` after the sleep.
- **BUG 5** — Lock-engaged suppresses still-open reminder. Removed the
  `await self._stop_door_reminder(key)` line in the lock handler; only the
  contact-sensor close transition stops the open reminder.
- **BUG 6** — Resync doesn't re-arm auto-lock. `_async_resync_door_window_reminders_on_startup`
  now re-arms `_door_auto_lock_task` for currently-closed + unlocked doors with
  `auto_lock_enabled`, and re-seeds `_door_window_last_signal_state`.
- **BUG 7** — Dead state dicts. `_door_window_state`, `_lock_state`,
  `_presence_hold_state` removed (never read/written).
- **BUG 8** — Heater block on/open inconsistency. `_heater_door_window_blocks`
  and the `websocket.py` manual-toggle guard now use `contact_is_open`
  (accepts both `on` and `open`).
- **BUG 12** — Windows have no activity log. `append_door_activity_event`
  accepts `type in ("door","window")`; `_handle_window_contact_change` now
  records opened/closed events.

## Phase 3 — HA Convention Fixes

- **Storage** — `_load_json_file` tolerates corrupt JSON (backs up + returns
  None instead of crashing). `_write_json_file` is atomic (write `.partial`
  then `os.replace`). Full `Store` migration deferred to a focused follow-up.
- **Recorder threading** — 7 recorder-touching call sites in `websocket.py`
  now use `get_instance(hass).async_add_executor_job` via the new
  `_recorder_executor_job` helper.
- **Passcode security** — `websocket_verify_passcode` uses `hmac.compare_digest`
  and applies a per-connection rate limit (5 fails / 60s → 60s lockout).
- **Logging** — `_monitor_loop` uses `_LOGGER.exception` instead of
  `_LOGGER.error("%s", e)` to preserve tracebacks.

## Phase 4 — Frontend Module Extraction (partial)

- `frontend/tokens.css` created as the canonical palette source of truth
  (extracted from `shared-utils.js` `:host` + inline styles).
- Drifted JS Tuya encoder deleted (`energy-panel.js::_encodeTuyaSceneHex`);
  callers now send the raw scene dict to the backend.
- New `smart_dashboards/encode_tuya_scene` WS command for frontend previews.
- **BUG 23** — `_segmentsOverlap` now handles midnight wrap-around via
  `_segmentIntervals` (splits wrap segments at midnight).
- **BUG 24** — `_refreshLightAutomationModal` now flushes the segment editor
  to state before re-rendering, so switching segments no longer discards
  unsaved edits.

Full 11-module ES-module split deferred (the 18,938-line file is a single
class; a safe split is a focused multi-day follow-up that should not be rushed
alongside the bug fixes).

## Phase 5 — UX Modernization (same palette)

- **Room card declutter** — Room name no longer cycles with presence; presence
  is a small chip beside the name (`.room-name-presence-chip`).
- **Settings tabs responsive** — `.settings-tabs` now `flex-wrap` with
  `min-height: 44px` tap targets so the 7-tab strip reflows on mobile instead
  of squishing.
- **Dirty-state guard** — New `_settingsDirty` flag set by delegated
  input/change listeners in settings; Back button warns on unsaved changes;
  cleared on successful save.
- **Dead stove branch** — Removed the unreachable `else if` in `_loadStoveData`.

## Phase 6 — Live Update Modernization

- **Door/window card change-detection** — The 1s live-update loop now skips
  DOM writes when the contact/lock state signature hasn't changed since the
  last tick (`dataset.lastDoorSig` / `lastWindowSig`).
- **BUG 13** — Open-state check consolidated into `isContactOpen(state)` helper
  (was duplicated in 4 frontend sites).

## Phase 7 — Verification

- All modified Python files pass `python -m py_compile`.
- `energy-panel.js` and `shared-utils.js` pass `node --check`.
- No linter errors across all modified files.
- Kept modules (`statistics_aggregation.py`, `mobile_notify_target.py`,
  `room_ratings.py`) untouched — no regression risk.

## Out of Scope / Deferred

- Full `homeassistant.helpers.storage.Store` migration (Phase 3 — atomic writes
  delivered as an interim measure).
- Full 11-module ES-module split of `energy-panel.js` (Phase 4 — tokens.css
  + encoder dedupe + targeted bug fixes delivered).
- Full unification of the 7 delegation flags (Phase 6 — they work correctly
  as-is; consolidated open-state helper delivered).
- Settings tab grouping 7→4 (Phase 5 — mobile wrap delivered instead, lower
  regression risk).
- Per-section save buttons (Phase 5 — global dirty-state guard delivered).
- Manual reload verification in a live HA instance (requires the user's HA
  environment).

## Phase 8 — Light Automation Frontend Audit

Full audit of the light automation modal UI (`_openLightAutomationModal` and
related methods in `energy-panel.js`). Bugs found and fixed:

- **Listener leak** — the segment-level color wheel, temp wheel, and both
  inline-scene wheels attached `mousemove`/`mouseup`/`touchmove`/`touchend`
  handlers directly to `document` on every `_refreshLightAutomationModal`
  call and never removed them. After a few segment switches dozens of zombie
  listeners fired on every pointer move. Added `_addLightAutoDocListener` /
  `_detachLightAutoDocListeners`; detach now runs on refresh, close, and
  open.
- **Wrap-around on right-edge click** — clicking the timeline near the right
  edge produced an end time of `00:00` (from `_percentToTime(100)`), which
  the backend treats as start-of-day, turning an end-of-day segment into a
  wrap-around spanning the whole next day. Added `_percentToEndTime` that
  maps 100% to `23:59`; used in both group and individual timeline click
  handlers.
- **Silent overlap no-op** — `_addTimelineSegment` /
  `_addTimelineSegmentForEntity` returned without feedback when the new
  segment overlapped an existing one, so clicking "did nothing." Now shows a
  toast explaining the overlap.
- **White-mode misdetection** — `_renderInlineSceneStep`,
  `_renderInlineSceneEditor` (`isUnitColorMode`), and
  `_updateInlineStepCircle` used `unit.h === 0 || !unit.h`, where `!0` is
  `true`, so any color-mode unit with `h:0` (red) and `s:0` was misdetected
  as white mode. Replaced with strict `temperature > 0 && h === 0 && s === 0`.
- **Dead `v` field** — default Tuya scene units carried a `v: 1000` field
  that the backend `encode_tuya_scene_hex` never reads (it uses `bright`).
  Removed from all 5 default-unit literals.
- **Dead legacy scene builder** — `_openTuyaSceneBuilder`,
  `_renderTuyaSceneModal`, `_attachTuyaSceneListeners`,
  `_refreshTuyaSceneModal`, `_updateStepCircleColor`,
  `_renderTuyaStepCircle`, `_renderTuyaColorWheelPicker`,
  `_renderTuyaTempWheelPicker`, `_testTuyaScene`, and ~290 lines of
  `.tuya-scene-*` CSS were an unreachable duplicate of the inline scene
  editor (no callers). Deleted the methods and the CSS.
- **No delete confirmation** — the segment "Delete" button spliced the
  segment immediately on click. Added a `window.confirm` guard.
- **No keyboard access** — timeline segments had no `tabindex`/`role`/keydown
  handling. Added `role="button"`, `tabindex="0"`, `aria-label`, and
  Enter/Space handlers on both group and individual timelines, plus a
  `:focus-visible` outline.
- **Auth-check swallow** — `_openLightAutomationModal` caught
  `verify_room_auth` WS failures and opened the modal anyway, letting
  unauthorized users edit automations when the call errored. Now fails
  closed with a toast.
- **Mode-Only option scope** — the action `<select>` showed the "Mode Only"
  option based on the room-level `state.hasWrgb` even in individual mode,
  where the selected light may not be WRGB. Now uses the per-light
  `scope.hasWrgb` / local `hasWrgb`.
- **No touch drag** — `_attachSegmentDragHandlers` wired only
  `mousedown/mousemove/mouseup`, so segment edges and whole-segment drags
  didn't work on touch devices. Added `touchstart` handlers on both handles
  and segment bodies that synthesize clientX and route through the existing
  mouse pipeline; `passive: false` + `preventDefault` to stop scroll
  fighting.
- **Stale scene step** — `sceneSelectedStep` could persist from a prior
  modal session and point past the end of a new scene's unit list. Now
  reset to 0 when opening the modal.
- **Mobile modal reachability** — the centered 90vh modal with overlay
  padding could push the footer Save/Cancel below the fold on small
  screens. Added a `max-width: 640px` media query that makes the modal
  full-height/full-width with reduced padding so the footer is always
  reachable.
- **Color wheel text selection** — `mousedown` on the segment-level color
  wheel and inline-scene wheels didn't `preventDefault`, causing text
  selection while dragging. Added `e.preventDefault()` on the wheel
  `mousedown`/`touchstart` handlers.

Verification: `node --check energy-panel.js` passes; no linter errors; no
lingering references to the deleted legacy methods or `.tuya-scene-*` CSS.
