/**
 * Energy Panel for Smart Dashboards
 * Room-based power monitoring with automatic TTS threshold alerts
 */

import { sharedStyles, icons, showToast, passcodeModalStyles, showPasscodeModal, renderCustomSelect, initCustomSelects } from './shared-utils.js';

// TTS message defaults (must match const.py, periods and commas only for TTS)
const TTS_DEFAULTS = {
  prefix: 'Message from Home Energy.',
  room_warn_msg: '{prefix} {room_name} is using {watts} watts out of {threshold} watt room threshold, reduce your usage.',
  outlet_warn_msg: '{prefix} {outlet_name} in {room_name} is using {watts} watts out of {threshold} watt outlet threshold, reduce your usage.',
  budget_exceeded_msg: '{prefix} {room_name} at {kwh_used} kWh, power alerts are on.',
  shutoff_msg: '{prefix} {room_name} {outlet_name} {plug} reset after overload, reduce power use.',
  breaker_warn_msg: '{prefix} {breaker_name} is using {watts} watts out of {max_load} watt limit, reduce your usage.',
  breaker_shutoff_msg: '{prefix} {breaker_name} at limit, {watts} watts, max {max_load} watts. Shutoff enabled.',
  phase1_warn_msg: '{prefix} {room_name} has exceeded threshold {warning_count} times. Volume will rise until power stays under {threshold} watts.',
  phase2_warn_msg: '{prefix} {room_name} has exceeded threshold {warning_count} times. Cycling all outlets now, turn off devices.',
  phase2_after_msg: '{prefix} Cycle complete in {room_name}. Stay under limit or outlets cycle again.',
  minisplit_phase2_warn_msg:
    '{prefix} {room_name} is over the {room_threshold} watt room limit. Turning off {outlet_name} to protect the circuit. It will stay off at least {restore_delay} seconds for compressor safety, and will only turn back on when the room is under the limit. Other outlets may still cycle if the room stays high.',
  minisplit_phase2_after_msg:
    '{prefix} Enforcement step complete in {room_name}. {outlet_name} stays off until total room power is under {room_threshold} watts.',
  minisplit_phase2_restore_msg:
    '{prefix} Room power is under {room_threshold} watts. Restoring power to {outlet_name}.',
  phase_reset_msg: '{prefix} {room_name} under limit, enforcement reset.',
  room_kwh_warn_msg: '{prefix} {room_name} used {kwh_limit} kWh today, {percentage} percent of home, reduce use.',
  home_kwh_warn_msg: '{prefix} Home over {kwh_limit} kWh today, reduce consumption.',
  budget_boost_scheduled_msg:
    '{prefix} Room kilo watt hour budgets are {budget_multiplier} times higher {period_label}, because usage is usually higher those days.',
  phase1_warn_msg_boost_day:
    '{prefix} {room_name} has exceeded threshold {warning_count} times. Kilo watt hour budget is {budget_multiplier} times higher {period_label}, effective {kwh_budget_effective} versus usual {kwh_budget} kilo watt hours. Volume will rise until power stays under {threshold} watts.',
  stove_timer_progress_msg:
    '{prefix} Stove unattended timer: about {minutes_remaining} minutes and {seconds_remaining} seconds remaining.',
  vent_automation_on_msg:
    '{prefix} {room_name} vent is on.',
  heater_automation_on_msg:
    '{prefix} {room_name} temp below {threshold} degrees, warming up {room_name}.',
  notification_title: 'Home Energy',
  notify_budget_hit_title: '{notification_title} Budget Exceeded',
  notify_budget_hit_msg: '{room_name} has exceeded its daily budget of {kwh_budget} kWh (used {kwh_used} kWh).',
  notify_enforcement_phase1_title: '{notification_title} Enforcement Phase 1',
  notify_enforcement_phase1_msg: '{room_name} has entered enforcement phase 1 (volume escalation). Please reduce power usage.',
  notify_enforcement_phase2_title: '{notification_title} Enforcement Phase 2',
  notify_enforcement_phase2_msg: '{room_name} has entered enforcement phase 2 (power cycling). Please reduce power usage.',
  notify_ac_auto_off_title: '{notification_title} Air Conditioner Off',
  notify_ac_auto_off_msg:
    '{outlet_name} was turned off because {person_name} left the monitored zone.',
  notify_ac_auto_on_title: '{notification_title} Air Conditioner On',
  notify_ac_auto_on_msg: '{outlet_name} was turned back on because {person_name} is nearby.',
  notify_toggle_title: '{notification_title} Appliance Toggled',
  notify_toggle_msg: '{user_name} turned {action} {outlet_name} in {room_name}.',
  notify_heater_auto_on_title: '{notification_title} Heater On',
  notify_heater_auto_on_msg: '{room_name} is {temperature}°, turning on {outlet_name}.',
  notify_heater_auto_off_title: '{notification_title} Heater Off',
  notify_heater_auto_off_msg: '{room_name} reached {temperature}°, turning off {outlet_name}.',
  notify_vent_auto_on_title: '{notification_title} Vent On',
  notify_vent_auto_on_msg: 'Motion detected in {room_name}, turning on {outlet_name}.',
  notify_vent_auto_off_title: '{notification_title} Vent Off',
  notify_vent_auto_off_msg: 'No motion in {room_name}, turning off {outlet_name}.',
};

const EFFICIENCY_UI_DEFAULTS = {
  efficiency_digest_title: '{notification_title} {room_name} efficiency',
  efficiency_digest_message:
    '{room_name}: {stars} stars ({average}/100). {worst_pillar_tip}',
};

/** Tooltip + visible label for room header enforcement badge (index = phase 0–2). */
const ENFORCEMENT_PHASE_TITLES = [
  'Power enforcement Phase 0: monitoring on; volume may rise and outlets may cycle if limits are ignored.',
  'Power enforcement Phase 1: TTS volume escalates with repeated threshold warnings.',
  'Power enforcement Phase 2: outlets may be power-cycled when warnings continue.',
];
/** Short header label next to shield icon (index = phase 0–2). */
const ENFORCEMENT_BADGE_LABELS = ['Enforced', 'Phase 1', 'Phase 2'];

/** Fallback when ha-icon-picker is unavailable (~120 common MDI ids). */
const ROOM_ICON_CURATED = [
  'mdi:home', 'mdi:home-variant', 'mdi:home-outline', 'mdi:door', 'mdi:door-open',
  'mdi:bed', 'mdi:bed-empty', 'mdi:sofa', 'mdi:chair-rolling', 'mdi:desk',
  'mdi:pot-steam', 'mdi:stove', 'mdi:microwave', 'mdi:fridge', 'mdi:silverware-fork-knife',
  'mdi:coffee', 'mdi:cup', 'mdi:bottle-wine', 'mdi:glass-wine',
  'mdi:toilet', 'mdi:shower', 'mdi:bathtub', 'mdi:washing-machine', 'mdi:tumble-dryer',
  'mdi:iron', 'mdi:hanger', 'mdi:wardrobe',
  'mdi:desk-lamp', 'mdi:floor-lamp', 'mdi:ceiling-light', 'mdi:lightbulb', 'mdi:led-strip',
  'mdi:television', 'mdi:monitor', 'mdi:laptop', 'mdi:keyboard', 'mdi:gamepad-variant',
  'mdi:bookshelf', 'mdi:book-open-variant', 'mdi:palette',
  'mdi:garage', 'mdi:garage-open', 'mdi:car', 'mdi:bike', 'mdi:motorbike',
  'mdi:tree', 'mdi:flower', 'mdi:sprout', 'mdi:watering-can',
  'mdi:hammer-wrench', 'mdi:tools', 'mdi:screwdriver', 'mdi:brush',
  'mdi:router-wireless', 'mdi:server', 'mdi:ip-network',
  'mdi:thermometer', 'mdi:snowflake', 'mdi:fire', 'mdi:weather-sunny',
  'mdi:fan', 'mdi:air-conditioner', 'mdi:radiator', 'mdi:heat-wave',
  'mdi:power-plug', 'mdi:flash', 'mdi:lightning-bolt', 'mdi:battery', 'mdi:solar-power',
  'mdi:window-open', 'mdi:window-closed', 'mdi:blinds', 'mdi:roller-shade',
  'mdi:stairs', 'mdi:elevator', 'mdi:floor-plan',
  'mdi:dog', 'mdi:cat', 'mdi:fish', 'mdi:bird',
  'mdi:baby-face', 'mdi:human-male', 'mdi:human-female', 'mdi:account-group',
  'mdi:office-building', 'mdi:factory', 'mdi:warehouse', 'mdi:store',
  'mdi:gymnastics', 'mdi:dumbbell', 'mdi:swim', 'mdi:basketball',
  'mdi:music', 'mdi:microphone', 'mdi:headphones', 'mdi:speaker',
  'mdi:filmstrip', 'mdi:camera', 'mdi:image', 'mdi:piano',
  'mdi:heart', 'mdi:star', 'mdi:shield-home', 'mdi:lock', 'mdi:key-variant',
  'mdi:bell', 'mdi:alarm-light', 'mdi:smoke-detector', 'mdi:fire-alert',
  'mdi:water', 'mdi:water-pump', 'mdi:pipe', 'mdi:leak',
  'mdi:recycle', 'mdi:leaf', 'mdi:earth',
];

const _ROOM_ICON_MDI_RE = /^mdi:[a-z0-9-]+$/;

function isVentLikeType(t) {
  return t === 'vent' || t === 'wall_heater' || t === 'ceiling_vent_fan';
}

class EnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._powerData = null;
    this._showSettings = false;
    this._settingsTab = 'rooms'; // 'rooms' | 'tts' | 'notifications' | 'statistics' | 'efficiency' | 'enforcement' | 'zone-health'
    this._dashboardView = 'rooms'; // 'rooms' | 'statistics' | 'stove'
    this._stoveData = null;
    this._refreshInterval = null;
    this._statsRefreshInterval = null;
    this._loading = true;
    this._error = null;
    this._draggedRoomCard = null;
    this._graphOpen = null;  // { type, roomId?, roomName?, billingStart?, billingEnd? }
    this._graphData = null;  // from get_daily_history
    this._graphLoading = false;
    this._graphLoadError = null;
    this._apexChartInstance = null;
    this._statsData = null;  // from get_statistics
    this._statsLoading = false;
    this._statsFetchedAt = null; // ms — last successful get_statistics
    this._statsFetchError = null;
    this._statsSubscription = null; // WebSocket subscription for live statistics updates
    this._statsRoomsView = 'pie'; // 'table' | 'pie' — statistics rooms card only
    this._statsRoomsPieInstance = null;
    this._statsPieRoomRows = null; // aligned with pie series for tooltips / selection
    /** Serializes async pie mount so concurrent _render() passes cannot stack ApexCharts. */
    this._statsPieSyncChain = Promise.resolve();
    this._statPieBillingDelegation = false;
    this._applianceToggleDelegation = false;
    /** Appliance card context menu: Escape handler + scroll-close. */
    this._applianceMenuEsc = null;
    this._applianceMenuScrollClose = null;
    this._summaryStatsResizeObs = null;
    this._summaryStatsWindowResizeBound = null;
    this._summaryFitDebounce = null;
    this._summaryFitZeroRetry = null;
    this._summaryFitRaf = null;
    this._graphModalEscapeHandler = null;
    /** AbortController teardown for Shadow-DOM-safe native bar charts (billing + room hourly; no Apex). */
    this._billingBarNativeCleanup = null;
    /** Room icon modal: `.room-settings-card` receiving the selection. */
    this._roomIconModalTargetCard = null;
    this._roomIconModalEscapeHandler = null;
    this._presenceLiveLastRun = 0;
    this._presenceLiveThrottleTimer = null;
    // Zone health data for room card indicators
    this._zoneHealthData = null;
    this._zoneHealthRefreshInterval = null;
    this._zoneHealthIconClickDelegation = false;
    this._dashboardHeartbeatInterval = null;
    this._roomRatingModalDelegation = false;
    this._roomRatingModalEsc = null;
    /** @type {ResizeObserver|null} */
    this._roomsGridResizeObserver = null;
    /** @type {number|null} */
    this._roomTitleFitRaf = null;
    /** @type {number} */
    this._roomTitleFitGen = 0;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) {
      this._loadConfig();
    }
    if (this._showSettings && hass?.states) {
      this._scheduleUpdateRoomPresenceLiveLabels();
    }
    if (hass) {
      this._startRoomRatingsAndHeartbeat();
    }
  }

  set panel(panel) {
    this._panelConfig = panel.config;
  }

  connectedCallback() {
    this._render();
    this._loadConfig();
    // Start zone health refresh
    this._startZoneHealthRefresh();
  }

  disconnectedCallback() {
    this._stopRefresh();
    this._destroyStatsRoomsPie();
    if (this._summaryStatsResizeObs) {
      this._summaryStatsResizeObs.disconnect();
      this._summaryStatsResizeObs = null;
    }
    if (this._summaryStatsWindowResizeBound) {
      window.removeEventListener('resize', this._summaryStatsWindowResizeBound);
      this._summaryStatsWindowResizeBound = null;
    }
    if (this._summaryFitDebounce != null) {
      clearTimeout(this._summaryFitDebounce);
      this._summaryFitDebounce = null;
    }
    if (this._summaryFitZeroRetry != null) {
      clearTimeout(this._summaryFitZeroRetry);
      this._summaryFitZeroRetry = null;
    }
    if (this._summaryFitRaf != null) {
      cancelAnimationFrame(this._summaryFitRaf);
      this._summaryFitRaf = null;
    }
    if (this._graphModalEscapeHandler) {
      window.removeEventListener('keydown', this._graphModalEscapeHandler);
      this._graphModalEscapeHandler = null;
    }
    if (this._roomIconModalEscapeHandler) {
      window.removeEventListener('keydown', this._roomIconModalEscapeHandler);
      this._roomIconModalEscapeHandler = null;
    }
    if (this._presenceLiveThrottleTimer) {
      clearTimeout(this._presenceLiveThrottleTimer);
      this._presenceLiveThrottleTimer = null;
    }
    // Stop zone health refresh
    this._stopZoneHealthRefresh();
    this._stopRoomRatingsAndHeartbeat();
    if (this._roomRatingModalEsc) {
      window.removeEventListener('keydown', this._roomRatingModalEsc);
      this._roomRatingModalEsc = null;
    }
    this._roomTitleFitGen += 1;
    if (this._roomTitleFitRaf != null) {
      cancelAnimationFrame(this._roomTitleFitRaf);
      this._roomTitleFitRaf = null;
    }
    if (this._roomsGridResizeObserver) {
      this._roomsGridResizeObserver.disconnect();
      this._roomsGridResizeObserver = null;
    }
    this.shadowRoot?.querySelector('.room-rating-modal-overlay')?.remove();
    this._closeApplianceMenu();
    this._teardownBillingBarChartNative();
    this._unsubscribeFromStatisticsUpdates();
  }

  _statisticsRefreshMs() {
    const raw = this._config?.statistics_settings?.statistics_refresh_seconds;
    const n = typeof raw === 'number' ? raw : parseInt(String(raw ?? ''), 10);
    const sec = Number.isFinite(n) ? n : 60;
    return Math.max(15, Math.min(600, sec)) * 1000;
  }

  /** True when all five supplier-related entity fields are set (Statistics overview column). */
  _statisticsSupplierConfigured() {
    const st = this._config?.statistics_settings || {};
    const keys = [
      'billing_start_sensor',
      'billing_end_sensor',
      'current_usage_sensor',
      'projected_usage_sensor',
      'kwh_cost_sensor',
    ];
    return keys.every((k) => String(st[k] ?? '').trim() !== '');
  }

  _startRefresh() {
    this._stopRefresh();
    this._refreshInterval = setInterval(() => this._loadPowerData(), 1000);
    this._statsRefreshInterval = setInterval(() => {
      if (this._dashboardView === 'statistics') this._loadStatistics();
    }, this._statisticsRefreshMs());
  }

  _stopRefresh() {
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
    if (this._statsRefreshInterval) {
      clearInterval(this._statsRefreshInterval);
      this._statsRefreshInterval = null;
    }
  }

  async _loadConfig() {
    if (!this._hass) return;

    this._loading = true;
    this._error = null;
    this._render();

    try {
      const [config, entities, areasResult, switchesResult] = await Promise.all([
        this._hass.callWS({ type: 'smart_dashboards/get_config' }),
        this._hass.callWS({ type: 'smart_dashboards/get_entities' }),
        this._hass.callWS({ type: 'smart_dashboards/get_areas' }),
        this._hass.callWS({ type: 'smart_dashboards/get_switches' }),
      ]);
      this._config = config.energy || {};
      this._entities = entities || {};
      this._entities.persons = Array.isArray(this._entities.persons) ? this._entities.persons : [];
      this._entities.zones = Array.isArray(this._entities.zones) ? this._entities.zones : [];
      this._entities.switches = switchesResult.switches || [];
      this._entities.binary_sensors = this._entities.binary_sensors || [];
      this._areas = areasResult.areas || [];
      await this._loadPowerData();
      this._loading = false;
      this._render();
      this._startRefresh();
      queueMicrotask(() => {
        if (!this._showSettings && this._hass) {
          void this._loadStatistics();
        }
      });
    } catch (e) {
      console.error('Failed to load energy config:', e);
      this._loading = false;
      this._error = e.message || 'Failed to load configuration';
      this._render();
    }
  }

  async _loadPowerData(options = {}) {
    if (!this._hass) return;
    if (this._showSettings && !options.force) return;

    try {
      this._powerData = await this._hass.callWS({ type: 'smart_dashboards/get_power_data' });
      if (this._dashboardView === 'rooms') {
        this._updatePowerDisplay();
      }
    } catch (e) {
      console.error('Failed to load power data:', e);
    }
  }


  async _loadStatistics() {
    if (!this._hass || this._showSettings) return;

    // Never block the Statistics UI with a full-screen loader; data comes from JSON or a fast shell.
    this._statsLoading = false;
    this._statsFetchError = null;

    try {
      const data = await this._hass.callWS({ type: 'smart_dashboards/get_statistics' });
      this._statsData = data;
      this._statsFetchedAt = Date.now();
    } catch (e) {
      console.error('Failed to load statistics:', e);
      this._statsFetchError = e.message || 'Failed to load statistics';
    } finally {
      this._statsLoading = false;
      if (this._dashboardView === 'statistics') {
        this._render();
      }
    }
    
    // Subscribe to live updates (only once)
    this._subscribeToStatisticsUpdates();
  }
  
  async _subscribeToStatisticsUpdates() {
    if (this._statsSubscription || !this._hass) return;
    
    try {
      this._statsSubscription = await this._hass.connection.subscribeMessage(
        (event) => {
          // Live push from backend when statistics JSON updates
          this._statsData = event;
          this._statsFetchedAt = Date.now();
          this._statsFetchError = null;
          if (this._dashboardView === 'statistics') {
            this._render();
          }
        },
        { type: 'smart_dashboards/subscribe_statistics' }
      );
    } catch (e) {
      console.error('Failed to subscribe to statistics updates:', e);
    }
  }
  
  _unsubscribeFromStatisticsUpdates() {
    if (this._statsSubscription) {
      this._statsSubscription();
      this._statsSubscription = null;
    }
  }

  /** Human-readable age of last stats fetch, e.g. "3 min ago". */
  _statsDataAgeLabel() {
    if (!this._statsFetchedAt) return '';
    const sec = Math.floor((Date.now() - this._statsFetchedAt) / 1000);
    if (sec < 10) return 'just now';
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} min ago`;
    const h = Math.floor(min / 60);
    if (h < 48) return `${h} hr ago`;
    const d = Math.floor(h / 24);
    return `${d} day${d === 1 ? '' : 's'} ago`;
  }

  /** Format HA ISO from sensor_meta.supplier_last_updated (recorder: last transition to current cycle usage value). */
  _formatSupplierLastUpdated(iso) {
    if (!iso || typeof iso !== 'string') return '—';
    const ms = Date.parse(iso);
    if (Number.isNaN(ms)) return '—';
    const d = new Date(ms);
    const rel = Math.floor((Date.now() - ms) / 1000);
    let relPart = '';
    if (rel < 60) relPart = 'just now';
    else if (rel < 3600) relPart = `${Math.floor(rel / 60)} min ago`;
    else if (rel < 86400) relPart = `${Math.floor(rel / 3600)} hr ago`;
    else relPart = `${Math.floor(rel / 86400)} day${Math.floor(rel / 86400) === 1 ? '' : 's'} ago`;
    const abs = d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
    return `${abs} · ${relPart}`;
  }

  /** Date range for statistics billing graphs; aligns with server rolling window when API dates are missing. */
  _statisticsGraphDateRange() {
    const s = this._statsData;
    const ds = (s?.date_start || '').trim();
    const de = (s?.date_end || '').trim();
    if (ds && de) {
      return { date_start: ds, date_end: de };
    }
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    const iso = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    };
    return { date_start: iso(start), date_end: iso(end) };
  }

  _updateStatisticsDisplay() {
    if (!this._statsData || this._showSettings) return;
    const s = this._statsData;
    const dateStart = s.date_start || '';
    const dateEnd = s.date_end || '';
    const isNarrowed = s.is_narrowed === true;
    const startFormatted = this._formatDateRange(dateStart);
    const endFormatted = this._formatDateRange(dateEnd);
    const rangeBanner = dateStart && dateEnd ? `${startFormatted} – ${endFormatted}` : 'No date range available';
    const sensorValues = s.sensor_values || {};
    const sensorMeta = s.sensor_meta || {};
    const fmt = (v) => (v == null ? '—' : (typeof v === 'number' ? v.toFixed(2) : String(v)));
    const rangeEl = this.shadowRoot.querySelector('#stat-range-banner');
    const narrowedEl = this.shadowRoot.querySelector('#stat-narrowed');
    const periodLabelEl = this.shadowRoot.querySelector('#stat-period-label');
    if (rangeEl) rangeEl.textContent = rangeBanner;
    if (narrowedEl) narrowedEl.style.display = isNarrowed ? '' : 'none';
    if (periodLabelEl) {
      periodLabelEl.textContent =
        s.period_source === 'billing'
          ? 'Current billing cycle (tracked totals)'
          : 'Tracked totals window';
    }
    const curEl = this.shadowRoot.querySelector('#stat-current-usage');
    const projEl = this.shadowRoot.querySelector('#stat-projected-usage');
    const costEl = this.shadowRoot.querySelector('#stat-kwh-cost');
    if (curEl) curEl.textContent = fmt(sensorValues.current_usage);
    if (projEl) projEl.textContent = `${fmt(sensorValues.projected_usage)} kWh`;
    if (costEl) costEl.textContent = `$${fmt(sensorValues.kwh_cost)}`;
    const supUpd = this.shadowRoot.querySelector('#stat-supplier-updated');
    if (supUpd) {
      const iso = sensorMeta.supplier_last_updated;
      supUpd.textContent = iso
        ? `Bill cycle usage last changed · ${this._formatSupplierLastUpdated(iso)}`
        : 'Configure supplier sensors in Settings to show live utility reads.';
    }
    const totalKwh = s.total_kwh ?? 0;
    const totalWarnings = s.total_warnings ?? 0;
    const totalShutoffs = s.total_shutoffs ?? 0;
    const totalPowerCycles = s.total_power_cycles ?? 0;
    const kwhEl = this.shadowRoot.querySelector('#stat-total-kwh');
    const warnEl = this.shadowRoot.querySelector('#stat-total-warnings');
    const shutEl = this.shadowRoot.querySelector('#stat-total-shutoffs');
    const pcEl = this.shadowRoot.querySelector('#stat-total-power-cycles');
    if (kwhEl) kwhEl.textContent = totalKwh.toFixed(2);
    if (warnEl) warnEl.textContent = totalWarnings;
    if (shutEl) shutEl.textContent = totalShutoffs;
    if (pcEl) pcEl.textContent = totalPowerCycles;
    const rooms = s.rooms || [];
    const tbody = this.shadowRoot.querySelector('#stat-rooms-tbody');
    if (tbody) {
      const ds = dateStart;
      const de = dateEnd;
      const kwhCostNum = sensorValues.kwh_cost;
      const costOk = kwhCostNum != null && Number.isFinite(Number(kwhCostNum));
      const fmtTotalCost = (periodKwh) => {
        if (!costOk) return '—';
        const n = Number(periodKwh) * Number(kwhCostNum);
        if (!Number.isFinite(n)) return '—';
        return `$${n.toFixed(2)}`;
      };
      tbody.innerHTML = rooms.length === 0
        ? '<tr><td colspan="10" class="statistics-empty">No room data for this range.</td></tr>'
        : rooms.map((r) => {
          const rname = (r.name || r.id || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
          const rid = String(r.id || '').replace(/"/g, '&quot;');
          const warnCell = ds && de
            ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_warnings" data-room-id="${rid}" data-room-name="${rname}" title="Room warning log (billing period)">${r.warnings ?? 0}</span>`
            : `${r.warnings ?? 0}`;
          const shutCell = ds && de
            ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_shutoffs" data-room-id="${rid}" data-room-name="${rname}" title="Room shutoff log (billing period)">${r.shutoffs ?? 0}</span>`
            : `${r.shutoffs ?? 0}`;
          const cycCell = ds && de
            ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_power_cycles" data-room-id="${rid}" data-room-name="${rname}" title="Room cycle log (billing period)">${r.power_cycles ?? 0}</span>`
            : `${r.power_cycles ?? 0}`;
          const hi = (r.daily_high_kwh != null ? Number(r.daily_high_kwh) : 0).toFixed(2);
          const lo = (r.daily_low_kwh != null ? Number(r.daily_low_kwh) : 0).toFixed(2);
          const avg = (r.daily_avg_kwh != null ? Number(r.daily_avg_kwh) : 0).toFixed(2);
          const totalCost = fmtTotalCost(r.kwh);
          return `
          <tr>
            <td>${(r.name || r.id || '').replace(/</g, '&lt;')}</td>
            <td>${(r.kwh ?? 0).toFixed(2)} kWh</td>
            <td>${(r.pct ?? 0).toFixed(1)}%</td>
            <td>${warnCell}</td>
            <td>${shutCell}</td>
            <td>${cycCell}</td>
            <td>${hi}</td>
            <td>${lo}</td>
            <td>${avg}</td>
            <td>${totalCost}</td>
          </tr>`;
        }).join('');
    }
  }

  _destroyStatsRoomsPie() {
    if (this._statsRoomsPieInstance) {
      try {
        this._statsRoomsPieInstance.destroy();
      } catch (_e) {
        /* stale DOM */
      }
      this._statsRoomsPieInstance = null;
    }
  }

  _resetStatPieSelectionPanel() {
    const el = this.shadowRoot?.getElementById('stat-pie-selection');
    if (!el) return;
    el.innerHTML =
      '<p class="stat-pie-selection-meta">Tap a slice for room details and to open a usage graph. Rooms with 0 kWh this period appear in the table only.</p>';
  }

  _fillStatPieSelection(dataPointIndex) {
    const el = this.shadowRoot?.getElementById('stat-pie-selection');
    const rows = this._statsPieRoomRows;
    if (!el || !rows || dataPointIndex == null || dataPointIndex < 0 || dataPointIndex >= rows.length) {
      return;
    }
    const r = rows[dataPointIndex];
    const ds = this._statsData?.date_start;
    const de = this._statsData?.date_end;
    const rid = String(r.id || '').replace(/"/g, '&quot;');
    const rname = String(r.name || r.id || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    const title = this._eventLogEscape(String(r.name || r.id || 'Room'));
    const open = ds && de
      ? `<div class="stat-pie-selection-actions"><button type="button" class="btn-stat-chart btn-stat-chart-sm stat-room-billing-chart" data-room-id="${rid}" data-room-name="${rname}" title="Room daily kWh for the date range at the top">Open usage graph</button></div>`
      : '';
    el.innerHTML = `
      <div class="stat-pie-selection-title">${title}</div>
      ${open}`;
  }

  _syncStatsRoomsPie() {
    this._statsPieSyncChain = this._statsPieSyncChain
      .catch(() => {})
      .then(() => this._syncStatsRoomsPieImpl());
  }

  async _syncStatsRoomsPieImpl() {
    if (this._showSettings || this._dashboardView !== 'statistics') {
      this._destroyStatsRoomsPie();
      return;
    }
    const container = this.shadowRoot?.getElementById('stat-rooms-pie-chart');
    if (!container) {
      this._destroyStatsRoomsPie();
      return;
    }
    if (this._statsRoomsView !== 'pie') {
      this._destroyStatsRoomsPie();
      return;
    }
    const rooms = this._statsData?.rooms || [];
    const pieRoomRows = rooms
      .filter((r) => (Number(r.kwh) || 0) > 0)
      .map((r) => ({
        id: r.id,
        name: r.name || r.id,
        kwh: Number(r.kwh) || 0,
        pct: Number(r.pct) || 0,
        warnings: r.warnings ?? 0,
        shutoffs: r.shutoffs ?? 0,
        power_cycles: r.power_cycles ?? 0,
      }));
    this._statsPieRoomRows = pieRoomRows.length ? pieRoomRows : null;

    this._destroyStatsRoomsPie();
    container.innerHTML = '';
    this._resetStatPieSelectionPanel();

    if (pieRoomRows.length === 0) {
      container.innerHTML =
        '<p class="statistics-pie-empty">No room kWh in this period.</p>';
      return;
    }

    try {
      const ApexCharts = (await import('https://cdn.jsdelivr.net/npm/apexcharts@3.45.1/dist/apexcharts.esm.min.js')).default;
      const accent = getComputedStyle(this).getPropertyValue('--panel-accent').trim() || '#03a9f4';
      const textColor = getComputedStyle(this).getPropertyValue('--primary-text-color').trim() || '#e1e1e1';
      const muted = getComputedStyle(this).getPropertyValue('--secondary-text-color').trim() || '#9b9b9b';
      const sliceColors = [
        accent,
        '#26a69a',
        '#7e57c2',
        '#ff9800',
        '#ec407a',
        '#66bb6a',
        '#5c6bc0',
        '#ef5350',
        '#29b6f6',
        '#ab47bc',
      ];
      const labels = pieRoomRows.map((p) => String(p.name));
      const series = pieRoomRows.map((p) => p.kwh);
      const panel = this;
      const options = {
        chart: {
          type: 'pie',
          height: 300,
          fontFamily: 'inherit',
          background: 'transparent',
          toolbar: { show: false },
          animations: { enabled: true },
          events: {
            dataPointSelection(_event, _ctx, cfg) {
              const i = cfg?.dataPointIndex;
              if (typeof i === 'number' && i >= 0) {
                panel._fillStatPieSelection(i);
              }
            },
          },
        },
        labels,
        series,
        colors: sliceColors,
        legend: {
          position: 'bottom',
          fontSize: '11px',
          labels: { colors: textColor },
          markers: { width: 10, height: 10 },
        },
        plotOptions: {
          pie: {
            dataLabels: { minAngleToShowLabel: 12 },
          },
        },
        dataLabels: {
          enabled: true,
          style: { fontSize: '11px', colors: ['#fff'] },
          dropShadow: { enabled: false },
          formatter: (val) => `${Number(val).toFixed(1)}%`,
        },
        stroke: { width: 1, colors: ['rgba(0,0,0,0.25)'] },
        tooltip: {
          enabled: false,
        },
        theme: { mode: 'dark' },
      };
      this._statsRoomsPieInstance = new ApexCharts(container, options);
      await this._statsRoomsPieInstance.render();
    } catch (e) {
      console.error('Statistics rooms pie chart failed:', e);
      const errMuted =
        getComputedStyle(this).getPropertyValue('--secondary-text-color').trim() || '#9b9b9b';
      container.innerHTML = `<p class="statistics-pie-empty" style="color:${errMuted}">Chart failed to load.</p>`;
    }
  }

  async _loadStoveData() {
    if (!this._hass || this._showSettings) return;

    try {
      this._stoveData = await this._hass.callWS({ type: 'smart_dashboards/get_stove_data' });
      if (this._dashboardView === 'stove') {
        this._updateStoveDisplay();
      } else if (this._dashboardView === 'stove' && !this._showSettings) {
        // Re-render if we're on stove view but data changed significantly
        this._render();
      }
    } catch (e) {
      console.error('Failed to load stove data:', e);
    }
  }

  _updatePowerDisplay() {
    if (!this._powerData || this._showSettings) return;

    const rooms = this._powerData.rooms || [];
    
    // Update summary stats
    let totalWatts = 0;
    let totalDayWh = 0;
    rooms.forEach(r => {
      totalWatts += r.total_watts;
      totalDayWh += r.total_day_wh;
    });

    const totalWattsEl = this.shadowRoot.querySelector('#summary-total-watts');
    const totalDayEl = this.shadowRoot.querySelector('#summary-total-day');
    const totalWarningsEl = this.shadowRoot.querySelector('#summary-warnings');
    const totalShutoffsEl = this.shadowRoot.querySelector('#summary-shutoffs');
    const totalPowerCyclesEl = this.shadowRoot.querySelector('#summary-power-cycles');
    
    if (totalWattsEl) totalWattsEl.textContent = `${totalWatts.toFixed(1)} W`;
    if (totalDayEl) totalDayEl.textContent = `${(totalDayWh / 1000).toFixed(2)} kWh`;
    if (totalWarningsEl) totalWarningsEl.textContent = `${this._powerData.total_warnings || 0}`;
    if (totalShutoffsEl) totalShutoffsEl.textContent = `${this._powerData.total_shutoffs || 0}`;
    if (totalPowerCyclesEl) totalPowerCyclesEl.textContent = `${this._powerData.total_power_cycles || 0}`;
    
    rooms.forEach(room => {
      const pid = String(room.id || '');
      const cfgRoom = (this._config?.rooms || []).find(
        (r) =>
          (r.id != null && String(r.id) === pid) || this._canonicalRoomId(r) === pid,
      );
      const cardId = cfgRoom ? this._canonicalRoomId(cfgRoom) : pid;
      const roomCard = this.shadowRoot.querySelector(`.room-card[data-room-id="${cardId}"]`);
      if (!roomCard) return;

      const roomConfig = this._getRoomConfig(cardId);
      const threshold = roomConfig?.threshold || 0;

      // Update room totals (watts only in header; kWh is in the bar)
      const totalWattsSpan = roomCard.querySelector('.room-total-watts');
      if (totalWattsSpan) {
        totalWattsSpan.textContent = `${room.total_watts.toFixed(1)} W`;
        totalWattsSpan.classList.toggle('over-threshold', threshold > 0 && room.total_watts > threshold);
      }

      // Budget bar updates
      const budgetState = this._roomBudgetUiState(room, roomConfig);
      const budgetSection = roomCard.querySelector('.room-budget-section');
      const barFill = roomCard.querySelector('.room-budget-bar-fill');
      const budgetValEl = roomCard.querySelector('.room-budget-values');
      const budgetSubEl = roomCard.querySelector('.room-budget-sub');
      if (budgetSection) {
        budgetSection.classList.toggle('room-budget-section--na', !budgetState.showBar);
      }
      if (barFill) {
        barFill.style.width = `${budgetState.showBar ? budgetState.fillPct : 0}%`;
        barFill.classList.remove('kwh-tier-0', 'kwh-tier-1', 'kwh-tier-2', 'kwh-tier-3');
        barFill.classList.add(`kwh-tier-${budgetState.kwhTier}`);
        barFill.classList.toggle('over', budgetState.over);
        barFill.classList.toggle('over-budget', budgetState.overBudget && !budgetState.over);
      }
      if (budgetValEl) {
        budgetValEl.textContent = budgetState.showBar
          ? `${budgetState.usedKwh.toFixed(2)} kWh`
          : '—';
      }
      if (budgetSubEl) {
        budgetSubEl.textContent = this._budgetBarSubtitle(budgetState);
      }
      const maxIv = budgetState.maxInterval;
      roomCard.querySelectorAll('.room-budget-marker-wrap[data-kwh]').forEach((el) => {
        const v = Number(el.dataset.kwh);
        if (!budgetState.showBar || !Number.isFinite(v)) return;
        if (budgetState.boost && v < budgetState.effKwh - 1e-6) {
          el.style.display = 'none';
          return;
        }
        if (
          !budgetState.boost &&
          budgetState.baseKwh > 0 &&
          v < budgetState.baseKwh - 1e-6
        ) {
          el.style.display = 'none';
          return;
        }
        el.style.display = '';
        const pct = Math.min(100, (v / maxIv) * 100);
        el.style.left = `${pct}%`;
      });
      const budgetOnlyWrap = roomCard.querySelector(
        '.room-budget-marker-wrap[data-marker-role="budget"]',
      );
      if (budgetOnlyWrap) {
        if (
          budgetState.showSeparateBudget &&
          budgetState.budgetMarkerPct != null &&
          budgetState.showBar
        ) {
          budgetOnlyWrap.style.display = '';
          budgetOnlyWrap.style.left = `${budgetState.budgetMarkerPct}%`;
          budgetOnlyWrap.querySelector('.room-budget-marker-tick')?.setAttribute(
            'title',
            `Daily kWh budget (effective) ${budgetState.effKwh.toFixed(2)} kWh — before phase thresholds`,
          );
        } else {
          budgetOnlyWrap.style.display = 'none';
        }
      }

      // Enforcement badge update
      const pe = this._config?.power_enforcement || {};
      const enfOn = pe.enabled && (pe.rooms_enabled || []).includes(room.id);
      const badge = roomCard.querySelector('.enforcement-badge');
      if (badge && enfOn) {
        const p = typeof room.enforcement_phase === 'number'
          ? Math.max(0, Math.min(2, room.enforcement_phase))
          : 0;
        badge.className = `enforcement-badge enforcement-phase-${p} enforcement-badge--inline has-tooltip`;
        badge.setAttribute('title', ENFORCEMENT_PHASE_TITLES[p]);
        const lbl = badge.querySelector('.enforcement-badge-label');
        if (lbl) lbl.textContent = ENFORCEMENT_BADGE_LABELS[p];
      }

      // Update per-room event counts (W / S / C chips)
      const wEl = roomCard.querySelector('.event-count[data-event="warnings"]');
      const sEl = roomCard.querySelector('.event-count[data-event="shutoffs"]');
      const pEl = roomCard.querySelector('.event-count[data-event="power_cycles"]');
      if (wEl) wEl.textContent = `W ${room.warnings || 0}`;
      if (sEl) sEl.textContent = `S ${room.shutoffs || 0}`;
      if (pEl) pEl.textContent = `C ${room.power_cycles || 0}`;

      const ratingBtn = roomCard.querySelector('.room-header-rating:not(.room-header-rating--loading)');
      if (ratingBtn) {
        const rat = room.ratings;
        const starValue =
          rat != null && rat.stars != null && Number.isFinite(Number(rat.stars))
            ? Number(rat.stars)
            : 0;
        const prefix = `u_${String(cardId).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
        const wrap = ratingBtn.querySelector('.room-efficiency-stars');
        if (wrap) {
          wrap.innerHTML = this._formatEfficiencyStarsSvg(starValue, prefix);
        }
      }

      const presEl = roomCard.querySelector('.room-name-presence');
      const cycleH3 = roomCard.querySelector('.room-name--cycling');
      if (presEl && roomConfig?.presence_person_entity) {
        const rawEnt = String(roomConfig.presence_person_entity).trim();
        const key = rawEnt.toLowerCase();
        const ps =
          this._hass?.states?.[key] || this._hass?.states?.[rawEnt];
        const plainPresence = this._presenceLabelFromPersonState(ps);
        presEl.textContent = plainPresence;
        if (cycleH3) {
          const rn = roomConfig.name || cardId;
          cycleH3.setAttribute('aria-label', `Alternates: ${rn}, then ${plainPresence}`);
        }
      }

      // Update individual devices
      (room.outlets || []).forEach((outlet, i) => {
        const deviceCard = roomCard.querySelector(`[data-outlet-index="${i}"]`);
        if (!deviceCard) return;

        const deviceConfig = roomConfig?.outlets?.[i];
        const deviceThreshold = deviceConfig?.threshold || 0;
        const deviceType = deviceConfig?.type || 'outlet';
        const isSingleOutlet = deviceType === 'single_outlet';
        const isMinisplit = deviceType === 'minisplit';
        const isFridge = deviceType === 'fridge';
        const isVentLike = isVentLikeType(deviceType);
        const isAppliance = deviceType === 'stove' || deviceType === 'microwave';
        const outletTotal = isAppliance || isSingleOutlet || isMinisplit || isFridge || isVentLike
          ? outlet.plug1.watts
          : outlet.plug1.watts + outlet.plug2.watts;

        const plug1Watts = deviceCard.querySelector('.plug1-watts');
        const plug2Watts = deviceCard.querySelector('.plug2-watts');
        const outletTotalEl = deviceCard.querySelector('.outlet-total');
        const mwLcdWatts = deviceCard.querySelector('.mw-lcd-watts');
        const stoveDoorWatts = deviceCard.querySelector('.stove-door-watts');
        const msLcdWatts = deviceCard.querySelector('.ms-lcd-watts');

        if (plug1Watts) plug1Watts.textContent = `${outlet.plug1.watts.toFixed(1)}W`;
        if (plug2Watts) plug2Watts.textContent = `${outlet.plug2.watts.toFixed(1)}W`;
        if (mwLcdWatts) {
          mwLcdWatts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
          mwLcdWatts.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        if (msLcdWatts) {
          msLcdWatts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
          msLcdWatts.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        if (stoveDoorWatts) {
          stoveDoorWatts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
          stoveDoorWatts.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        const stoveTimerEl = deviceCard.querySelector('.stove-timer-remaining');
        if (stoveTimerEl && deviceType === 'stove') {
          const line = this._formatStoveTimerRemaining(outlet.timer_phase, outlet.time_remaining);
          if (line) {
            stoveTimerEl.textContent = line;
            stoveTimerEl.style.display = '';
          } else {
            stoveTimerEl.textContent = '';
            stoveTimerEl.style.display = 'none';
          }
        }
        if (outletTotalEl && deviceType !== 'light') {
          outletTotalEl.textContent = `${outletTotal.toFixed(1)} W`;
          outletTotalEl.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        if (isAppliance) {
          const mwBody = deviceCard.querySelector('.mw-body');
          if (mwBody) mwBody.classList.toggle('mw-on', outlet.plug1.watts > 0.1);
          if (deviceType === 'stove') {
            const active = outlet.plug1.watts > 0.1;
            const ovenDoor = deviceCard.querySelector('.stove-oven-door');
            const firstKnob = deviceCard.querySelector('.stove-knob');
            if (ovenDoor) ovenDoor.classList.toggle('active', active);
            if (firstKnob) firstKnob.classList.toggle('active', active);
          }
        }
        if (isMinisplit) {
          const msUnit = deviceCard.querySelector('.ms-unit');
          if (msUnit) msUnit.classList.toggle('ms-on', outlet.plug1.watts > 0.1);
        }
        if (isVentLike) {
          const cvWatts = deviceCard.querySelector('.ceiling-vent-watts');
          if (cvWatts) {
            const cvFmt = this._formatCeilingVentWatts(outlet.plug1.watts);
            cvWatts.textContent = cvFmt.text;
            if (cvFmt.title) cvWatts.setAttribute('title', cvFmt.title);
            else cvWatts.removeAttribute('title');
            cvWatts.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
          }
          const ventBody = deviceCard.querySelector('.ceiling-vent-body');
          if (ventBody) ventBody.classList.toggle('vent-on', outlet.plug1.watts > 0.1);
          if (deviceType === 'wall_heater') {
            const nowEl = deviceCard.querySelector('.heater-dash-now-val');
            const thEl = deviceCard.querySelector('.heater-dash-threshold-val');
            const timerEl = deviceCard.querySelector('.heater-dash-timer');
            const runRow = deviceCard.querySelector('.heater-dash-row-run');
            if (nowEl) {
              const ct = outlet.heater_current_temperature;
              nowEl.textContent = ct != null && ct !== '' && !Number.isNaN(Number(ct))
                ? `${Number(ct).toFixed(1)}°`
                : '—';
            }
            if (thEl) {
              const b = outlet.heater_on_below_temperature ?? deviceConfig?.heater_on_below_temperature ?? 65;
              const bd = Number(b) % 1 === 0 ? 0 : 1;
              thEl.textContent = `${Number(b).toFixed(bd)}°`;
            }
            const tr = this._formatHeaterRunRemaining(outlet.heater_time_remaining_sec);
            if (timerEl) timerEl.textContent = tr;
            if (runRow) runRow.style.display = tr ? '' : 'none';
          }
        }
        if (isFridge) {
          const fridgeW = deviceCard.querySelector('.fridge-watts');
          if (fridgeW) {
            fridgeW.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
            fridgeW.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
          }
          const fridgeBody = deviceCard.querySelector('.fridge-body');
          if (fridgeBody) fridgeBody.classList.toggle('fridge-on', outlet.plug1.watts > 0.1);
        }
        if (deviceType === 'light') {
          const isOn = outlet.switch_state === true;
          const totalWatts = isOn ? (outlet.plug1?.watts || 0) : 0;
          const lightLever = deviceCard.querySelector('.light-toggle-lever');
          const lightLabel = deviceCard.querySelector('.light-toggle-label');
          const lightWattsDisplay = deviceCard.querySelector('.light-watts-display');
          const lightSwitchPlate = deviceCard.querySelector('.light-switch-plate');
          if (lightLever) {
            lightLever.classList.toggle('on', isOn);
            lightLever.classList.toggle('off', !isOn);
          }
          if (lightLabel) lightLabel.textContent = isOn ? 'ON' : 'OFF';
          if (lightWattsDisplay) {
            lightWattsDisplay.textContent = `${totalWatts.toFixed(1)} W`;
          }
          if (lightSwitchPlate) lightSwitchPlate.classList.toggle('active', isOn);
          deviceCard.classList.toggle('light-on', isOn);
        }
      });
    });

    this._scheduleSummaryStatFit();
    this._scheduleRoomHeaderTitleFit();
  }

  _scheduleSummaryStatFit() {
    const run = () => this._fitSummaryStatValues();
    run();
    if (this._summaryFitRaf != null) cancelAnimationFrame(this._summaryFitRaf);
    this._summaryFitRaf = requestAnimationFrame(() => {
      this._summaryFitRaf = null;
      run();
      requestAnimationFrame(run);
    });
    if (this._summaryFitDebounce != null) clearTimeout(this._summaryFitDebounce);
    this._summaryFitDebounce = setTimeout(() => {
      this._summaryFitDebounce = null;
      run();
    }, 150);
  }

  _fitSummaryStatValues() {
    const root = this.shadowRoot?.querySelector('.summary-stats');
    if (!root) return;
    const values = [...root.querySelectorAll('.stat-value')];
    if (!values.length) return;
    if (values.some((el) => el.clientWidth <= 0)) {
      if (this._summaryFitZeroRetry != null) clearTimeout(this._summaryFitZeroRetry);
      this._summaryFitZeroRetry = setTimeout(() => {
        this._summaryFitZeroRetry = null;
        this._fitSummaryStatValues();
      }, 100);
      return;
    }
    const minPx = 5.5;
    const maxPx = 17;
    const step = 0.5;
    const pad = 1;
    const applyPx = (px) => {
      root.style.setProperty('--summary-stat-value-px', `${px}px`);
      values.forEach((el) => {
        el.style.fontSize = `${px}px`;
      });
      void root.offsetWidth;
    };
    const fits = (px) => {
      applyPx(px);
      return values.every(
        (el) => el.scrollWidth <= el.clientWidth + pad && el.clientWidth > 0,
      );
    };
    if (fits(maxPx)) return;
    for (let px = maxPx - step; px >= minPx; px -= step) {
      if (fits(px)) return;
    }
    applyPx(minPx);
  }

  _syncRoomsGridTitleFitObserver() {
    if (this._roomsGridResizeObserver) {
      this._roomsGridResizeObserver.disconnect();
      this._roomsGridResizeObserver = null;
    }
    if (this._dashboardView !== 'rooms' || this._showSettings) return;
    const grid = this.shadowRoot?.querySelector('.rooms-grid');
    if (!grid) return;
    this._roomsGridResizeObserver = new ResizeObserver(() => {
      this._scheduleRoomHeaderTitleFit();
    });
    this._roomsGridResizeObserver.observe(grid);
  }

  _scheduleRoomHeaderTitleFit() {
    if (this._dashboardView !== 'rooms' || this._showSettings) return;
    if (this._roomTitleFitRaf != null) cancelAnimationFrame(this._roomTitleFitRaf);
    this._roomTitleFitGen += 1;
    const gen = this._roomTitleFitGen;
    this._roomTitleFitRaf = requestAnimationFrame(() => {
      this._roomTitleFitRaf = requestAnimationFrame(() => {
        this._roomTitleFitRaf = null;
        if (gen !== this._roomTitleFitGen) return;
        this._fitRoomHeaderTitles();
      });
    });
  }

  _fitRoomHeaderTitles() {
    const root = this.shadowRoot;
    if (!root || this._dashboardView !== 'rooms' || this._showSettings) return;
    const MIN_PX = 9;
    const MAX_PX = 16;
    const STEP = 0.5;
    const PAD = 1;

    root.querySelectorAll('.room-header-title-wrap').forEach((wrap) => {
      const nameEl = wrap.querySelector('.room-name');
      if (!nameEl || wrap.clientWidth <= 0) return;

      nameEl.classList.remove('room-name--trunc-floor');
      nameEl.style.fontSize = '';

      const cycling = nameEl.classList.contains('room-name--cycling');
      const textEl = nameEl.querySelector('.room-name-text');
      const presEl = nameEl.querySelector('.room-name-presence');

      const fitsAt = (px) => {
        nameEl.style.fontSize = `${px}px`;
        void wrap.offsetWidth;
        const cw = nameEl.clientWidth;
        if (cw <= 0) return true;
        if (cycling && textEl && presEl) {
          const need = Math.max(textEl.scrollWidth, presEl.scrollWidth);
          return need <= cw + PAD;
        }
        return nameEl.scrollWidth <= cw + PAD;
      };

      let best = MIN_PX;
      for (let px = MAX_PX; px >= MIN_PX - 1e-9; px -= STEP) {
        const rounded = Math.round(px * 2) / 2;
        if (fitsAt(rounded)) {
          best = rounded;
          break;
        }
      }

      nameEl.style.fontSize = `${best}px`;
      void nameEl.offsetWidth;
      const cw = nameEl.clientWidth;
      const overflow =
        cw > 0 &&
        (cycling && textEl && presEl
          ? Math.max(textEl.scrollWidth, presEl.scrollWidth) > cw + PAD
          : nameEl.scrollWidth > cw + PAD);
      if (overflow) nameEl.classList.add('room-name--trunc-floor');
    });
  }

  _attachSummaryStatsResize() {
    if (this._summaryStatsResizeObs) {
      this._summaryStatsResizeObs.disconnect();
      this._summaryStatsResizeObs = null;
    }
    const el = this.shadowRoot?.querySelector('.summary-stats');
    if (!el) return;
    this._summaryStatsResizeObs = new ResizeObserver(() => {
      this._scheduleSummaryStatFit();
    });
    this._summaryStatsResizeObs.observe(el);
    if (!this._summaryStatsWindowResizeBound) {
      this._summaryStatsWindowResizeBound = () => this._scheduleSummaryStatFit();
      window.addEventListener('resize', this._summaryStatsWindowResizeBound);
    }
  }

  _attachRoomContentWheelScroll() {
    const roomContents = this.shadowRoot.querySelectorAll('.room-content');
    roomContents.forEach(el => {
      if (el._wheelScrollAttached) return;
      el._wheelScrollAttached = true;
      el.addEventListener('wheel', (e) => {
        if (el.scrollWidth > el.clientWidth) {
          e.preventDefault();
          el.scrollLeft += e.deltaY;
        }
      }, { passive: false });
    });
  }

  _getRoomConfig(roomId) {
    const rooms = this._config?.rooms || [];
    return rooms.find(
      (r) => r.id === roomId || this._canonicalRoomId(r) === roomId,
    );
  }

  /** Matches server `canonical_room_id` in room_ratings.py */
  _canonicalRoomId(room) {
    if (!room || typeof room !== 'object') return '';
    const id = room.id;
    if (id != null && String(id).trim() !== '') {
      return String(id).trim();
    }
    return String(room.name || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '_');
  }

  _render() {
    const styles = `
      ${sharedStyles}
      ${passcodeModalStyles}
      
      .summary-stats {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: clamp(4px, 1.2vw, 10px);
        margin-bottom: 12px;
        overflow-x: hidden;
        width: 100%;
        container-type: inline-size;
        --summary-stat-value-px: clamp(9px, 2.1vw + 0.28rem, 17px);
      }

      .stat-card {
        min-width: 0;
        background: var(--card-bg);
        border-radius: 8px;
        border: 1px solid var(--card-border);
        padding: clamp(5px, 1.4vw, 12px) clamp(2px, 0.9vw, 10px);
        text-align: center;
      }
      .stat-card.graph-clickable, .graph-clickable {
        cursor: pointer;
      }
      .stat-card.graph-clickable:hover, .graph-clickable:hover {
        opacity: 0.9;
      }

      .stat-value {
        font-size: clamp(11px, 2.6vw + 0.35rem, 17px);
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        line-height: 1.15;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
      }

      .summary-stats .stat-value {
        font-size: var(--summary-stat-value-px);
        text-overflow: clip;
        overflow: hidden;
        max-width: 100%;
        box-sizing: border-box;
      }

      .stat-label {
        font-size: clamp(6px, 1.65vw + 0.12rem, 9px);
        color: var(--secondary-text-color);
        margin-top: clamp(2px, 0.5vw, 3px);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .view-tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 16px;
        background: var(--secondary-background-color);
        padding: 4px;
        border-radius: 8px;
      }

      .view-tab {
        flex: 1;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--disabled-text-color);
        cursor: pointer;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        transition: all 0.2s;
      }

      .view-tab:hover {
        background: rgba(255, 255, 255, 0.05);
      }

      .view-tab.active {
        background: var(--panel-accent);
        color: white;
      }

      .statistics-view-shell {
        position: relative;
        min-height: 180px;
      }
      .statistics-loading-overlay {
        position: absolute;
        inset: 0;
        z-index: 10;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.42);
        border-radius: 10px;
        backdrop-filter: blur(3px);
      }
      .statistics-loading-inner {
        text-align: center;
        padding: 20px 24px;
        max-width: 320px;
      }
      .statistics-loading-spinner {
        width: 36px;
        height: 36px;
        margin: 0 auto 12px;
        border: 3px solid rgba(255,255,255,0.15);
        border-top-color: var(--panel-accent, #03a9f4);
        border-radius: 50%;
        animation: statistics-spin 0.85s linear infinite;
      }
      @keyframes statistics-spin {
        to { transform: rotate(360deg); }
      }
      .statistics-loading-title {
        margin: 0 0 8px;
        font-size: 14px;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .statistics-loading-sub {
        margin: 0;
        font-size: 12px;
        line-height: 1.4;
        color: var(--secondary-text-color);
      }
      .statistics-loading-err {
        margin: 10px 0 0;
        font-size: 12px;
        color: #ff8a80;
      }
      .statistics-chart-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
      }
      .btn-stat-chart {
        font-size: 12px;
        padding: 8px 12px;
        border-radius: 8px;
        border: 1px solid var(--card-border);
        background: rgba(255,255,255,0.06);
        color: var(--panel-accent);
        cursor: pointer;
        font-weight: 500;
      }
      .btn-stat-chart:hover {
        background: rgba(255,255,255,0.1);
      }
      .btn-stat-chart:disabled {
        opacity: 0.45;
        cursor: not-allowed;
      }
      .btn-stat-chart-sm {
        font-size: 10px;
        padding: 4px 8px;
        margin-left: 6px;
        vertical-align: middle;
      }
      .statistics-view {
        display: flex;
        flex-direction: column;
        gap: clamp(12px, 3vw, 20px);
        padding: 0 4px;
      }
      .statistics-banner {
        font-size: clamp(12px, 2.5vw, 14px);
        color: var(--secondary-text-color);
        padding: 8px 12px;
        background: var(--input-bg);
        border-radius: 8px;
        border: 1px solid var(--card-border);
      }
      .statistics-banner-row {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 6px 10px;
      }
      .statistics-banner-label {
        font-weight: 600;
        color: var(--primary-text-color);
        letter-spacing: 0.02em;
      }
      .statistics-range {
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .statistics-narrowed { font-size: 11px; opacity: 0.9; }
      .statistics-pending-banner {
        margin-top: 8px;
        font-size: 12px;
        line-height: 1.35;
        color: var(--primary-color, #03a9f4);
        opacity: 0.95;
      }
      .statistics-cards {
        display: block;
        width: 100%;
        max-width: 100%;
        margin: 0 auto;
      }
      .statistics-rooms-fullbleed {
        max-width: 100%;
        width: 100%;
      }
      .statistics-overview-card,
      .statistics-rooms-card {
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        padding: clamp(12px, 3vw, 16px);
      }
      .statistics-overview-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: clamp(16px, 3vw, 20px);
      }
      @media (min-width: 640px) {
        .statistics-overview-grid {
          grid-template-columns: minmax(0, 1fr) minmax(0, 1.12fr);
          gap: 0;
          align-items: start;
        }
        .statistics-overview-grid--tracked-only {
          grid-template-columns: minmax(0, 1fr);
        }
        .statistics-overview-grid--tracked-only .statistics-overview-col--tracked {
          border-left: none;
          padding-left: 0;
        }
        .statistics-overview-col--supplier {
          padding-right: clamp(14px, 3vw, 22px);
        }
        .statistics-overview-col--tracked {
          border-left: 1px solid var(--card-border);
          padding-left: clamp(14px, 3vw, 22px);
        }
      }
      .statistics-supplier-updated {
        font-size: 10px;
        color: var(--secondary-text-color);
        margin: 10px 0 0;
        line-height: 1.35;
        opacity: 0.92;
      }
      .sensor-diagnostic {
        font-size: 10px;
        color: var(--warning-color, #f0a30a);
        font-weight: 400;
        margin-left: 4px;
      }
      .statistics-card-title { font-size: 13px; font-weight: 600; margin: 0 0 4px; color: var(--primary-text-color); }
      .statistics-card-sub { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--panel-accent); margin: 0 0 8px; }
      .statistics-kpi-big {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        margin-bottom: 10px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--card-border);
      }
      .statistics-kpi-big .val { font-size: clamp(17px, 4vw + 0.5rem, 28px); font-weight: 700; font-variant-numeric: tabular-nums; color: var(--primary-text-color); line-height: 1.1; }
      .statistics-kpi-big .lbl { font-size: 11px; color: var(--secondary-text-color); }
      .statistics-sensor-grid,
      .statistics-totals-grid {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .statistics-sensor-item,
      .statistics-total-item {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
      }
      .statistics-sensor-label,
      .statistics-total-label { font-size: 11px; color: var(--secondary-text-color); }
      .statistics-sensor-sublabel { font-weight: 500; opacity: 0.75; font-size: 10px; }
      .statistics-sensor-value,
      .statistics-total-value { font-size: 13px; font-weight: 500; }
      .statistics-table-wrap {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        margin: 0 -4px;
        padding: 0 4px;
      }
      .statistics-table { width: 100%; min-width: 720px; border-collapse: collapse; font-size: clamp(11px, 2.4vw, 12px); }
      .statistics-table th, .statistics-table td { padding: clamp(6px, 1.5vw, 10px) clamp(6px, 2vw, 10px); text-align: left; border-bottom: 1px solid var(--card-border); }
      .statistics-table th { font-weight: 600; color: var(--secondary-text-color); }
      .statistics-table th abbr { text-decoration: none; border-bottom: 1px dotted var(--secondary-text-color); cursor: help; }
      .statistics-empty { color: var(--secondary-text-color); text-align: center; padding: 16px !important; }

      .stat-rooms-segment-wrap {
        display: flex;
        gap: 4px;
        margin: 0 0 12px;
        padding: 4px;
        background: rgba(0, 0, 0, 0.18);
        border-radius: 8px;
        border: 1px solid var(--card-border);
      }
      .stat-rooms-segment {
        flex: 1;
        padding: 8px 12px;
        border: none;
        border-radius: 6px;
        background: transparent;
        color: var(--secondary-text-color);
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s, color 0.2s;
      }
      .stat-rooms-segment:hover {
        background: rgba(255, 255, 255, 0.06);
        color: var(--primary-text-color);
      }
      .stat-rooms-segment.active {
        background: var(--panel-accent);
        color: #fff;
      }
      .stat-rooms-panel { min-width: 0; }
      .stat-rooms-pie-mount {
        min-height: 280px;
        width: 100%;
      }
      .statistics-pie-empty,
      .stat-pie-caption {
        font-size: 11px;
        color: var(--secondary-text-color);
        text-align: center;
        margin: 0;
        padding: 12px 8px 0;
        line-height: 1.4;
      }
      .statistics-pie-empty {
        padding: 32px 16px;
      }
      .stat-pie-selection {
        margin-top: 12px;
        padding: 12px;
        border-radius: 8px;
        background: var(--input-bg);
        border: 1px solid var(--card-border);
        font-size: 12px;
        color: var(--primary-text-color);
        line-height: 1.45;
      }
      .stat-pie-selection-title {
        font-weight: 600;
        margin: 0 0 6px;
        font-size: 13px;
      }
      .stat-pie-selection-meta {
        margin: 0;
        color: var(--secondary-text-color);
        font-size: 11px;
      }
      .stat-pie-selection-actions {
        margin-top: 10px;
      }

      .rooms-grid {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .room-card {
        container-type: inline-size;
        container-name: roomCard;
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        overflow: visible;
        height: fit-content;
        width: 100%;
        --room-card-edge-padding: clamp(6px, 1.6vw, 10px) clamp(8px, 2vw, 12px);
        --room-card-rail-min-h: clamp(26px, 5.5vw, 36px);
      }

      /* ===== Room header: single rail (height aligned with footer budget strip) ===== */
      .room-header {
        padding: var(--room-card-edge-padding);
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
        border-radius: 10px 10px 0 0;
        overflow: visible;
      }

      /* Single rail: matches footer bar row height (no second meta row) */
      .room-header-inner.room-header-rail {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr) auto auto;
        align-items: center;
        gap: clamp(3px, 0.9cqi + 0.2rem, 8px);
        min-width: 0;
        min-height: var(--room-card-rail-min-h);
        box-sizing: border-box;
      }

      .room-header-title-wrap {
        display: flex;
        flex-direction: row;
        flex-wrap: nowrap;
        align-items: center;
        gap: clamp(2px, 0.75cqi + 0.15rem, 6px);
        min-width: 0;
        overflow: hidden;
      }

      .room-header-title-wrap .room-name {
        flex: 1 1 auto;
        min-width: 0;
      }

      .room-header-title-wrap .room-header-rating {
        flex-shrink: 0;
      }

      .room-header-title-wrap .room-header-badges {
        flex-shrink: 0;
      }

      .room-header-rail .room-event-chips {
        flex-shrink: 0;
      }

      .room-header-rating {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: clamp(2px, 0.5vw, 4px);
        padding: 2px 4px;
        margin: 0;
        border: none;
        background: transparent;
        cursor: pointer;
        font: inherit;
        color: var(--primary-text-color);
        text-align: center;
        min-width: 0;
        width: auto;
        max-width: 100%;
        flex-shrink: 0;
        border-radius: 6px;
      }

      .room-header-rating:hover:not(:disabled) {
        background: rgba(255, 255, 255, 0.04);
      }

      .room-header-rating:focus-visible {
        outline: 2px solid var(--panel-accent);
        outline-offset: 2px;
      }

      .room-header-rating:disabled {
        cursor: default;
        opacity: 0.85;
      }

      .room-header-rating--error .room-efficiency-placeholder {
        color: var(--secondary-text-color);
        font-size: clamp(10px, 2.2vw, 13px);
        font-weight: 700;
        line-height: 1;
        min-width: 1em;
        text-align: center;
      }

      .room-header-rating--loading .room-efficiency-placeholder {
        color: var(--secondary-text-color);
        font-size: clamp(12px, 2.6vw, 16px);
        letter-spacing: 0.12em;
        font-weight: 700;
        opacity: 0.55;
        line-height: 1;
        animation: room-rating-dots 1.1s ease-in-out infinite;
      }

      @keyframes room-rating-dots {
        0%, 100% { opacity: 0.35; }
        50% { opacity: 0.85; }
      }

      @media (prefers-reduced-motion: reduce) {
        .room-header-rating--loading .room-efficiency-placeholder {
          animation: none;
          opacity: 0.65;
        }
      }

      .stat-efficiency-cell {
        white-space: nowrap;
        vertical-align: middle;
      }
      .stat-room-efficiency-rating {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 2px;
        padding: 4px 6px;
        margin: 0;
        border: none;
        border-radius: 8px;
        background: transparent;
        cursor: pointer;
        color: inherit;
        font: inherit;
      }
      .stat-room-efficiency-rating:hover {
        background: rgba(255, 255, 255, 0.06);
      }
      .stat-room-efficiency-rating:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .stat-room-efficiency-stars .room-efficiency-star {
        width: 14px;
        height: 14px;
      }

      .room-rating-modal-overlay {
        position: fixed;
        inset: 0;
        z-index: 10050;
        background: rgba(0, 0, 0, 0.55);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: clamp(8px, 3vw, 20px);
        box-sizing: border-box;
      }

      .room-rating-modal-dialog {
        background: var(--card-bg, #1c1c1c);
        border: 1px solid var(--card-border);
        border-radius: clamp(14px, 3vw, 20px);
        max-width: min(440px, 100%);
        max-height: min(92vh, 720px);
        overflow: auto;
        box-shadow:
          0 0 0 1px rgba(0, 0, 0, 0.4),
          0 24px 56px rgba(0, 0, 0, 0.5);
        padding: 0;
      }

      .room-rating-modal-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        padding: clamp(18px, 4vw, 24px) clamp(18px, 4vw, 24px) clamp(10px, 2vw, 14px);
        background: var(--panel-header-background, var(--card-bg, #1c1c1c));
        border-bottom: 1px solid var(--card-border);
      }

      .room-rating-modal-header-text {
        min-width: 0;
        flex: 1;
      }

      .room-rating-modal-eyebrow {
        margin: 0 0 6px 0;
        font-size: clamp(10px, 2.2vw, 11px);
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--panel-accent, #29b6f6);
        opacity: 0.95;
      }

      .room-rating-modal-room {
        margin: 0;
        font-size: clamp(20px, 4.8vw, 26px);
        font-weight: 800;
        line-height: 1.15;
        letter-spacing: -0.03em;
        color: var(--primary-text-color);
        word-break: break-word;
      }

      .room-rating-modal-close {
        border: 1px solid var(--input-border);
        background: var(--secondary-background-color);
        color: var(--secondary-text-color);
        font-size: 20px;
        line-height: 1;
        cursor: pointer;
        padding: 8px 10px;
        border-radius: 10px;
        flex-shrink: 0;
        margin: -4px -4px 0 0;
        transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
      }

      .room-rating-modal-close:hover {
        background: var(--input-bg, var(--secondary-background-color));
        border-color: var(--card-border);
        color: var(--primary-text-color);
      }

      .room-rating-modal-close:focus-visible {
        outline: 2px solid var(--panel-accent);
        outline-offset: 2px;
      }

      .room-rating-modal-hero {
        text-align: center;
        padding: clamp(16px, 3.5vw, 22px) clamp(18px, 4vw, 24px) clamp(18px, 3.5vw, 22px);
        background-color: var(--card-bg, #1c1c1c);
        background-image: radial-gradient(
          ellipse 70% 55% at 50% 0%,
          var(--panel-accent-dim, rgba(3, 169, 244, 0.15)) 0%,
          transparent 60%
        );
        border-bottom: 1px solid var(--card-border);
      }

      .room-rating-modal-hero-intro {
        margin: clamp(12px, 2.5vw, 16px) auto 0;
        max-width: 34em;
        font-size: clamp(11px, 2.4vw, 13px);
        font-weight: 500;
        line-height: 1.45;
        color: var(--secondary-text-color);
        text-align: center;
      }

      .room-rating-modal-stars {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-wrap: wrap;
        gap: clamp(4px, 1.2vw, 10px);
        margin: 0 0 clamp(10px, 2vw, 14px) 0;
      }

      .room-rating-modal-stars .room-efficiency-star {
        width: clamp(28px, 7vw, 36px);
        height: clamp(28px, 7vw, 36px);
        filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.35));
      }

      .room-rating-modal-index {
        display: flex;
        align-items: baseline;
        justify-content: center;
        gap: 4px;
        font-variant-numeric: tabular-nums;
      }

      .room-rating-modal-index-value {
        font-size: clamp(26px, 6vw, 34px);
        font-weight: 800;
        letter-spacing: -0.03em;
        color: var(--primary-text-color);
        line-height: 1;
      }

      .room-rating-modal-index-suffix {
        font-size: clamp(13px, 3vw, 15px);
        font-weight: 600;
        color: var(--secondary-text-color);
        opacity: 0.85;
      }

      .room-rating-modal-index-caption {
        margin: 6px 0 0 0;
        font-size: clamp(11px, 2.4vw, 12px);
        color: var(--secondary-text-color);
        font-weight: 500;
        letter-spacing: 0.02em;
      }

      .room-rating-modal-body {
        display: flex;
        flex-direction: column;
        gap: clamp(10px, 2vw, 12px);
        padding: clamp(14px, 3vw, 18px) clamp(18px, 4vw, 24px) clamp(6px, 1.5vw, 10px);
        background: var(--card-bg, #1c1c1c);
      }

      .room-rating-modal-metric {
        padding: clamp(12px, 2.5vw, 14px) clamp(14px, 3vw, 16px);
        border-radius: 12px;
        background: var(--secondary-background-color);
        border: 1px solid var(--card-border);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
      }

      .room-rating-modal-metric-top {
        display: flex;
        flex-direction: row;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 10px;
      }

      .room-rating-modal-metric-text {
        min-width: 0;
        flex: 1;
        text-align: left;
      }

      .room-rating-modal-metric-kicker {
        display: block;
        font-size: clamp(9px, 2vw, 10px);
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        margin-bottom: 4px;
      }

      .room-rating-modal-metric-title {
        display: block;
        font-size: clamp(13px, 2.8vw, 15px);
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--primary-text-color);
        line-height: 1.25;
      }

      .room-rating-modal-metric-status {
        display: block;
        margin-top: 4px;
        font-size: clamp(10px, 2.2vw, 12px);
        font-weight: 600;
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .room-rating-modal-metric-desc {
        display: block;
        margin-top: 5px;
        font-size: clamp(10px, 2.2vw, 12px);
        font-weight: 500;
        line-height: 1.35;
        color: var(--secondary-text-color);
      }

      .room-rating-modal-metric-value {
        font-size: clamp(22px, 5vw, 28px);
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        line-height: 1;
        color: var(--panel-accent, #29b6f6);
        flex-shrink: 0;
        text-shadow: 0 0 24px rgba(3, 169, 244, 0.25);
      }

      .room-rating-modal-metric-bar {
        height: clamp(11px, 2.4vw, 14px);
        border-radius: 999px;
        background: var(--card-bg, #111);
        border: 1px solid var(--card-border);
        overflow: hidden;
        box-sizing: border-box;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.35);
      }

      .room-rating-modal-metric-fill {
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(
          90deg,
          rgba(2, 136, 209, 0.95) 0%,
          var(--panel-accent, #29b6f6) 55%,
          rgba(129, 212, 250, 0.9) 100%
        );
        transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
        box-shadow: 0 0 16px rgba(3, 169, 244, 0.35);
      }

      .room-rating-modal-footnote {
        margin: 0;
        padding: clamp(12px, 2.5vw, 16px) clamp(18px, 4vw, 24px) clamp(16px, 3vw, 20px);
        font-size: clamp(10px, 2.2vw, 11px);
        color: var(--secondary-text-color);
        line-height: 1.4;
        text-align: center;
        opacity: 0.88;
        border-top: 1px solid var(--card-border);
        background: var(--card-bg, #1c1c1c);
      }

      @media (prefers-reduced-motion: reduce) {
        .room-rating-modal-metric-fill {
          transition: none;
        }
      }

      .room-efficiency-stars {
        display: inline-flex;
        align-items: center;
        gap: clamp(1px, 0.35vw, 3px);
        flex-shrink: 0;
      }

      .room-header-rating .room-efficiency-star {
        width: clamp(8px, 2.2cqi + 0.2rem, 14px);
        height: clamp(8px, 2.2cqi + 0.2rem, 14px);
        flex-shrink: 0;
      }

      .room-efficiency-star {
        width: clamp(12px, 3vw, 16px);
        height: clamp(12px, 3vw, 16px);
        flex-shrink: 0;
      }

      .room-header-rail .room-icon {
        flex-shrink: 0;
        align-self: center;
      }

      .room-header-rail .room-icon[title]:not([title=""]) {
        cursor: help;
      }

      .room-header-rail .room-icon.zone-health-issue[title]:not([title=""]) {
        cursor: pointer;
      }

      .room-header-watts-col {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        min-width: 0;
        flex-shrink: 0;
      }

      .room-icon {
        --room-card-icon-inner: clamp(11px, 2.8cqi + 0.25rem, 18px);
        width: clamp(22px, 5.5cqi + 0.5rem, 34px);
        height: clamp(22px, 5.5cqi + 0.5rem, 34px);
        border-radius: clamp(5px, 1.2vw, 8px);
        background: rgba(255, 255, 255, 0.06);
        display: grid;
        place-items: center;
        flex-shrink: 0;
        line-height: 0;
        box-sizing: border-box;
      }

      .room-icon svg {
        width: var(--room-card-icon-inner);
        height: var(--room-card-icon-inner);
        fill: var(--panel-accent);
        display: block;
      }

      .room-icon ha-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: var(--room-card-icon-inner);
        height: var(--room-card-icon-inner);
        color: var(--panel-accent);
        flex-shrink: 0;
        --mdc-icon-size: var(--room-card-icon-inner);
        --ha-icon-size: var(--room-card-icon-inner);
      }

      @keyframes zone-health-pulse {
        0%, 100% { color: var(--panel-accent, #03a9f4); }
        50% { color: #ff9800; }
      }

      .room-icon.zone-health-issue {
        cursor: pointer;
      }

      .room-icon.zone-health-issue ha-icon {
        animation: zone-health-pulse 2s ease-in-out infinite;
      }

      @media (prefers-reduced-motion: reduce) {
        .room-icon.zone-health-issue ha-icon {
          animation: none;
          color: #ff9800;
        }
      }

      .room-header-title-col {
        display: flex;
        flex-direction: column;
        gap: clamp(2px, 0.5vw, 4px);
        min-width: 0;
        flex: 0 1 auto;
      }

      .room-name {
        margin: 0;
        font-size: clamp(9px, 2.8cqi + 0.35rem, 16px);
        font-weight: 700;
        line-height: 1.15;
        letter-spacing: -0.01em;
        min-width: 0;
        flex: 1 1 auto;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: clip;
      }

      .room-name.room-name--trunc-floor {
        text-overflow: ellipsis;
      }

      .room-name--cycling {
        position: relative;
      }

      .room-name--cycling .room-name-text,
      .room-name--cycling .room-name-presence {
        display: block;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: clip;
      }

      .room-name--cycling.room-name--trunc-floor .room-name-text,
      .room-name--cycling.room-name--trunc-floor .room-name-presence {
        text-overflow: ellipsis;
      }

      .room-name--cycling .room-name-presence {
        position: absolute;
        left: 0;
        top: 0;
        right: 0;
        opacity: 0;
        pointer-events: none;
        animation: roomPresenceCycle 10s ease-in-out infinite;
      }

      .room-name--cycling .room-name-text {
        animation: roomNameCycle 10s ease-in-out infinite;
      }

      @keyframes roomNameCycle {
        0%, 42% { opacity: 1; }
        50%, 92% { opacity: 0; }
        100% { opacity: 1; }
      }

      @keyframes roomPresenceCycle {
        0%, 42% { opacity: 0; }
        50%, 92% { opacity: 1; }
        100% { opacity: 0; }
      }

      @media (prefers-reduced-motion: reduce) {
        .room-name--cycling .room-name-text,
        .room-name--cycling .room-name-presence {
          animation: none;
        }
        .room-name--cycling .room-name-presence {
          display: none;
        }
      }

      @container roomCard (max-width: 320px) {
        .room-header-rail .room-header-badges .room-threshold-pill {
          display: none;
        }
      }

      @container roomCard (max-width: 260px) {
        .room-header-rail {
          gap: clamp(2px, 0.5cqi, 5px);
        }
        .room-header-rail .room-total-watts {
          font-size: clamp(8px, 2.4cqi, 10px);
        }
        .room-header-rail .event-count {
          font-size: clamp(5px, 1.8cqi, 7px);
          padding: 1px clamp(2px, 0.5cqi, 4px);
        }
        .room-header-rail .room-threshold-pill {
          font-size: clamp(5px, 1.8cqi, 7px);
          padding: 1px clamp(2px, 0.5cqi, 5px);
        }
        .room-header-rail .room-header-rating .room-efficiency-star {
          width: clamp(6px, 2cqi, 9px);
          height: clamp(6px, 2cqi, 9px);
        }
        .room-header-rail .enforcement-badge--inline {
          font-size: clamp(5px, 1.8cqi, 7px);
          padding: 1px clamp(2px, 0.5cqi, 4px);
          gap: 2px;
        }
        .room-header-rail .enforcement-badge--inline svg {
          width: clamp(6px, 1.6cqi, 9px);
          height: clamp(6px, 1.6cqi, 9px);
        }
      }

      @container roomCard (max-width: 220px) {
        .room-header-rail .room-threshold-pill {
          display: none;
        }
        .room-header-rail .room-total-watts {
          font-size: clamp(7px, 2.2cqi, 9px);
        }
        .room-header-rail .room-header-rating .room-efficiency-star {
          width: clamp(5px, 1.8cqi, 8px);
          height: clamp(5px, 1.8cqi, 8px);
        }
      }

      @container roomCard (min-width: 261px) and (max-width: 340px) {
        .room-header-rail .room-total-watts {
          font-size: clamp(10px, 3.6cqi, 15px);
        }
        .room-header-rail .event-count {
          font-size: clamp(6px, 2cqi, 9px);
        }
        .room-header-rail .room-threshold-pill {
          font-size: clamp(6px, 2cqi, 9px);
        }
        .room-header-rail .room-header-rating .room-efficiency-star {
          width: clamp(8px, 2.4cqi, 13px);
          height: clamp(8px, 2.4cqi, 13px);
        }
        .room-header-rail .enforcement-badge--inline {
          font-size: clamp(6px, 2cqi, 9px);
        }
      }

      @container roomCard (min-width: 341px) {
        .room-header-rail .room-total-watts {
          font-size: clamp(12px, 2.8cqi + 0.2rem, 17px);
        }
      }

      .room-header-badges {
        display: flex;
        flex-wrap: nowrap;
        align-items: center;
        gap: clamp(3px, 0.9vw, 6px);
        min-height: 0;
        min-width: 0;
      }

      .room-header-badges:empty {
        display: none;
      }

      .room-person-location {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: clamp(10px, 2.3vw, 12px);
        color: var(--secondary-text-color);
        flex-shrink: 0;
        white-space: nowrap;
      }

      .room-person-location ha-icon {
        color: var(--panel-accent);
        flex-shrink: 0;
      }

      .room-person-location .person-name {
        color: var(--primary-text-color);
        font-weight: 500;
      }

      .room-person-location .person-state {
        color: var(--secondary-text-color);
      }

      .room-footer {
        padding: var(--room-card-edge-padding);
        background: linear-gradient(0deg, rgba(255, 255, 255, 0.04) 0%, transparent 100%);
        border-top: 1px solid var(--card-border);
        border-radius: 0 0 10px 10px;
      }

      .room-threshold-pill {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: clamp(7px, 1.7vw, 9px);
        color: var(--secondary-text-color);
        background: rgba(255,255,255,0.06);
        border: 1px solid var(--card-border);
        border-radius: 5px;
        padding: 1px clamp(4px, 1vw, 7px);
      }

      .room-threshold-pill svg {
        width: clamp(8px, 1.8vw, 10px);
        height: clamp(8px, 1.8vw, 10px);
        fill: currentColor;
        flex-shrink: 0;
      }

      .room-budget-section {
        width: 100%;
        overflow: visible;
      }

      .room-budget-bar-track {
        position: relative;
        display: flex;
        align-items: center;
        min-height: var(--room-card-rail-min-h);
        padding: 0 clamp(10px, 2.2vw, 14px);
        margin-bottom: 0;
        border-radius: clamp(9px, 2.2vw, 14px);
        background: var(--secondary-background-color);
        border: 1px solid var(--card-border);
        overflow: hidden;
        box-sizing: border-box;
        box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.22);
        cursor: pointer;
      }

      .room-budget-bar-track.graph-clickable:hover {
        border-color: rgba(3, 169, 244, 0.45);
        box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.22), 0 0 0 1px rgba(3, 169, 244, 0.2);
      }

      .room-budget-bar-fill {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        z-index: 0;
        border-radius: inherit;
        transition: width 0.35s ease, background 0.25s ease;
        min-width: 0;
        pointer-events: none;
      }

      .room-budget-bar-fill.kwh-tier-0 {
        background: linear-gradient(100deg, #0288d1 0%, var(--panel-accent) 35%, #26c6da 100%);
      }

      .room-budget-bar-fill.kwh-tier-1 {
        background: linear-gradient(100deg, #e65100 0%, #ff9800 45%, #ffb74d 100%);
      }

      .room-budget-bar-fill.kwh-tier-2 {
        background: linear-gradient(100deg, #b71c1c 0%, #e53935 40%, #ef5350 100%);
      }

      .room-budget-bar-fill.kwh-tier-3 {
        background: linear-gradient(100deg, #4a148c 0%, #7b1fa2 42%, #9c27b0 100%);
      }

      .room-budget-markers {
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        bottom: 0;
        z-index: 2;
        pointer-events: none;
      }

      .room-budget-marker-wrap {
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        display: flex;
        flex-direction: row;
        align-items: stretch;
        gap: 2px;
        width: max-content;
        max-width: min(100%, calc(100% - 4px));
        transform: none;
        pointer-events: none;
        box-sizing: border-box;
      }

      .room-budget-marker-tick {
        position: relative;
        flex-shrink: 0;
        align-self: stretch;
        width: 2px;
        left: auto;
        top: auto;
        bottom: auto;
        transform: none;
        border-radius: 2px;
        pointer-events: auto;
        z-index: 1;
      }

      .room-budget-marker--interval {
        background: rgba(255, 255, 255, 0.42);
        box-shadow: 0 0 5px rgba(0, 0, 0, 0.4);
      }

      .room-budget-marker--audible {
        width: 3px;
        background: linear-gradient(180deg, #fff 0%, var(--panel-accent) 100%);
        box-shadow: 0 0 12px rgba(3, 169, 244, 0.7), 0 0 2px rgba(0, 0, 0, 0.5);
        z-index: 1;
      }

      .room-budget-marker--budget-only {
        width: 0;
        border-left: 2px dashed rgba(255, 255, 255, 0.55);
        background: transparent;
        box-shadow: none;
        opacity: 0.95;
      }

      .room-budget-marker-label {
        position: relative;
        flex: 0 1 auto;
        align-self: center;
        font-size: clamp(4px, 0.9vw, 7px);
        font-weight: 700;
        line-height: 1.1;
        text-align: left;
        max-width: min(16vw, 80px);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-shadow: 0 0 5px rgba(0, 0, 0, 0.8), 0 1px 2px rgba(0, 0, 0, 0.95);
        pointer-events: none;
        z-index: 2;
      }

      .room-budget-marker-label--audible {
        color: #e1f5fe;
        font-weight: 800;
      }

      .room-budget-marker-wrap > .room-budget-marker-label--audible {
        white-space: normal;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
      }

      .room-budget-marker-label--kwh {
        color: var(--secondary-text-color);
        font-weight: 600;
        font-size: clamp(4px, 0.85vw, 6px);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }

      .room-budget-marker-label--budget {
        color: rgba(255, 255, 255, 0.75);
        font-weight: 600;
        font-size: clamp(4px, 0.85vw, 6px);
      }

      .room-budget-marker-label-stack {
        position: relative;
        flex: 0 1 auto;
        align-self: center;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        gap: 0;
        max-width: min(18vw, 90px);
        min-width: 0;
        pointer-events: none;
        z-index: 2;
      }

      .room-budget-marker-label-stack .room-budget-marker-label {
        max-width: 100%;
        white-space: normal;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        line-height: 1.1;
      }

      .room-budget-marker-sublabel {
        font-size: clamp(3px, 0.8vw, 6px);
        font-weight: 600;
        color: var(--secondary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
        text-shadow: 0 0 5px rgba(0, 0, 0, 0.65);
        text-align: left;
        line-height: 1;
      }

      .room-budget-bar-fill::after {
        content: '';
        position: absolute;
        inset: 0;
        border-radius: inherit;
        background: linear-gradient(
          105deg,
          transparent 0%,
          rgba(255, 255, 255, 0.28) 42%,
          transparent 68%
        );
        background-size: 220% 100%;
        animation: room-budget-surge 2s linear infinite;
      }

      .room-budget-bar-fill.kwh-tier-1::after {
        background: linear-gradient(
          105deg,
          transparent 0%,
          rgba(255, 255, 255, 0.34) 40%,
          transparent 66%
        );
        animation-duration: 1.65s;
      }

      .room-budget-bar-fill.kwh-tier-2::after {
        background: linear-gradient(
          105deg,
          transparent 0%,
          rgba(255, 255, 255, 0.4) 38%,
          transparent 64%
        );
        animation-duration: 1.25s;
      }

      .room-budget-bar-fill.kwh-tier-3::after {
        background: linear-gradient(
          105deg,
          transparent 0%,
          rgba(255, 255, 255, 0.45) 36%,
          transparent 62%
        );
        animation-duration: 0.95s;
      }

      .room-budget-bar-fill.over::after {
        animation-duration: 0.6s;
      }

      @keyframes room-budget-surge {
        0% { background-position: 120% 0; }
        100% { background-position: -120% 0; }
      }

      @media (prefers-reduced-motion: reduce) {
        .room-budget-bar-fill::after {
          animation: none;
        }
      }

      .room-budget-section--na .room-budget-bar-track {
        opacity: 0.45;
      }

      .room-budget-bar-labels {
        position: relative;
        z-index: 3;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        gap: 2px;
        width: 100%;
        min-width: 0;
        max-width: 55%;
        font-size: clamp(8px, 1.85vw, 11px);
        line-height: 1.2;
      }

      .room-budget-values {
        font-variant-numeric: tabular-nums;
        font-weight: 800;
        color: var(--primary-text-color);
        letter-spacing: -0.02em;
        text-shadow:
          0 0 8px rgba(0, 0, 0, 0.65),
          0 1px 3px rgba(0, 0, 0, 0.9);
      }

      .room-budget-sub {
        font-variant-numeric: tabular-nums;
        font-style: italic;
        font-weight: 500;
        font-size: clamp(7px, 1.5vw, 9px);
        color: var(--secondary-text-color);
        text-shadow:
          0 0 6px rgba(0, 0, 0, 0.55),
          0 1px 2px rgba(0, 0, 0, 0.8);
        flex: 0 1 auto;
        min-width: 0;
        max-width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .room-budget-scale-hint {
        margin-left: auto;
        font-variant-numeric: tabular-nums;
        font-weight: 600;
        font-size: clamp(7px, 1.65vw, 10px);
        color: var(--secondary-text-color);
        opacity: 0.88;
        text-shadow:
          0 0 6px rgba(0, 0, 0, 0.5),
          0 1px 2px rgba(0, 0, 0, 0.75);
        white-space: nowrap;
      }

      .room-header-stats-inline {
        display: flex;
        flex-direction: row;
        flex-wrap: nowrap;
        align-items: center;
        justify-content: flex-end;
        gap: clamp(6px, 1.5vw, 10px);
        flex-shrink: 0;
        margin-left: auto;
      }

      .room-total-watts {
        font-size: clamp(12px, 3vw, 17px);
        font-weight: 800;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        line-height: 1.1;
        letter-spacing: -0.02em;
        white-space: nowrap;
      }

      .room-total-watts.over-threshold {
        color: var(--panel-danger);
        animation: pulse-danger 1s infinite;
      }

      @keyframes pulse-danger {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
      }

      .room-event-chips {
        display: flex;
        align-items: center;
        gap: clamp(3px, 0.8vw, 6px);
        flex-shrink: 0;
      }

      .event-count {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        font-size: clamp(7px, 1.7vw, 9px);
        color: var(--secondary-text-color);
        padding: 2px clamp(3px, 0.9vw, 6px);
        background: rgba(255, 255, 255, 0.06);
        border-radius: 4px;
        white-space: nowrap;
        font-variant-numeric: tabular-nums;
        border: 1px solid var(--card-border);
      }

      .view-tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 16px;
        background: var(--secondary-background-color);
        padding: 4px;
        border-radius: 8px;
      }

      .view-tab {
        flex: 1;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--disabled-text-color);
        cursor: pointer;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        transition: all 0.2s;
      }

      .view-tab:hover {
        background: rgba(255, 255, 255, 0.05);
      }

      .view-tab.active {
        background: var(--panel-accent);
        color: white;
      }

      .stove-safety-panel {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }

      .stove-status-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        padding: 20px;
      }

      .stove-status-header {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-bottom: 16px;
      }

      .stove-status-icon {
        width: 64px;
        height: 64px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.3);
        transition: all 0.3s;
      }

      .stove-status-icon.on {
        background: rgba(244, 67, 54, 0.2);
        border: 2px solid var(--panel-danger);
      }

      .stove-status-icon.off {
        background: rgba(76, 175, 80, 0.2);
        border: 2px solid var(--panel-success);
      }

      .stove-status-icon svg {
        width: 32px;
        height: 32px;
        fill: currentColor;
      }

      .stove-status-icon.on svg {
        fill: var(--panel-danger);
      }

      .stove-status-icon.off svg {
        fill: var(--panel-success);
      }

      .stove-status-info {
        flex: 1;
      }

      .stove-status-title {
        font-size: 14px;
        font-weight: 500;
        color: var(--secondary-text-color);
        margin: 0 0 4px 0;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .stove-status-state {
        font-size: 32px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
      }

      .stove-status-state.on {
        color: var(--panel-danger);
      }

      .stove-status-state.off {
        color: var(--panel-success);
      }

      .stove-status-details {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--card-border);
      }

      .stove-detail-item {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .stove-detail-label {
        font-size: 11px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .stove-detail-value {
        font-size: 18px;
        font-weight: 600;
        color: var(--primary-text-color);
        font-variant-numeric: tabular-nums;
      }

      .stove-detail-value.present {
        color: var(--panel-success);
      }

      .stove-detail-value.absent {
        color: var(--panel-warning);
      }

      .stove-timer-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        padding: 20px;
        transition: all 0.3s;
      }

      .stove-timer-card.warning {
        border-color: var(--panel-warning);
        background: rgba(255, 152, 0, 0.1);
        animation: pulse-warning 2s infinite;
      }

      @keyframes pulse-warning {
        0%, 100% { box-shadow: 0 0 0 0 rgba(255, 152, 0, 0.4); }
        50% { box-shadow: 0 0 0 8px rgba(255, 152, 0, 0); }
      }

      .stove-timer-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
      }

      .stove-timer-icon {
        width: 24px;
        height: 24px;
        fill: var(--panel-warning);
      }

      .stove-timer-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--primary-text-color);
        margin: 0;
      }

      .stove-timer-display {
        text-align: center;
        padding: 20px;
        background: rgba(0, 0, 0, 0.2);
        border-radius: 8px;
      }

      .stove-timer-time {
        font-size: 48px;
        font-weight: 700;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        font-family: monospace;
        margin-bottom: 8px;
      }

      .stove-timer-label {
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .stove-timer-warning {
        margin-top: 16px;
        padding: 12px;
        background: rgba(255, 152, 0, 0.2);
        border-radius: 8px;
        border-left: 4px solid var(--panel-warning);
        font-size: 13px;
        color: var(--primary-text-color);
        text-align: center;
      }

      .stove-info-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        padding: 20px;
        display: flex;
        align-items: center;
        gap: 16px;
      }

      .stove-info-icon {
        width: 24px;
        height: 24px;
        fill: var(--panel-accent);
        flex-shrink: 0;
      }

      .stove-info-text {
        font-size: 14px;
        color: var(--secondary-text-color);
        margin: 0;
      }

      .room-content {
        padding: 10px 12px;
        border-radius: 0 0 10px 10px;
        overflow-x: auto;
        overflow-y: hidden;
        /* Hide scrollbar for Chrome, Safari and Opera */
        scrollbar-width: none; /* Firefox */
        -ms-overflow-style: none; /* IE and Edge */
      }

      .room-content::-webkit-scrollbar {
        display: none; /* Chrome, Safari and Opera */
      }

      .outlets-grid {
        display: flex;
        flex-wrap: nowrap;
        gap: 6px;
        justify-content: flex-start;
        align-items: flex-start;
        min-width: min-content;
      }

      .outlet-card.outlet-face {
        width: 81px;
        min-width: 81px;
        flex-shrink: 0;
        padding: 0;
        border: none;
        background: transparent;
        box-sizing: border-box;
      }

      @media (max-width: 500px) {
        .outlet-card.outlet-face {
          width: 72px;
          min-width: 72px;
        }
      }

      .outlet-card.outlet-face .faceplate {
        background: linear-gradient(#f7f7f7, #e9e9e9);
        border: 1px solid rgba(0, 0, 0, 0.18);
        border-radius: 9px;
        padding: 6px 6px 5px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.8);
        position: relative;
        min-height: 200px;
      }

      .outlet-card.outlet-face .outlet-name-top {
        font-size: 14px;
        font-weight: 600;
        color: rgba(0,0,0,0.62);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: center;
        margin-bottom: 4px;
      }

      .outlet-card.outlet-face .faceplate::before {
        content: "";
        position: absolute;
        inset: 4px;
        border-radius: 7px;
        box-shadow: inset 0 0 0 1px rgba(0,0,0,0.07);
        pointer-events: none;
      }

      .outlet-card.outlet-face .receptacle {
        background: linear-gradient(#efefef, #dedede);
        border: 1px solid rgba(0, 0, 0, 0.22);
        border-radius: 8px;
        padding: 6px 6px 4px;
        position: relative;
        box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.65);
      }

      .outlet-card.outlet-face .receptacle + .center-screw {
        margin: 5px auto;
      }

      .outlet-card.outlet-face .receptacle.active {
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.7), 0 0 8px rgba(3, 169, 244, 0.4),
          inset 0 2px 4px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.65);
      }

      .outlet-card.outlet-face .holes {
        height: 26px;
        position: relative;
        margin: 0 auto 4px;
        width: 48px;
      }

      .outlet-card.outlet-face .slot {
        position: absolute;
        top: 2px;
        width: 8px;
        height: 16px;
        background: #2f2f2f;
        border-radius: 2px;
        box-shadow: inset 0 2px 2px rgba(255,255,255,0.08), inset 0 -2px 2px rgba(0,0,0,0.35);
      }

      .outlet-card.outlet-face .slot.left { left: 2px; }
      .outlet-card.outlet-face .slot.right { right: 2px; }

      .outlet-card.outlet-face .slot.right::after {
        content: "";
        position: absolute;
        top: 3px;
        right: 1px;
        width: 2px;
        height: 9px;
        background: rgba(255,255,255,0.08);
        border-radius: 1px;
      }

      .outlet-card.outlet-face .ground {
        position: absolute;
        left: 50%;
        bottom: 2px;
        transform: translateX(-50%);
        width: 18px;
        height: 12px;
        background: #2f2f2f;
        border-radius: 0 0 10px 10px;
        box-shadow: inset 0 2px 2px rgba(255,255,255,0.08), inset 0 -2px 2px rgba(0,0,0,0.35);
      }

      .outlet-card.outlet-face .center-screw {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: linear-gradient(#d8d8d8, #bdbdbd);
        border: 1px solid rgba(0, 0, 0, 0.25);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 1px 2px rgba(0,0,0,0.2);
        position: relative;
        display: block;
      }

      .outlet-card.outlet-face .center-screw::after {
        content: "";
        position: absolute;
        left: 50%;
        top: 50%;
        width: 10px;
        height: 2px;
        transform: translate(-50%, -50%);
        background: rgba(0,0,0,0.35);
        border-radius: 1px;
      }

      .outlet-card.outlet-face .plug-readout {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 4px;
        padding: 0 1px;
      }

      .outlet-card.outlet-face .plug-label {
        font-size: 8px;
        letter-spacing: 0.2px;
        color: rgba(0,0,0,0.55);
        text-transform: uppercase;
      }

      .outlet-card.outlet-face .plug-watts {
        font-size: 10px;
        font-weight: 700;
        color: rgba(0,0,0,0.78);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }

      .outlet-card.outlet-face .outlet-meta {
        margin-top: 5px;
        text-align: center;
        padding-top: 4px;
        border-top: 1px solid rgba(0,0,0,0.10);
      }

      .outlet-card.outlet-face .outlet-name {
        font-size: 7px;
        font-weight: 600;
        color: rgba(0,0,0,0.62);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .outlet-card.outlet-face .outlet-total {
        font-size: 10px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
        margin-top: 2px;
        white-space: nowrap;
      }

      .outlet-card.outlet-face .outlet-total.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      .outlet-card.outlet-face .outlet-threshold {
        margin-top: 3px;
      }

      .outlet-card.outlet-face .threshold-badge {
        display: inline-flex;
        align-items: center;
        font-size: 8px;
        padding: 2px 4px;
        border-radius: 5px;
        color: rgba(0,0,0,0.60);
        background: rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.10);
        white-space: nowrap;
      }

      .outlet-card.outlet-face.single-outlet .faceplate {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        min-height: 200px;
      }

      .outlet-card.outlet-face.single-outlet .single-receptacle {
        flex: 0 0 auto;
        margin-top: auto;
        margin-bottom: auto;
        max-width: calc(100% - 4px);
        margin-left: auto;
        margin-right: auto;
      }

      .outlet-card.outlet-face.single-outlet .plate-screw:first-of-type {
        margin: 4px auto 0;
      }

      .outlet-card.outlet-face.single-outlet .plate-screw:last-of-type {
        margin: 0 auto 4px;
      }

      .outlet-card.outlet-face.single-outlet .outlet-meta {
        margin-top: auto;
      }

      .outlet-card.outlet-face.light-outlet {
        width: 81px;
        min-width: 81px;
        flex-shrink: 0;
      }

      .outlet-card.outlet-face.light-outlet .faceplate {
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .outlet-card.outlet-face.light-outlet .plate-screw:first-of-type {
        margin: 4px auto 16px;
      }

      .outlet-card.outlet-face.light-outlet .plate-screw:last-of-type {
        margin: 16px auto 4px;
      }

      .outlet-card.outlet-face.light-outlet .light-switch-plate {
        width: 48px;
        height: 56px;
        flex: 0 0 auto;
        margin: auto 0;
        background: linear-gradient(#efefef, #dedede);
        border: 1px solid rgba(0, 0, 0, 0.22);
        border-radius: 8px;
        padding: 6px 8px;
        box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.65);
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .outlet-card.outlet-face.light-outlet .light-switch-plate.active {
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.7), 0 0 8px rgba(3, 169, 244, 0.3),
          inset 0 2px 4px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.65);
      }

      .outlet-card.outlet-face.light-outlet .light-toggle-lever {
        width: 36px;
        height: 20px;
        background: linear-gradient(#f8f8f8, #e8e8e8);
        border: 1px solid rgba(0,0,0,0.2);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 2px 4px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.9);
      }

      .outlet-card.outlet-face.light-outlet .light-toggle-lever.off {
        transform: translateY(5px);
      }

      .outlet-card.outlet-face.light-outlet .light-toggle-lever.on {
        transform: translateY(-5px);
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.5), 0 2px 4px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.9);
      }

      .outlet-card.outlet-face.light-outlet .light-toggle-label {
        font-size: 6px;
        font-weight: 700;
        color: rgba(0,0,0,0.75);
        letter-spacing: 0.4px;
        text-shadow: 0 1px 0 rgba(255,255,255,0.8);
      }

      .outlet-card.outlet-face.light-outlet .outlet-total.light-watts-display {
        font-size: 10px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
      }

      .outlet-card.outlet-face.light-outlet .outlet-meta.light-outlet-meta {
        margin-top: 5px;
        padding-top: 4px;
        border-top: 1px solid rgba(0,0,0,0.10);
      }

      .add-device-dropdown {
        position: relative;
      }

      .add-device-menu {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 100;
        min-width: 160px;
        overflow: hidden;
      }

      .add-device-option {
        display: block;
        width: 100%;
        padding: 10px 14px;
        border: none;
        background: transparent;
        color: var(--primary-text-color);
        font-size: 13px;
        text-align: left;
        cursor: pointer;
        transition: background 0.15s;
      }

      .add-device-option:hover {
        background: rgba(3, 169, 244, 0.15);
      }

      .plugs-settings-grid.single-plug {
        grid-template-columns: 1fr;
      }

      .device-card .outlet-name-top {
        font-size: 14px;
        font-weight: 600;
        color: rgba(0,0,0,0.62);
      }

      .device-card.stove-card .outlet-name-top,
      .device-card.microwave-card .outlet-name-top,
      .device-card.minisplit-card .outlet-name-top,
      .device-card.fridge-card .outlet-name-top,
      .device-card.ceiling-vent-card .outlet-name-top {
        font-size: 12px;
        color: var(--primary-text-color);
      }

      .device-card.stove-card .outlet-meta,
      .device-card.microwave-card .outlet-meta,
      .device-card.fridge-card .outlet-meta,
      .device-card.ceiling-vent-card .outlet-meta {
        border-top-color: rgba(255,255,255,0.08);
      }

      .device-card.stove-card .threshold-badge,
      .device-card.microwave-card .threshold-badge,
      .device-card.fridge-card .threshold-badge,
      .device-card.ceiling-vent-card .threshold-badge {
        color: var(--secondary-text-color);
        background: rgba(255,255,255,0.08);
        border-color: rgba(255,255,255,0.12);
      }

      .device-card.stove-card .stove-meta {
        margin-top: 3px;
        padding-top: 3px;
      }

      .device-card .outlet-meta {
        margin-top: 5px;
        text-align: center;
        padding-top: 4px;
        border-top: 1px solid rgba(0,0,0,0.10);
      }

      .device-card .outlet-total {
        font-size: 10px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
      }

      .device-card .outlet-total.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      .device-card .threshold-badge {
        font-size: 8px;
        padding: 2px 4px;
        border-radius: 5px;
        color: rgba(0,0,0,0.60);
        background: rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.10);
      }

      .enforcement-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        font-size: clamp(8px, 1.9vw, 10px);
        font-weight: 600;
        padding: 3px clamp(6px, 1.4vw, 9px);
        border-radius: 8px;
        color: #fff;
        letter-spacing: 0.02em;
        white-space: nowrap;
        line-height: 1.2;
        flex-shrink: 0;
        text-transform: none;
      }

      .enforcement-badge--inline {
        padding: 1px clamp(4px, 1.1vw, 7px);
        font-size: clamp(7px, 1.65vw, 9px);
        border-radius: 5px;
        gap: 2px;
      }

      .enforcement-badge.enforcement-phase-0 {
        background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
        box-shadow: 0 1px 3px rgba(255, 152, 0, 0.35);
      }

      .enforcement-badge.enforcement-phase-1 {
        background: linear-gradient(135deg, #e53935 0%, #b71c1c 100%);
        box-shadow: 0 1px 3px rgba(229, 57, 53, 0.35);
      }

      .enforcement-badge.enforcement-phase-2 {
        background: linear-gradient(135deg, #7e57c2 0%, #4527a0 100%);
        box-shadow: 0 1px 3px rgba(126, 87, 194, 0.35);
      }

      .enforcement-badge svg {
        filter: drop-shadow(0 1px 1px rgba(0,0,0,0.2));
      }

      .device-card.stove-card {
        width: 243px;
        min-width: 243px;
        flex-shrink: 0;
        background: transparent;
      }

      .device-card.stove-card .stove-faceplate {
        background: transparent;
        border: none;
        padding: 6px 6px 5px;
        box-shadow: none;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .device-card.stove-card .stove-body {
        flex: 1;
        width: 100%;
        margin: 4px 0;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        background: linear-gradient(180deg, #d0d4d8, #b8bcc0);
        border: 1px solid rgba(0, 0, 0, 0.12);
        border-radius: 4px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), 0 1px 2px rgba(0,0,0,0.08);
        overflow: hidden;
      }

      .device-card.stove-card .stove-control-panel {
        height: 18px;
        background: linear-gradient(180deg, #2a2a2a, #1a1a1a);
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 3px 6px;
        gap: 4px;
      }

      .device-card.stove-card .stove-display {
        width: 18px;
        height: 8px;
        background: rgba(8, 8, 8, 0.9);
        border-radius: 1px;
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-knobs {
        display: flex;
        gap: 6px;
        align-items: center;
        flex: 1;
        justify-content: center;
      }

      .device-card.stove-card .stove-knob {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: radial-gradient(circle at 35% 35%, #c8ccd0, #808488);
        border: none;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.15), inset 0 1px 2px rgba(255,255,255,0.2), 0 1px 1px rgba(0,0,0,0.2);
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .device-card.stove-card .stove-knob::after {
        content: "";
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: #404448;
      }

      .device-card.stove-card .stove-knob.active {
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.6), inset 0 0 0 1px rgba(255,255,255,0.15);
      }

      .device-card.stove-card .stove-oven-door {
        flex: 1;
        min-height: 44px;
        display: flex;
        flex-direction: column;
        align-items: center;
        background: linear-gradient(180deg, #d8dce0, #c4c8cc);
        padding: 5px 10px 6px;
      }

      .device-card.stove-card .stove-oven-door.active {
        box-shadow: inset 0 0 0 2px rgba(3, 169, 244, 0.4);
      }

      .device-card.stove-card .stove-handle {
        width: 50%;
        height: 4px;
        margin: 0 0 5px;
        background: linear-gradient(180deg, #b0b4b8, #888c90);
        border-radius: 1px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.4), 0 1px 0 rgba(0,0,0,0.15);
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-oven-window {
        flex: 1;
        width: 88%;
        min-height: 30px;
        border-radius: 2px;
        background: linear-gradient(135deg, rgba(18,18,20,0.98) 0%, rgba(35,35,38,0.98) 50%, rgba(25,25,28,0.98) 100%);
        border: 1px solid rgba(0, 0, 0, 0.5);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
        position: relative;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 3px;
      }

      .device-card.stove-card .stove-timer-remaining {
        font-size: 10px;
        font-weight: 600;
        color: var(--panel-warning, #ff9800);
        margin-top: 0;
        text-align: center;
        line-height: 1.2;
      }
      .device-card.stove-card .stove-door-watts {
        font-size: 10px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
        text-shadow: 0 0 4px rgba(0,0,0,0.8);
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-door-watts.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      .device-card.stove-card .stove-oven-window::before {
        content: "";
        position: absolute;
        top: -20%;
        left: -20%;
        width: 80%;
        height: 80%;
        background: linear-gradient(135deg, transparent 40%, rgba(180,180,185,0.12) 50%, transparent 60%);
        transform: rotate(-45deg);
        pointer-events: none;
      }

      .device-card.stove-card .stove-lower-panel {
        height: 14px;
        background: linear-gradient(180deg, #d4d8dc, #bcc0c4);
        border-top: 1px solid rgba(255,255,255,0.3);
      }

      .device-card.stove-card .stove-kickplate {
        height: 6px;
        background: linear-gradient(180deg, #1c1c1c, #0c0c0c);
      }

      .device-card.microwave-card {
        width: 243px;
        min-width: 243px;
        flex-shrink: 0;
        background: transparent;
      }

      .device-card.microwave-card .mw-faceplate {
        background: transparent;
        border: none;
        padding: 6px 6px 5px;
        box-shadow: none;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .device-card.microwave-card .mw-body {
        flex: 1;
        display: flex;
        align-items: stretch;
        width: 100%;
        margin: 4px 0;
        border-radius: 8px;
        padding: 6px;
        gap: 8px;
        background: linear-gradient(180deg, rgba(235,235,235,0.95), rgba(190,190,190,0.95));
        border: 1px solid rgba(0, 0, 0, 0.12);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.55);
      }

      .device-card.microwave-card .mw-body.mw-on .mw-window {
        border-color: rgba(3,169,244,0.4);
        box-shadow: 0 0 8px rgba(3,169,244,0.2), inset 0 1px 0 rgba(255,255,255,0.08);
      }

      .device-card.microwave-card .mw-door {
        flex: 4 1 auto;
        min-width: 0;
        display: flex;
        gap: 6px;
        align-items: stretch;
      }

      .device-card.microwave-card .mw-window {
        flex: 1;
        min-width: 0;
        border-radius: 6px;
        background: linear-gradient(180deg, rgba(25,25,25,0.95), rgba(40,40,40,0.95));
        border: 1px solid rgba(0, 0, 0, 0.4);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
      }

      .device-card.microwave-card .mw-controls {
        flex: 1 0 auto;
        width: 20%;
        min-width: 44px;
        max-width: 52px;
        display: flex;
        flex-direction: column;
        gap: 3px;
      }

      .device-card.microwave-card .mw-lcd {
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.75);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 4px 5px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
      }

      .device-card.microwave-card .mw-lcd-watts {
        font-size: 10px;
        font-weight: 700;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
      }

      .device-card.microwave-card .mw-lcd-watts.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      .device-card.microwave-card .mw-keys {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 2px;
      }

      .device-card.microwave-card .mw-key {
        height: 7px;
        border-radius: 3px;
        background: rgba(120,120,120,0.5);
        border: 1px solid rgba(255,255,255,0.12);
      }

      .device-card.microwave-card .mw-actions {
        display: flex;
        gap: 3px;
        align-items: center;
        justify-content: center;
      }

      .device-card.microwave-card .mw-btn-pill {
        width: 18px;
        height: 6px;
        border-radius: 6px;
        background: rgba(120,120,120,0.5);
        border: 1px solid rgba(255,255,255,0.12);
      }

      .device-card.microwave-card .mw-btn-round {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: rgba(120,120,120,0.5);
        border: 1px solid rgba(255,255,255,0.12);
      }

      .device-card.microwave-card .mw-door-btn-wrap {
        margin-top: auto;
        display: flex;
        justify-content: stretch;
        width: 100%;
      }

      .device-card.microwave-card .mw-door-btn {
        width: 100%;
        height: 16px;
        border-radius: 4px;
        background: rgba(120,120,120,0.5);
        border: 1px solid rgba(255,255,255,0.12);
      }

      .device-card.microwave-card .mw-handle {
        width: 6px;
        border-radius: 4px;
        background: linear-gradient(180deg, rgba(160,160,160,0.95), rgba(120,120,120,0.95));
        border: 1px solid rgba(0, 0, 0, 0.2);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.4);
      }

      .device-card.minisplit-card {
        width: 243px;
        min-width: 243px;
        flex-shrink: 0;
        background: transparent;
      }

      .device-card.minisplit-card .ms-faceplate {
        background: transparent;
        border: none;
        padding: 6px 6px 5px;
        box-shadow: none;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .device-card.minisplit-card .outlet-name-top,
      .device-card.minisplit-card .outlet-meta,
      .device-card.minisplit-card .threshold-badge {
        color: var(--primary-text-color);
      }

      .device-card.minisplit-card .outlet-meta {
        border-top-color: rgba(255,255,255,0.08);
        margin-top: auto;
        padding-top: 12px;
      }

      .device-card.minisplit-card .threshold-badge {
        background: rgba(255,255,255,0.08);
        border-color: rgba(255,255,255,0.12);
      }

      .device-card.minisplit-card .ms-unit {
        flex: 0 0 auto;
        width: 88%;
        max-width: 200px;
        height: 88px;
        margin: auto 12px;
        position: relative;
        overflow: visible;
        /* Mini-split shape: tapered, narrower at bottom - mimics real unit, not a perfect rectangle */
        clip-path: polygon(0 0, 100% 0, 96% 100%, 4% 100%);
        border-radius: 14px 14px 8px 8px;
        /* Main body gradient - light from upper left, shading toward lower right */
        background: linear-gradient(145deg, #ffffff 0%, #fafafa 20%, #f2f2f2 50%, #eaeaea 80%, #e2e2e2 100%);
        border: 1px solid rgba(0, 0, 0, 0.06);
        box-shadow:
          6px 8px 18px rgba(0,0,0,0.14),
          2px 4px 8px rgba(0,0,0,0.08),
          inset 0 1px 0 rgba(255,255,255,0.92);
      }

      /* Top bevel - subtle darker edge suggesting 3D curve */
      .device-card.minisplit-card .ms-unit::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 14px;
        border-radius: 14px 14px 0 0;
        background: linear-gradient(180deg, rgba(220,222,225,0.5) 0%, rgba(255,255,255,0) 100%);
        pointer-events: none;
      }

      /* Right-side shading - depth from light source upper-left */
      .device-card.minisplit-card .ms-unit::after {
        content: "";
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 35%;
        background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(0,0,0,0.04) 50%, rgba(0,0,0,0.08) 100%);
        pointer-events: none;
      }

      .device-card.minisplit-card .ms-lcd {
        position: absolute;
        top: 10px;
        left: 50%;
        transform: translateX(-50%);
        width: 20%;
        min-width: 44px;
        max-width: 52px;
        height: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 4px;
        background: linear-gradient(180deg, rgba(45,45,48,0.95), rgba(25,25,28,0.95));
        border: 1px solid rgba(0, 0, 0, 0.35);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
      }

      .device-card.minisplit-card .ms-lcd-watts {
        font-size: 9px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
      }

      .device-card.minisplit-card .ms-lcd-watts.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      .device-card.minisplit-card .ms-unit.ms-on .ms-lcd {
        border-color: rgba(3,169,244,0.4);
        box-shadow: 0 0 6px rgba(3,169,244,0.2), inset 0 1px 0 rgba(255,255,255,0.06);
      }

      /* Recessed upper strip - light grey band for display area */
      .device-card.minisplit-card .ms-upper-panel {
        position: absolute;
        top: 0;
        left: 8%;
        right: 8%;
        height: 24px;
        background: linear-gradient(180deg, rgba(245,245,248,0.9) 0%, rgba(232,232,236,0.95) 100%);
        border-radius: 6px 6px 0 0;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.06);
      }

      .device-card.minisplit-card .ms-vent {
        position: absolute;
        left: 8px;
        right: 8px;
        bottom: 4px;
        height: 24px;
        border-radius: 0 0 8px 8px;
        /* Recessed vent - lighter top bevel, darker interior */
        background: linear-gradient(180deg, #c8c8cc 0%, #b0b0b4 20%, #9a9a9e 100%);
        border: 1px solid rgba(0, 0, 0, 0.12);
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.15);
      }

      /* Grey bevel strip above vent - transition from white body */
      .device-card.minisplit-card .ms-vent::before {
        content: "";
        position: absolute;
        left: -2px;
        right: -2px;
        top: -5px;
        height: 5px;
        background: linear-gradient(180deg, rgba(200,202,206,0.95), rgba(180,182,186,0.95));
        border-radius: 2px 2px 0 0;
      }

      .device-card.minisplit-card .ms-vent-inner {
        position: absolute;
        left: 6px;
        right: 6px;
        top: 50%;
        transform: translateY(-50%);
        display: flex;
        flex-direction: column;
        gap: 3px;
        justify-content: center;
      }

      .device-card.minisplit-card .ms-slat {
        height: 1px;
        background: #1a1a1a;
      }

      .device-card.minisplit-card .ms-vent-edge {
        position: absolute;
        left: 4px;
        right: 4px;
        bottom: 0;
        height: 1px;
        background: rgba(0, 0, 0, 0.25);
        border-radius: 0 0 6px 6px;
      }

      /* Fridge card - single width, detailed two-door top-freezer fridge */
      .device-card.fridge-card {
        width: 81px;
        min-width: 81px;
        flex-shrink: 0;
        background: transparent;
      }
      .device-card.fridge-card .fridge-faceplate {
        background: transparent;
        border: none;
        padding: 6px 6px 5px;
        box-shadow: none;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .device-card.fridge-card .fridge-body {
        flex: 1;
        width: 100%;
        margin: 4px 0;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        background: linear-gradient(135deg, #b8bcc0 0%, #a0a4a8 100%);
        border: 1px solid rgba(0, 0, 0, 0.2);
        border-radius: 4px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.4), 0 2px 4px rgba(0,0,0,0.12);
        overflow: hidden;
        position: relative;
      }
      .device-card.fridge-card .fridge-body.fridge-on {
        box-shadow: inset 0 0 0 2px rgba(3, 169, 244, 0.4);
      }
      .device-card.fridge-card .fridge-freezer-door,
      .device-card.fridge-card .fridge-fresh-door {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        padding-left: 3px;
        position: relative;
      }
      .device-card.fridge-card .fridge-freezer-door {
        flex: 0 0 32%;
        min-height: 36px;
      }
      .device-card.fridge-card .fridge-fresh-door {
        flex: 1;
        min-height: 56px;
      }
      .device-card.fridge-card .fridge-door-panel {
        flex: 1;
        height: 100%;
        min-height: 24px;
        background: linear-gradient(135deg, #e4e8ec 0%, #d0d4d8 40%, #c4c8cc 100%);
        border: 1px solid rgba(0, 0, 0, 0.15);
        border-radius: 2px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 1px 0 rgba(0,0,0,0.08);
      }
      .device-card.fridge-card .fridge-freezer-door .fridge-door-panel {
        background: linear-gradient(135deg, #e0e4e8 0%, #ccd0d4 100%);
      }
      .device-card.fridge-card .fridge-handle-vert {
        width: 4px;
        height: 75%;
        min-height: 18px;
        margin-left: 4px;
        background: linear-gradient(90deg, #909498 0%, #606468 40%, #707478 100%);
        border-radius: 1px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 1px 1px rgba(0,0,0,0.2);
        flex-shrink: 0;
      }
      .device-card.fridge-card .fridge-seam {
        height: 2px;
        background: linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.2) 20%, rgba(0,0,0,0.2) 80%, transparent 100%);
        flex-shrink: 0;
      }
      .device-card.fridge-card .fridge-kickplate {
        height: 5px;
        background: linear-gradient(180deg, #2a2a2a 0%, #1a1a1a 100%);
        flex-shrink: 0;
      }
      .device-card.fridge-card .fridge-watts {
        position: absolute;
        bottom: 8px;
        left: 50%;
        transform: translateX(-50%);
        font-size: 9px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
        text-shadow: 0 0 3px rgba(0,0,0,0.7);
      }
      .device-card.fridge-card .fridge-watts.over-threshold {
        color: var(--panel-danger, #ff5252);
      }

      /* Ceiling vent fan card - single width, square, detailed vent grill */
      .device-card.ceiling-vent-card {
        width: 81px;
        min-width: 81px;
        flex-shrink: 0;
        background: transparent;
      }
      .device-card.ceiling-vent-card .ceiling-vent-faceplate {
        background: transparent;
        border: none;
        padding: 6px 6px 5px;
        box-shadow: none;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .device-card.ceiling-vent-card .ceiling-vent-body {
        width: 69px;
        height: 69px;
        margin: 4px 0;
        flex-shrink: 0;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        justify-content: flex-start;
        background: linear-gradient(180deg, #f5f5f5 0%, #e8e8e8 100%);
        border: 1px solid rgba(0, 0, 0, 0.1);
        border-radius: 6px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.8), 0 1px 2px rgba(0,0,0,0.08);
        overflow: hidden;
        position: relative;
      }
      .device-card.ceiling-vent-card .ceiling-vent-body.vent-on {
        box-shadow: inset 0 0 0 2px rgba(3, 169, 244, 0.4);
      }
      .device-card.ceiling-vent-card .ceiling-vent-grill-wrap {
        position: relative;
        flex: 1 1 0;
        min-height: 0;
        display: flex;
        flex-direction: column;
        align-items: stretch;
        justify-content: center;
        overflow: hidden;
      }
      .device-card.ceiling-vent-card .ceiling-vent-grill {
        width: 100%;
        padding: 5px 4px 4px;
        display: flex;
        flex-direction: column;
        gap: 2px;
        align-items: stretch;
        flex-shrink: 0;
      }
      .device-card.ceiling-vent-card .cv-slat {
        display: block;
        height: 2px;
        background: linear-gradient(180deg, #1a1a1a 0%, #0d0d0d 50%, #1a1a1a 100%);
        border-radius: 0;
        box-shadow: 0 0 0 1px rgba(0,0,0,0.3);
      }
      .device-card.ceiling-vent-card .cv-air-particles {
        position: absolute;
        inset: 6px 6px 4px;
        pointer-events: none;
      }
      .device-card.ceiling-vent-card .cv-particle {
        position: absolute;
        width: 2px;
        height: 2px;
        background: rgba(3, 169, 244, 0.5);
        border-radius: 50%;
        animation: cv-particle-float 2s ease-in-out infinite;
      }
      .device-card.ceiling-vent-card .cv-particle:nth-child(1) { left: 15%; top: 80%; animation-delay: 0s; }
      .device-card.ceiling-vent-card .cv-particle:nth-child(2) { left: 45%; top: 70%; animation-delay: 0.4s; }
      .device-card.ceiling-vent-card .cv-particle:nth-child(3) { left: 75%; top: 85%; animation-delay: 0.8s; }
      .device-card.ceiling-vent-card .cv-particle:nth-child(4) { left: 25%; top: 50%; animation-delay: 0.2s; }
      .device-card.ceiling-vent-card .cv-particle:nth-child(5) { left: 60%; top: 40%; animation-delay: 0.6s; }
      @keyframes cv-particle-float {
        0%, 100% { transform: translateY(0) scale(0.8); opacity: 0.4; }
        50% { transform: translateY(-8px) scale(1); opacity: 0.8; }
      }
      @media (prefers-reduced-motion: reduce) {
        .device-card.ceiling-vent-card .cv-particle { animation: none; opacity: 0.5; }
      }
      .device-card.ceiling-vent-card .ceiling-vent-watts-row {
        flex-shrink: 0;
        width: 100%;
        min-height: 15px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 2px 3px;
        box-sizing: border-box;
      }
      .device-card.ceiling-vent-card .ceiling-vent-watts {
        font-size: clamp(7px, 2.1vw, 9px);
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
        text-shadow: 0 0 3px rgba(255,255,255,0.5);
        white-space: nowrap;
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.1;
        text-align: center;
      }
      .device-card.ceiling-vent-card .ceiling-vent-watts.over-threshold {
        color: var(--panel-danger, #ff5252);
      }
      .device-card.ceiling-vent-card .heater-dash-meta {
        margin-top: 3px;
        font-size: 9px;
        line-height: 1.2;
        color: var(--secondary-text-color, rgba(255,255,255,0.52));
        font-variant-numeric: tabular-nums;
        text-align: center;
        max-width: 100%;
        padding: 0 2px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
      }
      .device-card.ceiling-vent-card .heater-dash-row {
        display: flex;
        flex-direction: row;
        flex-wrap: nowrap;
        align-items: baseline;
        justify-content: center;
        gap: 3px;
        max-width: 100%;
      }
      .device-card.ceiling-vent-card .heater-dash-lbl {
        font-size: 8px;
        font-weight: 600;
        opacity: 0.72;
        flex-shrink: 0;
      }
      .device-card.ceiling-vent-card .heater-dash-val {
        font-size: 9px;
        font-weight: 800;
        color: var(--primary-text-color, rgba(255,255,255,0.9));
        flex-shrink: 0;
      }
      .device-card.ceiling-vent-card .heater-dash-dot {
        opacity: 0.45;
        font-size: 8px;
        flex-shrink: 0;
        padding: 0 1px;
      }
      .device-card.ceiling-vent-card .heater-dash-timer {
        color: var(--panel-accent, #03a9f4);
      }

      .appliance-context-menu-backdrop {
        position: fixed;
        inset: 0;
        z-index: 1100;
        background: transparent;
      }
      .appliance-context-menu {
        position: fixed;
        z-index: 1101;
        min-width: 200px;
        max-width: min(92vw, 280px);
        padding: 6px;
        margin: 0;
        border-radius: 10px;
        border: 1px solid var(--card-border, rgba(255,255,255,0.14));
        background: var(--card-bg, #1c1c1c);
        box-shadow: 0 8px 28px rgba(0,0,0,0.45);
        box-sizing: border-box;
      }
      .appliance-context-menu-item {
        display: block;
        width: 100%;
        margin: 0;
        padding: 10px 12px;
        border: none;
        border-radius: 8px;
        background: transparent;
        color: var(--primary-text-color, #e8e8e8);
        font: inherit;
        font-size: 14px;
        text-align: left;
        cursor: pointer;
        min-height: 44px;
        box-sizing: border-box;
        -webkit-tap-highlight-color: transparent;
      }
      .appliance-context-menu-item:hover,
      .appliance-context-menu-item:focus-visible {
        background: rgba(255, 255, 255, 0.08);
        outline: none;
      }
      .appliance-context-menu-item:focus-visible {
        outline: 2px solid var(--panel-accent, #03a9f4);
        outline-offset: 0;
      }
      .appliance-context-menu-item + .appliance-context-menu-item {
        margin-top: 2px;
      }

      .graph-modal-overlay {
        position: fixed;
        inset: 0;
        z-index: 1000;
        background: rgba(0, 0, 0, 0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: clamp(12px, 4vw, 24px);
        box-sizing: border-box;
      }
      .graph-modal {
        background: var(--card-bg, #1c1c1c);
        border-radius: clamp(8px, 2vw, 12px);
        border: 1px solid var(--card-border, rgba(255,255,255,0.12));
        width: min(95vw, 640px);
        max-width: 100%;
        max-height: min(90vh, 560px);
        display: flex;
        flex-direction: column;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      }
      .graph-modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: clamp(10px, 2.5vw, 16px) clamp(12px, 3vw, 20px);
        border-bottom: 1px solid var(--card-border, rgba(255,255,255,0.12));
        flex-shrink: 0;
      }
      .graph-modal-title {
        margin: 0;
        font-size: clamp(14px, 3.5vw, 18px);
        font-weight: 600;
        color: var(--primary-text-color, #fff);
      }
      .graph-modal-close {
        width: clamp(36px, 8vw, 44px);
        height: clamp(36px, 8vw, 44px);
        min-width: 36px;
        min-height: 36px;
        border: none;
        background: rgba(255,255,255,0.1);
        color: var(--primary-text-color, #fff);
        font-size: clamp(20px, 5vw, 28px);
        line-height: 1;
        border-radius: clamp(4px, 1vw, 8px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        transition: background 0.2s;
      }
      .graph-modal-close:hover {
        background: rgba(255,255,255,0.2);
      }
      .graph-modal-body {
        padding: clamp(10px, 2.5vw, 16px);
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
      }
      .graph-modal-loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        min-height: 200px;
        padding: 24px;
        color: var(--secondary-text-color, #9b9b9b);
        font-size: 14px;
        text-align: center;
      }
      .graph-modal-loading-spinner {
        width: 36px;
        height: 36px;
        border: 3px solid rgba(255,255,255,0.15);
        border-top-color: var(--panel-accent, #03a9f4);
        border-radius: 50%;
        animation: graph-modal-spin 0.75s linear infinite;
      }
      @keyframes graph-modal-spin {
        to { transform: rotate(360deg); }
      }
      .graph-modal-error {
        color: var(--panel-danger, #ff5252);
        padding: 16px;
        text-align: center;
        font-size: 14px;
      }
      .event-log-container {
        max-height: 360px;
        overflow-y: auto;
        padding: 16px;
      }
      .event-log-list {
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .event-log-entry {
        padding: 10px 0;
        border-bottom: 1px solid var(--card-border);
        font-size: 14px;
      }
      .event-log-entry-row {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        flex-wrap: wrap;
      }
      .event-log-ts {
        color: var(--secondary-text-color);
        font-size: 13px;
        min-width: 8.5em;
        font-variant-numeric: tabular-nums;
      }
      .event-log-who {
        flex: 1;
        min-width: 0;
        font-size: 14px;
      }
      .event-log-badge {
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 500;
      }
      .event-log-detail {
        margin-top: 8px;
        width: 100%;
      }
      .event-log-message {
        margin: 0 0 6px;
        font-size: 12px;
        color: var(--secondary-text-color);
        white-space: pre-wrap;
        word-break: break-word;
        line-height: 1.45;
      }
      .event-log-readings {
        margin: 0;
        font-size: 11px;
        color: var(--secondary-text-color);
        opacity: 0.95;
        line-height: 1.4;
      }
      .graph-chart-container {
        flex: 1;
        min-height: clamp(220px, 50vw, 320px);
        width: 100%;
      }
      .billing-bar-chart-native {
        position: relative;
        width: 100%;
        min-height: 280px;
        display: flex;
        flex-direction: column;
        box-sizing: border-box;
        container-type: inline-size;
        container-name: billing-bar;
      }
      .billing-bar-chart-body {
        display: flex;
        flex: 1;
        min-height: 220px;
        gap: 8px;
        align-items: stretch;
      }
      .billing-bar-y-axis {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        width: 48px;
        flex-shrink: 0;
        font-size: 11px;
        color: var(--primary-text-color, #e1e1e1);
        text-align: right;
        padding-right: 4px;
        line-height: 1.1;
      }
      .billing-bar-plot {
        flex: 1;
        display: flex;
        align-items: stretch;
        gap: 3px;
        min-width: 0;
        border-bottom: 1px solid var(--card-border, rgba(255,255,255,0.12));
        padding-bottom: 2px;
        position: relative;
      }
      .billing-bar-grid-line {
        position: absolute;
        left: 0;
        right: 0;
        height: 1px;
        background: var(--card-border, rgba(255,255,255,0.12));
        pointer-events: none;
      }
      .billing-bar-column {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        min-height: 0;
      }
      .billing-bar-hit {
        flex: 1;
        min-height: 40px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        align-items: center;
        width: 100%;
        padding: 0;
        margin: 0;
        border: none;
        background: transparent;
        cursor: pointer;
        border-radius: 4px;
        -webkit-tap-highlight-color: transparent;
      }
      .billing-bar-hit:focus-visible {
        outline: 2px solid var(--panel-accent, #03a9f4);
        outline-offset: 2px;
      }
      .billing-bar-fill {
        width: 72%;
        max-width: 40px;
        border-radius: 4px 4px 0 0;
        transition: filter 0.12s ease;
      }
      .billing-bar-hit:hover .billing-bar-fill,
      .billing-bar-hit:focus-visible .billing-bar-fill {
        filter: brightness(1.14);
      }
      .billing-bar-x-labels {
        display: flex;
        margin-top: 8px;
        gap: 3px;
        padding-left: 56px;
        min-height: 2.5em;
      }
      .billing-bar-x-labels--dense {
        min-height: 4.5em;
      }
      .billing-bar-x-labels--hourly {
        min-height: 1.35em;
      }
      .billing-bar-x-label {
        flex: 1;
        min-width: 0;
        font-size: 10px;
        color: var(--secondary-text-color, #9b9b9b);
        text-align: center;
        line-height: 1.15;
        overflow: hidden;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        word-break: break-word;
      }
      .billing-bar-x-labels--dense .billing-bar-x-label {
        font-size: 9px;
        -webkit-line-clamp: 3;
      }
      .billing-bar-x-labels--hourly .billing-bar-x-label {
        display: block;
        -webkit-line-clamp: unset;
        -webkit-box-orient: unset;
        word-break: normal;
        white-space: nowrap;
        text-overflow: ellipsis;
        font-size: clamp(6px, 2.4cqi, 9px);
        line-height: 1.2;
      }
      .billing-bar-tooltip {
        position: absolute;
        z-index: 5;
        max-width: min(280px, 92vw);
        padding: 10px 12px;
        font-size: 12px;
        line-height: 1.45;
        color: #e8e8e8;
        background: #2a2a2a;
        border-radius: 8px;
        border: 1px solid rgba(255,255,255,0.12);
        box-shadow: 0 4px 16px rgba(0,0,0,0.35);
        pointer-events: none;
      }
      .billing-bar-tooltip[hidden] {
        display: none !important;
      }
      .graph-dates {
        font-size: clamp(9px, 2vw, 11px);
        color: var(--secondary-text-color, #999);
        margin-top: clamp(6px, 1.5vw, 10px);
      }

      @media (max-width: 500px) {
        .device-card.stove-card,
        .device-card.microwave-card,
        .device-card.minisplit-card {
          width: 216px;
          min-width: 216px;
        }
        .device-card.fridge-card,
        .device-card.ceiling-vent-card {
          width: 72px;
          min-width: 72px;
        }
      }

      /* Settings Styles */
      .room-settings-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        margin-bottom: 16px;
        overflow: visible;
        transition: box-shadow 0.2s, border-color 0.2s;
      }

      .room-settings-card.dragging {
        opacity: 0.6;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
      }

      .room-settings-card.drag-over {
        border-color: var(--panel-accent);
        box-shadow: 0 0 0 2px var(--panel-accent-dim);
      }

      .room-drag-handle {
        cursor: grab;
        color: var(--secondary-text-color);
        padding: 4px 6px;
        opacity: 0.6;
        display: flex;
        align-items: center;
        flex-shrink: 0;
      }

      .room-drag-handle:hover {
        opacity: 1;
      }

      .room-drag-handle:active {
        cursor: grabbing;
      }

      .room-drag-handle svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }

      .room-settings-header {
        display: flex;
        flex-wrap: nowrap;
        align-items: center;
        justify-content: flex-start;
        gap: 8px;
        padding: 16px 20px;
        min-width: 0;
        overflow-x: auto;
        scrollbar-width: thin;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
      }

      .room-settings-header-start {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1 1 auto;
        min-width: 0;
      }

      .room-settings-header-presence {
        flex: 1 1 clamp(4rem, 18vw, 12rem);
        min-width: 0;
        display: flex;
        align-items: center;
      }

      .room-settings-header-presence:not(:has(.room-settings-presence-live)) {
        flex: 0 0 0;
        width: 0;
        min-width: 0;
        overflow: hidden;
        padding: 0;
        margin: 0;
      }

      .room-settings-header-actions {
        flex-shrink: 0;
        display: flex;
        gap: 8px;
        align-items: center;
      }

      .room-settings-header .room-name-input {
        flex: 1 1 clamp(5rem, 22vw, 14rem);
        min-width: 0;
        font-size: clamp(11px, 2.5vw, 13px);
        font-weight: 500;
        padding: 8px 10px;
      }

      .room-icon-picker-trigger {
        width: 40px;
        height: 40px;
        min-width: 40px;
        padding: 0;
        border: 1px solid var(--card-border);
        border-radius: 8px;
        background: var(--input-bg, rgba(255, 255, 255, 0.06));
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--panel-accent, #03a9f4);
      }

      .room-icon-picker-trigger:hover {
        background: rgba(255, 255, 255, 0.1);
      }

      .room-icon-picker-trigger:focus-visible {
        outline: 2px solid var(--panel-accent, #03a9f4);
        outline-offset: 2px;
      }

      .room-icon-picker-trigger ha-icon {
        width: 22px;
        height: 22px;
      }

      .room-settings-presence-live {
        font-size: 11px;
        color: var(--secondary-text-color);
        line-height: 1.4;
        margin-bottom: 12px;
        padding: 8px 10px;
        background: rgba(255, 255, 255, 0.04);
        border-radius: 6px;
        border: 1px solid var(--card-border);
        word-break: break-word;
        overflow-wrap: anywhere;
      }

      .room-settings-presence-live--header {
        margin-bottom: 0;
        width: 100%;
        min-width: 0;
        padding: 6px 8px;
        font-size: clamp(10px, 2.2vw, 11px);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        word-break: normal;
        overflow-wrap: normal;
      }

      .room-settings-presence-live--header .room-settings-presence-live-text {
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .room-icon-modal-overlay {
        position: fixed;
        inset: 0;
        z-index: 10000;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 16px;
        background: rgba(0, 0, 0, 0.5);
        box-sizing: border-box;
      }

      .room-icon-modal {
        width: min(100%, 420px);
        max-height: min(85vh, 560px);
        display: flex;
        flex-direction: column;
        background: var(--card-background-color, #1e1e1e);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
        overflow: hidden;
      }

      .room-icon-modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 12px 14px;
        border-bottom: 1px solid var(--card-border);
      }

      .room-icon-modal-title {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }

      .room-icon-modal-actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .room-icon-modal-body {
        padding: 12px 14px;
        overflow-y: auto;
        flex: 1;
        min-height: 0;
      }

      .room-icon-modal-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(44px, 1fr));
        gap: 8px;
      }

      .room-icon-modal-grid-btn {
        width: 44px;
        height: 44px;
        padding: 0;
        border: 1px solid var(--card-border);
        border-radius: 8px;
        background: var(--input-bg, rgba(255, 255, 255, 0.06));
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--primary-text-color);
      }

      .room-icon-modal-grid-btn:hover {
        background: rgba(3, 169, 244, 0.15);
      }

      .room-icon-modal-grid-btn:focus-visible {
        outline: 2px solid var(--panel-accent, #03a9f4);
        outline-offset: 2px;
      }

      .room-icon-modal-grid-btn ha-icon {
        width: 22px;
        height: 22px;
      }

      @media (prefers-reduced-motion: reduce) {
        .room-icon-picker-trigger,
        .room-icon-modal-grid-btn {
          transition: none;
        }
      }

      .room-settings-body {
        padding: 12px 14px;
      }

      .room-settings-body .form-label {
        font-size: 10px;
        margin-bottom: 4px;
      }

      .room-settings-body .form-input {
        padding: 8px 10px;
        font-size: 12px;
      }

      .room-settings-body .form-input.threshold-disabled:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .room-settings-body .form-select {
        padding: 8px 32px 8px 10px;
        font-size: 12px;
      }

      .room-settings-body .grid-2 {
        gap: 10px;
      }

      .outlet-settings-item {
        background: var(--input-bg);
        border-radius: 6px;
        margin-bottom: 6px;
        border: 1px solid var(--card-border);
        overflow: hidden;
        transition: box-shadow 0.2s;
      }

      .outlet-settings-item.dragging {
        opacity: 0.5;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
      }

      .outlet-settings-item.drag-over {
        border-color: var(--panel-accent);
        box-shadow: 0 0 0 2px var(--panel-accent-dim);
      }

      .outlet-settings-bar {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 10px;
        cursor: pointer;
        user-select: none;
      }

      .outlet-settings-bar:hover {
        background: rgba(255, 255, 255, 0.03);
      }

      .outlet-drag-handle {
        cursor: grab;
        color: var(--secondary-text-color);
        padding: 2px;
        opacity: 0.5;
        transition: opacity 0.2s;
      }

      .outlet-settings-item.collapsed .outlet-drag-handle {
        opacity: 1;
      }

      .outlet-drag-handle:active {
        cursor: grabbing;
      }

      .outlet-drag-handle svg {
        width: 12px;
        height: 12px;
        fill: currentColor;
      }

      .outlet-settings-bar .outlet-name-display {
        flex: 1;
        font-size: 11px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .outlet-settings-bar .outlet-name-display.empty {
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .outlet-expand-icon {
        color: var(--secondary-text-color);
        transition: transform 0.2s;
      }

      .outlet-settings-item.collapsed .outlet-expand-icon {
        transform: rotate(-90deg);
      }

      .outlet-expand-icon svg {
        width: 14px;
        height: 14px;
        fill: currentColor;
      }

      .outlet-settings-body {
        padding: 0 10px 10px;
        display: block;
      }

      .outlet-settings-item.collapsed .outlet-settings-body {
        display: none;
      }

      .outlet-settings-header {
        display: flex;
        gap: 8px;
        align-items: flex-end;
        margin-bottom: 8px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--card-border);
      }

      .plugs-settings-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
      }

      @media (max-width: 700px) {
        .plugs-settings-grid {
          grid-template-columns: 1fr;
        }
      }

      .plug-settings-card {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 6px;
        padding: 8px;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }

      .plug-settings-title {
        font-size: 10px;
        font-weight: 600;
        color: var(--panel-accent);
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.4px;
      }

      .plug-settings-card .form-group {
        margin-bottom: 6px;
      }

      .plug-settings-card .form-group:last-child {
        margin-bottom: 0;
      }

      .plug-settings-card .form-label {
        font-size: 9px;
        margin-bottom: 2px;
      }

      .plug-settings-card .form-input,
      .plug-settings-card .form-select {
        padding: 6px 32px 6px 8px;
        font-size: 11px;
      }

      .outlet-settings-item .form-group {
        margin: 0;
      }

      .outlet-settings-item .form-label {
        font-size: 9px;
        margin-bottom: 3px;
      }

      .outlet-settings-item .form-input {
        padding: 6px 8px;
        font-size: 11px;
      }

      /* Shutoff row with test button */
      .shutoff-row {
        display: flex;
        gap: 6px;
        align-items: flex-end;
      }

      .shutoff-row .form-group {
        flex: 1;
      }

      .test-switch-btn {
        width: 32px;
        height: 32px;
        border-radius: 6px;
        border: 1px solid var(--input-border);
        background: var(--input-bg);
        color: var(--secondary-text-color);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
        flex-shrink: 0;
      }

      .test-switch-btn:hover {
        background: rgba(255, 255, 255, 0.08);
        color: var(--primary-text-color);
      }

      .test-switch-btn.on {
        background: var(--panel-accent-dim);
        border-color: var(--panel-accent);
        color: var(--panel-accent);
      }

      .test-switch-btn svg {
        width: 16px;
        height: 16px;
        fill: currentColor;
      }

      /* Light device: mapped light.* rows (mobile-first stacked cards) */
      .light-entity-rows {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .light-entity-card {
        padding: 10px;
        border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        background: rgba(0, 0, 0, 0.22);
        box-sizing: border-box;
      }

      .light-entity-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 10px;
      }

      .light-entity-card-title {
        font-size: 10px;
        font-weight: 600;
        color: var(--panel-accent);
        text-transform: uppercase;
        letter-spacing: 0.4px;
      }

      .light-entity-card .form-group {
        margin-bottom: 10px;
      }

      .light-entity-card .form-group:last-child {
        margin-bottom: 0;
      }

      .light-entity-card .form-input,
      .light-entity-card .entity-datalist-input {
        width: 100%;
        max-width: 100%;
        box-sizing: border-box;
      }

      .light-entity-power-wrgb {
        display: flex;
        flex-direction: column;
        gap: 0;
      }

      @media (min-width: 640px) {
        .light-entity-power-wrgb {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          align-items: start;
        }
      }

      .light-test-switch-btn {
        width: 100%;
        margin-top: 10px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        box-sizing: border-box;
        min-height: 40px;
      }

      .light-test-switch-btn svg {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        fill: currentColor;
      }

      .light-test-switch-btn.on {
        background: var(--panel-accent-dim);
        border-color: var(--panel-accent);
        color: var(--panel-accent);
      }


      .btn-small {
        padding: 6px 12px;
        font-size: 11px;
      }

      .outlet-assigned-list {
        margin-top: 8px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .outlet-assigned-card {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 10px;
        background: var(--input-bg);
        border-radius: 6px;
        border: 1px solid var(--card-border);
        transition: all 0.2s;
      }

      .outlet-assigned-card:hover {
        background: rgba(255, 255, 255, 0.05);
        border-color: var(--panel-accent);
      }

      .outlet-assigned-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .outlet-assigned-room {
        font-size: 9px;
        color: var(--secondary-text-color);
      }

      .outlet-assigned-name {
        font-size: 11px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .outlet-remove-icon {
        width: 14px;
        height: 14px;
        fill: var(--secondary-text-color);
        cursor: pointer;
        transition: fill 0.2s;
      }

      .outlet-remove-icon:hover {
        fill: var(--panel-danger);
      }

      .divider {
        height: 1px;
        background: var(--card-border);
        margin: 16px 0;
      }

      .icon-btn {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        border: none;
        background: transparent;
        color: var(--secondary-text-color);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s, color 0.2s;
      }

      .icon-btn:hover {
        background: rgba(255,255,255,0.08);
        color: var(--primary-text-color);
      }

      .icon-btn svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }

      .icon-btn.danger:hover {
        background: rgba(244, 67, 54, 0.15);
        color: var(--panel-danger);
      }

      /* Clickable appliance cards */
      .device-card,
      .outlet-card.outlet-face {
        cursor: pointer;
        transition: transform 0.1s ease, box-shadow 0.15s ease;
      }

      .device-card:hover,
      .outlet-card.outlet-face:hover {
        transform: translateY(-2px);
      }

      .outlet-card.outlet-face .receptacle {
        cursor: pointer;
        transition: box-shadow 0.15s ease;
      }

      .outlet-card.outlet-face .receptacle:hover {
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.5), inset 0 2px 4px rgba(0, 0, 0, 0.15);
      }

      .outlet-card.outlet-face .plug-receptacle {
        cursor: pointer;
      }

      /* Toggle confirmation modal */
      .toggle-confirm-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.15s ease;
      }

      @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }

      .toggle-confirm-modal {
        background: var(
          --ha-card-background-color,
          var(--card-background-color, var(--input-bg, #1e1e1e))
        );
        color: var(--primary-text-color, #e1e1e1);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 12px;
        padding: 20px 24px;
        min-width: 280px;
        max-width: 90vw;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
        animation: scaleIn 0.15s ease;
      }

      @keyframes scaleIn {
        from { transform: scale(0.95); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
      }

      .toggle-confirm-title {
        font-size: 18px;
        font-weight: 600;
        color: var(--primary-text-color, #f5f5f5);
        margin-bottom: 12px;
      }

      .toggle-confirm-message {
        font-size: 14px;
        color: var(--secondary-text-color, #c8c8c8);
        margin-bottom: 20px;
        line-height: 1.5;
      }

      .toggle-confirm-message strong {
        color: var(--primary-text-color, #ffffff);
        font-weight: 600;
      }

      .toggle-confirm-buttons {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
      }

      .toggle-confirm-cancel,
      .toggle-confirm-ok {
        padding: 10px 20px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: background 0.15s, transform 0.1s;
      }

      .toggle-confirm-cancel {
        background: rgba(255, 255, 255, 0.08);
        color: var(--primary-text-color, #e8e8e8);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.18));
      }

      .toggle-confirm-cancel:hover {
        background: rgba(255, 255, 255, 0.14);
      }

      .toggle-confirm-ok {
        background: var(--panel-accent, #03a9f4);
        color: #fff;
      }

      .toggle-confirm-ok:hover {
        background: #029ae5;
      }

      .toggle-confirm-ok:active,
      .toggle-confirm-cancel:active {
        transform: scale(0.97);
      }

      /* Zone health popup */
      .zone-health-popup-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10001;
        padding: 16px;
        box-sizing: border-box;
        animation: fadeIn 0.15s ease;
      }
      .zone-health-popup {
        background: var(--ha-card-background-color, var(--card-background-color, #1e1e1e));
        color: var(--primary-text-color, #e1e1e1);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 12px;
        width: 100%;
        max-width: 420px;
        max-height: 85vh;
        display: flex;
        flex-direction: column;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        animation: scaleIn 0.15s ease;
        overflow: hidden;
      }
      .zone-health-popup-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px 20px;
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
      }
      .zone-health-popup-header h3 {
        margin: 0;
        font-size: 17px;
        font-weight: 600;
      }
      .zone-health-popup-body {
        padding: 16px 20px;
        overflow-y: auto;
        font-size: 14px;
        line-height: 1.5;
      }
      .zone-health-popup-body p {
        margin: 0 0 8px 0;
      }
      .zone-health-popup-fix {
        margin-top: 16px;
        padding: 12px;
        background: rgba(255, 152, 0, 0.08);
        border-radius: 8px;
        border: 1px solid rgba(255, 152, 0, 0.2);
      }
      .zone-health-popup-fix h4 {
        margin: 0 0 8px 0;
        font-size: 13px;
        font-weight: 600;
        color: #ff9800;
      }
      .zone-health-popup-fix ol {
        margin: 0;
        padding-left: 20px;
        font-size: 12px;
      }
      .zone-health-popup-fix li {
        margin-bottom: 6px;
      }
      .zone-health-popup-actions {
        display: flex;
        gap: 10px;
        padding: 12px 20px 16px;
        border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
      }
      .zone-health-popup-actions .btn {
        flex: 1;
      }

      /* Minisplit / AC zone automation safety (non-admin) */
      .ac-safety-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10001;
        padding: 16px;
        box-sizing: border-box;
        animation: fadeIn 0.15s ease;
      }
      .ac-safety-modal {
        background: var(
          --ha-card-background-color,
          var(--card-background-color, var(--input-bg, #1e1e1e))
        );
        color: var(--primary-text-color, #e1e1e1);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 12px;
        width: 100%;
        max-width: 440px;
        max-height: min(85vh, 640px);
        display: flex;
        flex-direction: column;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        animation: scaleIn 0.15s ease;
      }
      .ac-safety-title {
        font-size: 17px;
        font-weight: 600;
        color: var(--primary-text-color, #f5f5f5);
        padding: 18px 20px 0;
        flex-shrink: 0;
      }
      .ac-safety-body {
        padding: 12px 20px 16px;
        overflow-y: auto;
        flex: 1;
        min-height: 0;
      }
      .ac-safety-lead {
        font-size: 13px;
        line-height: 1.5;
        color: var(--primary-text-color, #e8e8e8);
        margin: 0 0 12px;
      }
      .ac-safety-note {
        font-size: 12px;
        line-height: 1.45;
        color: var(--secondary-text-color, #a8a8a8);
        margin: 0 0 14px;
        padding: 10px 12px;
        background: rgba(255, 255, 255, 0.04);
        border-radius: 8px;
        border-left: 3px solid var(--panel-accent, #03a9f4);
      }
      .ac-safety-steps-title {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--secondary-text-color, #b0b0b0);
        margin: 0 0 8px;
      }
      .ac-safety-steps {
        margin: 0;
        padding-left: 1.15rem;
        font-size: 13px;
        line-height: 1.5;
        color: var(--secondary-text-color, #c8c8c8);
      }
      .ac-safety-steps li {
        margin-bottom: 8px;
      }
      .ac-safety-steps li:last-child {
        margin-bottom: 0;
      }
      .ac-safety-setup-intro {
        font-size: 13px;
        line-height: 1.45;
        color: var(--secondary-text-color, #c8c8c8);
        margin: 0 0 12px;
      }
      .ac-safety-part {
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
      }
      .ac-safety-setup-intro + .ac-safety-part {
        margin-top: 0;
        padding-top: 0;
        border-top: none;
      }
      .ac-safety-part-title {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--secondary-text-color, #b0b0b0);
        margin: 0 0 8px;
      }
      .ac-safety-steps.ac-safety-steps--tight li {
        margin-bottom: 6px;
      }
      .ac-safety-disclosure {
        margin-top: 10px;
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 8px;
        overflow: hidden;
        background: rgba(0, 0, 0, 0.15);
      }
      .ac-safety-disclosure summary {
        cursor: pointer;
        padding: 9px 12px;
        font-size: 12px;
        font-weight: 600;
        color: var(--panel-accent, #03a9f4);
        list-style: none;
        user-select: none;
      }
      .ac-safety-disclosure summary::-webkit-details-marker {
        display: none;
      }
      .ac-safety-disclosure summary::marker {
        content: '';
      }
      .ac-safety-disclosure summary:hover {
        background: rgba(255, 255, 255, 0.04);
      }
      .ac-safety-disclosure summary:focus-visible {
        outline: 2px solid var(--panel-accent, #03a9f4);
        outline-offset: -2px;
      }
      .ac-safety-disclosure[open] summary {
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
      }
      .settings-fold {
        margin-bottom: 14px;
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.12));
        border-radius: 8px;
        overflow: hidden;
        background: rgba(0, 0, 0, 0.08);
      }
      .settings-fold-summary {
        cursor: pointer;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 600;
        color: var(--primary-text-color);
        list-style: none;
        user-select: none;
      }
      .settings-fold-summary::-webkit-details-marker {
        display: none;
      }
      .settings-fold-summary::marker {
        content: '';
      }
      .settings-fold[open] > .settings-fold-summary {
        border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
      }
      .settings-fold-body {
        padding: 10px 14px 14px;
      }
      .ac-safety-screenshot {
        display: block;
        width: 100%;
        max-width: 100%;
        height: auto;
        border-radius: 0 0 6px 6px;
        box-sizing: border-box;
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.1));
        border-top: none;
        background: rgba(255, 255, 255, 0.03);
      }
      .ac-safety-buttons {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
        flex-wrap: wrap;
        padding: 12px 20px 18px;
        border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
        flex-shrink: 0;
      }
      .ac-safety-cancel,
      .ac-safety-ok {
        padding: 10px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: background 0.15s, transform 0.1s;
      }
      .ac-safety-cancel {
        background: rgba(255, 255, 255, 0.08);
        color: var(--primary-text-color, #e8e8e8);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.18));
      }
      .ac-safety-cancel:hover {
        background: rgba(255, 255, 255, 0.14);
      }
      .ac-safety-ok {
        background: var(--panel-accent, #03a9f4);
        color: #fff;
      }
      .ac-safety-ok:hover {
        background: #029ae5;
      }
      .ac-safety-ok:active,
      .ac-safety-cancel:active {
        transform: scale(0.97);
      }
      .ac-safety-ok:disabled {
        background: rgba(255, 255, 255, 0.15);
        color: rgba(255, 255, 255, 0.4);
        cursor: not-allowed;
      }
      .ac-safety-ok:disabled:hover {
        background: rgba(255, 255, 255, 0.15);
      }
      /* Wizard step indicators */
      .ac-wizard-steps {
        display: flex;
        justify-content: center;
        gap: 8px;
        padding: 14px 20px 0;
        flex-shrink: 0;
      }
      .ac-wizard-step-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.2);
        transition: background 0.2s, transform 0.2s;
      }
      .ac-wizard-step-dot.active {
        background: var(--panel-accent, #03a9f4);
        transform: scale(1.15);
      }
      .ac-wizard-step-dot.completed {
        background: var(--success-color, #4caf50);
      }
      .ac-wizard-step-content {
        display: none;
        animation: fadeIn 0.2s ease;
      }
      .ac-wizard-step-content.active {
        display: block;
      }
      .ac-wizard-nav {
        display: flex;
        gap: 10px;
        justify-content: space-between;
        padding: 12px 20px 18px;
        border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
        flex-shrink: 0;
      }
      .ac-wizard-nav-left,
      .ac-wizard-nav-right {
        display: flex;
        gap: 10px;
      }
      .ac-wizard-btn {
        padding: 10px 18px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: background 0.15s, transform 0.1s;
      }
      .ac-wizard-btn-back {
        background: rgba(255, 255, 255, 0.08);
        color: var(--primary-text-color, #e8e8e8);
        border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.18));
      }
      .ac-wizard-btn-back:hover {
        background: rgba(255, 255, 255, 0.14);
      }
      .ac-wizard-btn-next {
        background: var(--panel-accent, #03a9f4);
        color: #fff;
      }
      .ac-wizard-btn-next:hover {
        background: #029ae5;
      }
      .ac-wizard-btn:active {
        transform: scale(0.97);
      }
      .ac-wizard-privacy-warning {
        font-size: 12px;
        line-height: 1.5;
        color: #ff5252;
        margin: 14px 0 0;
        padding: 12px 14px;
        background: rgba(255, 82, 82, 0.1);
        border-radius: 8px;
        border-left: 3px solid #ff5252;
      }
      .ac-wizard-privacy-warning strong {
        color: #ff5252;
      }
      .ac-wizard-step-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: var(--panel-accent, #03a9f4);
        color: #fff;
        font-size: 13px;
        font-weight: 600;
        margin-right: 8px;
        flex-shrink: 0;
      }
      .ac-wizard-step-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--primary-text-color, #f5f5f5);
        margin: 0 0 12px;
        display: flex;
        align-items: center;
      }
    `;

    this._destroyStatsRoomsPie();

    if (this._loading) {
      this.shadowRoot.innerHTML = `
        <style>${styles}</style>
        <div class="panel-container">
          <div class="panel-header">
            <button class="menu-btn" id="menu-btn" title="Menu">
              <svg viewBox="0 0 24 24">${icons.menu}</svg>
            </button>
            <h1 class="panel-title">
              <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.flash}</svg>
              Home Energy
            </h1>
          </div>
          <div class="content-area">
            <div class="loading">
              <div class="loading-spinner"></div>
              <span>Loading energy data...</span>
            </div>
          </div>
        </div>
      `;
      return;
    }

    if (this._error) {
      this.shadowRoot.innerHTML = `
        <style>${styles}</style>
        <div class="panel-container">
          <div class="panel-header">
            <button class="menu-btn" id="menu-btn" title="Menu">
              <svg viewBox="0 0 24 24">${icons.menu}</svg>
            </button>
            <h1 class="panel-title">
              <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.flash}</svg>
              Home Energy
            </h1>
          </div>
          <div class="content-area">
            <div class="empty-state">
              <svg class="empty-state-icon" viewBox="0 0 24 24" style="fill: var(--panel-danger);">
                ${icons.warning}
              </svg>
              <h3 class="empty-state-title">Error Loading Data</h3>
              <p class="empty-state-desc">${this._error}</p>
              <button class="btn btn-primary" id="retry-btn">Retry</button>
            </div>
          </div>
        </div>
      `;
      const retryBtn = this.shadowRoot.querySelector('#retry-btn');
      if (retryBtn) retryBtn.addEventListener('click', () => this._loadConfig());
      return;
    }

    if (this._showSettings) {
      this._renderSettings(styles);
    } else {
      this._renderMain(styles);
    }
  }

  _renderMain(styles) {
    const rooms = this._config?.rooms || [];
    const powerData = this._powerData?.rooms || [];
    const showStatistics = this._dashboardView === 'statistics';

    // Calculate totals
    let totalWatts = 0;
    let totalDayWh = 0;
    powerData.forEach(r => {
      totalWatts += r.total_watts;
      totalDayWh += r.total_day_wh;
    });

    // Get event counts
    const totalWarnings = this._powerData?.total_warnings || 0;
    const totalShutoffs = this._powerData?.total_shutoffs || 0;
    const totalPowerCycles = this._powerData?.total_power_cycles || 0;

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="panel-container">
        <div class="panel-header">
          <button class="menu-btn" id="menu-btn" title="Menu">
            <svg viewBox="0 0 24 24">${icons.menu}</svg>
          </button>
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.flash}</svg>
            Home Energy
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="settings-btn">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
              Settings
            </button>
          </div>
        </div>

        <div class="content-area">
          <div class="view-tabs">
            <button class="view-tab ${this._dashboardView === 'rooms' ? 'active' : ''}" data-view="rooms">Rooms</button>
            <button class="view-tab ${this._dashboardView === 'statistics' ? 'active' : ''}" data-view="statistics">Statistics</button>
          </div>
          ${showStatistics ? this._renderStatisticsView() : ''}
          ${!showStatistics ? (rooms.length === 0 ? this._renderEmptyState() : `
            <div class="summary-stats">
              <div class="stat-card graph-clickable" data-graph-type="total_watts_intraday" title="Power draw right now (tap for chart)">
                <div class="stat-value" id="summary-total-watts">${totalWatts.toFixed(1)} W</div>
                <div class="stat-label">Load</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_wh_intraday" title="Home kWh since midnight (tap for chart)">
                <div class="stat-value" id="summary-total-day">${(totalDayWh / 1000).toFixed(2)} kWh</div>
                <div class="stat-label">Usage</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_warnings" title="Threshold voice alerts today">
                <div class="stat-value" id="summary-warnings">${totalWarnings}</div>
                <div class="stat-label">Warnings</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_shutoffs" title="Safety plug shutoffs today">
                <div class="stat-value" id="summary-shutoffs">${totalShutoffs}</div>
                <div class="stat-label">Shutoffs</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_power_cycles" title="Enforcement outlet cycles today">
                <div class="stat-value" id="summary-power-cycles">${totalPowerCycles}</div>
                <div class="stat-label">Cycles</div>
              </div>
            </div>
            <div class="rooms-grid">
              ${rooms.map((room) => this._renderRoomCard(room)).join('')}
            </div>
          `) : ''}
          </div>
        </div>
        ${this._graphOpen ? this._renderGraphModal() : ''}
      </div>
    `;

    this._attachEventListeners();
    this._syncGraphModalAfterRender();
    this._syncRoomsGridTitleFitObserver();
    if (this._dashboardView === 'rooms' && rooms.length > 0 && !showStatistics) {
      queueMicrotask(() => this._scheduleRoomHeaderTitleFit());
    }
    if (this._dashboardView === 'statistics' && this._statsRoomsView === 'pie') {
      queueMicrotask(() => void this._syncStatsRoomsPie());
    }
  }

  _isEventLogType(type) {
    return type === 'total_warnings' || type === 'total_shutoffs' || type === 'total_power_cycles'
      || type === 'room_warnings' || type === 'room_shutoffs' || type === 'room_power_cycles'
      || type === 'stat_total_warnings' || type === 'stat_total_shutoffs' || type === 'stat_total_power_cycles'
      || type === 'stat_room_warnings' || type === 'stat_room_shutoffs' || type === 'stat_room_power_cycles';
  }

  _eventLogEscape(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  _eventLogReadingsLine(e) {
    const parts = [];
    const addW = (label, v) => {
      if (v == null || v === '') return;
      const n = Number(v);
      if (Number.isNaN(n)) return;
      parts.push(`${label} ${Math.round(n)} W`);
    };
    addW('Load', e.room_watts);
    if (e.room_threshold != null && e.room_threshold !== '') {
      const t = Number(e.room_threshold);
      if (!Number.isNaN(t)) parts.push(`Threshold ${Math.round(t)} W`);
    }
    addW('Outlet', e.outlet_watts);
    if (e.outlet_threshold != null && e.outlet_threshold !== '') {
      const ot = Number(e.outlet_threshold);
      if (!Number.isNaN(ot)) parts.push(`Limit ${Math.round(ot)} W`);
    }
    if (e.enforcement_phase != null && e.enforcement_phase !== '') {
      const p = Number(e.enforcement_phase);
      if (!Number.isNaN(p)) parts.push(`Phase ${Math.round(p)}`);
    }
    if (e.volume_percent != null && e.volume_percent !== '') {
      const v = Number(e.volume_percent);
      if (!Number.isNaN(v)) parts.push(`Volume ${Math.round(v)}%`);
    }
    if (e.outlets_cycled != null && e.outlets_cycled !== '') {
      const c = Number(e.outlets_cycled);
      if (!Number.isNaN(c)) parts.push(`${Math.round(c)} outlet(s) cycled`);
    }
    return parts.join(' · ');
  }

  _eventLogEntryHasDetails(e) {
    const msg = e.tts_message;
    const hasMsg = msg != null && String(msg).trim() !== '';
    return hasMsg || !!this._eventLogReadingsLine(e);
  }

  _graphModalTitle() {
    const go = this._graphOpen;
    if (!go) return 'History';
    const type = go.type;
    const roomName = go.roomName || '';
    if (type === 'outlet_wh' && go.outletGraphTitle) {
      return go.outletGraphTitle;
    }
    const labels = {
      total_wh: 'Usage (kWh)', total_watts_intraday: 'Power now (W)', total_wh_intraday: 'Home kWh today (minute data)',
      total_warnings: 'Threshold Warnings (24h)', total_shutoffs: 'Safety Shutoffs (24h)',
      total_power_cycles: 'Power Cycles (24h)',
      room_wh: `${roomName} Usage (kWh) by hour today`, room_warnings: `${roomName} Warnings (24h)`, room_shutoffs: `${roomName} Shutoffs (24h)`,
      room_power_cycles: `${roomName} Power Cycles (24h)`,
      stat_total_wh: 'Home daily usage',
      stat_room_wh: `${roomName || 'Room'} daily usage`,
      stat_total_warnings: 'Threshold Warnings',
      stat_total_shutoffs: 'Safety Shutoffs',
      stat_total_power_cycles: 'Power Cycles',
      stat_room_warnings: `${roomName || 'Room'} Warnings`,
      stat_room_shutoffs: `${roomName || 'Room'} Shutoffs`,
      stat_room_power_cycles: `${roomName || 'Room'} Power Cycles`,
    };
    let title = labels[type] || 'History';
    const statPeriodEvent =
      type === 'stat_total_warnings' || type === 'stat_total_shutoffs' || type === 'stat_total_power_cycles'
      || type === 'stat_room_warnings' || type === 'stat_room_shutoffs' || type === 'stat_room_power_cycles';
    if ((type === 'stat_total_wh' || type === 'stat_room_wh' || statPeriodEvent) && go?.date_start && go?.date_end) {
      title = `${title} · ${this._formatDateRange(go.date_start)} – ${this._formatDateRange(go.date_end)}`;
    }
    return title;
  }

  _renderGraphModal() {
    if (!this._graphOpen) return '';
    const type = this._graphOpen.type;
    const roomId = this._graphOpen.roomId;
    const roomName = this._graphOpen.roomName || '';
    const title = this._graphModalTitle();
    if (this._graphLoading) {
      return `
      <div class="graph-modal-overlay" id="graph-modal-overlay">
        <div class="graph-modal">
          <div class="graph-modal-header">
            <h2 class="graph-modal-title">${title}</h2>
            <button type="button" class="graph-modal-close" id="graph-modal-close" aria-label="Close">×</button>
          </div>
          <div class="graph-modal-body">
            <div class="graph-modal-loading">
              <div class="graph-modal-loading-spinner" aria-hidden="true"></div>
              <span>Loading history…</span>
            </div>
          </div>
        </div>
      </div>`;
    }
    if (this._graphLoadError) {
      return `
      <div class="graph-modal-overlay" id="graph-modal-overlay">
        <div class="graph-modal">
          <div class="graph-modal-header">
            <h2 class="graph-modal-title">${title}</h2>
            <button type="button" class="graph-modal-close" id="graph-modal-close" aria-label="Close">×</button>
          </div>
          <div class="graph-modal-body">
            <p class="graph-modal-error">${this._eventLogEscape(this._graphLoadError)}</p>
          </div>
        </div>
      </div>`;
    }
    if (!this._graphData) return '';
    const isEventLog = this._isEventLogType(type);
    let bodyContent = '';
    if (isEventLog) {
      const events = this._graphData.events || [];
      let filterType = 'warning';
      if (type.includes('shutoffs')) filterType = 'shutoff';
      else if (type.includes('power_cycles')) filterType = 'power_cycle';
      const filtered = events.filter(e => e.type === filterType);
      const periodLog = !!(this._graphOpen?.date_start && this._graphOpen?.date_end);
      const emptyMsg = periodLog
        ? 'No events in this period'
        : 'No events in the last 24 hours';
      const truncNote = this._graphData.truncated
        ? '<p class="event-log-truncated" style="color: var(--secondary-text-color); text-align: center; padding: 8px 16px 0; font-size: 12px;">Showing the most recent 5000 events; list was truncated.</p>'
        : '';
      bodyContent = `
        <div class="event-log-container">
          ${filtered.length === 0
            ? `<p style="color: var(--secondary-text-color); text-align: center; padding: 24px;">${emptyMsg}</p>`
            : `
            <ul class="event-log-list">
              ${filtered.map((e) => {
                const isPc = e.type === 'power_cycle';
                const badgeStyle = isPc
                  ? 'background: rgba(3, 169, 244, 0.2); color: var(--panel-accent, #03a9f4);'
                  : (e.tts_succeeded ? 'background: rgba(76, 175, 80, 0.2); color: #4caf50;' : 'background: rgba(244, 67, 54, 0.2); color: #f44336;');
                const badgeText = isPc ? 'Outlets cycled' : (e.tts_succeeded ? 'TTS Succeeded' : 'TTS Failed');
                const who = `${e.room_name || ''}${e.outlet_name ? ' – ' + e.outlet_name : ''}`;
                const hasDetail = this._eventLogEntryHasDetails(e);
                const readings = this._eventLogReadingsLine(e);
                const msgHtml = e.tts_message != null && String(e.tts_message).trim() !== ''
                  ? `<p class="event-log-message">${this._eventLogEscape(e.tts_message)}</p>`
                  : '';
                const readingsHtml = readings
                  ? `<p class="event-log-readings">${this._eventLogEscape(readings)}</p>`
                  : '';
                const detailBlock = hasDetail
                  ? `<div class="event-log-detail">${msgHtml}${readingsHtml}</div>`
                  : '';
                return `
                <li class="event-log-entry">
                  <div class="event-log-entry-row">
                    <span class="event-log-ts">${e.ts ? e.ts.replace('T', ' ').slice(0, 19) : '—'}</span>
                    <span class="event-log-who">${this._eventLogEscape(who)}</span>
                    <span class="event-log-badge tts-badge" style="${badgeStyle}">${badgeText}</span>
                  </div>
                  ${detailBlock}
                </li>`;
              }).join('')}
            </ul>
            ${truncNote}
          `}
        </div>
      `;
    } else {
      bodyContent = '<div class="graph-chart-container" id="graph-apex-chart"></div>';
    }
    return `
      <div class="graph-modal-overlay" id="graph-modal-overlay">
        <div class="graph-modal">
          <div class="graph-modal-header">
            <h2 class="graph-modal-title">${title}</h2>
            <button type="button" class="graph-modal-close" id="graph-modal-close" aria-label="Close">×</button>
          </div>
          <div class="graph-modal-body">
            ${bodyContent}
          </div>
        </div>
      </div>
    `;
  }

  /** Start of local calendar day (ms). */
  _startOfLocalDayMs() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }

  /**
   * Chart data sources (must stay aligned with backend):
   * - Event logs: get_event_log (warnings/shutoffs/power_cycles; home or room).
   * - Intraday W: get_intraday_history (timestamps + watts).
   * - Intraday kWh (home): cumulative area + reference_kwh_today offset to match day ledger.
   * - Intraday kWh (room): same intraday fetch, native 24 hourly kWh bars.
   * - Intraday kWh (outlet): get_intraday_history with outlet_index (+ plug_slot for dual outlet).
   * - Stat billing (stat_*): get_daily_history date_start/end → bar chart kWh/day.
   * - Legacy daily (31d): get_daily_history days=31 for total_* / room_* non-intraday types.
   */
  async _openGraph(type, roomId = null, roomName = null, billingRange = null, graphOpts = null) {
    try {
      const isIntraday =
        type === 'total_watts_intraday' ||
        type === 'total_wh_intraday' ||
        type === 'room_wh' ||
        type === 'outlet_wh';
      const isStatBilling = type === 'stat_total_wh' || type === 'stat_room_wh';
      const isEventLog = this._isEventLogType(type);
      let result;
      if (isEventLog) {
        const payload = { type: 'smart_dashboards/get_event_log' };
        if (roomId) payload.room_id = roomId;
        if (billingRange?.date_start && billingRange?.date_end) {
          payload.date_start = billingRange.date_start;
          payload.date_end = billingRange.date_end;
        } else {
          payload.since_hours = 24;
        }
        result = await this._hass.callWS(payload);
      } else if (isStatBilling) {
        const br =
          billingRange?.date_start && billingRange?.date_end
            ? billingRange
            : this._statisticsGraphDateRange();
        const s = this._statsData;
        const dhRange = s?.daily_history_range;
        const cachedOk =
          s?.daily_history &&
          typeof s.daily_history === 'object' &&
          ((s.date_start === br.date_start && s.date_end === br.date_end) ||
            (dhRange?.date_start === br.date_start && dhRange?.date_end === br.date_end));
        if (cachedOk) {
          result = s.daily_history;
        } else {
          result = await this._hass.callWS({
            type: 'smart_dashboards/get_daily_history',
            date_start: br.date_start,
            date_end: br.date_end,
          });
        }
        billingRange = br;
      } else if (type === 'outlet_wh' && graphOpts && graphOpts.outletIndex != null) {
        const payload = {
          type: 'smart_dashboards/get_intraday_history',
          minutes: 1440,
          room_id: roomId,
          outlet_index: graphOpts.outletIndex,
        };
        if (graphOpts.plugSlot != null) payload.plug_slot = graphOpts.plugSlot;
        result = await this._hass.callWS(payload);
      } else if (isIntraday) {
        const payload = { type: 'smart_dashboards/get_intraday_history', minutes: 1440 };
        if (roomId) payload.room_id = roomId;
        result = await this._hass.callWS(payload);
      } else {
        result = await this._hass.callWS({ type: 'smart_dashboards/get_daily_history', days: 31 });
      }
      this._graphOpen = {
        type,
        roomId,
        roomName,
        date_start: billingRange?.date_start || null,
        date_end: billingRange?.date_end || null,
        outletIndex: graphOpts?.outletIndex ?? null,
        plugSlot: graphOpts?.plugSlot ?? null,
        outletGraphTitle: graphOpts?.outletGraphTitle ?? null,
        outletSeriesLabel: graphOpts?.outletSeriesLabel ?? null,
      };
      this._graphData = result;
      this._render();
    } catch (e) {
      console.error('Failed to load graph data:', e);
      showToast(this.shadowRoot, 'Failed to load history', 'error');
    }
  }

  _teardownBillingBarChartNative() {
    if (typeof this._billingBarNativeCleanup === 'function') {
      try {
        this._billingBarNativeCleanup();
      } catch (_e) {
        /* stale */
      }
      this._billingBarNativeCleanup = null;
    }
  }

  /** Local hour label 0–23 → "12am" … "11pm". */
  _hourLabel12h(hour) {
    const h = Number(hour);
    if (h === 0) return '12am';
    if (h < 12) return `${h}am`;
    if (h === 12) return '12pm';
    return `${h - 12}pm`;
  }

  /**
   * Per-hour kWh (24 buckets, local calendar day) from uneven W samples via trapezoids split at hour boundaries.
   * Returns 24 floats (kWh); hours after `now` contribute only from samples clipped at now.
   */
  _aggregateHourlyKwh(timestamps, watts) {
    const dayStart = this._startOfLocalDayMs();
    const nextMidnight = new Date(dayStart);
    nextMidnight.setDate(nextMidnight.getDate() + 1);
    const dayEndMs = nextMidnight.getTime();
    const now = Date.now();
    const hourlyWh = new Array(24).fill(0);

    const pairs = [];
    const n = Math.min(timestamps.length, watts.length);
    for (let i = 0; i < n; i++) {
      const t = this._parseChartTimeMs(timestamps[i]);
      if (Number.isNaN(t) || t < dayStart || t >= dayEndMs) continue;
      pairs.push({ t, w: Number(watts[i]) || 0 });
    }
    pairs.sort((a, b) => a.t - b.t);

    for (let i = 1; i < pairs.length; i++) {
      const origT0 = pairs[i - 1].t;
      const origT1 = pairs[i].t;
      const w0 = pairs[i - 1].w;
      const w1 = pairs[i].w;
      if (!(origT1 > origT0)) continue;
      const t0 = Math.max(origT0, dayStart);
      const t1 = Math.min(origT1, Math.min(now, dayEndMs));
      if (!(t1 > t0)) continue;

      let segStart = t0;
      while (segStart < t1) {
        const h0 = Math.floor((segStart - dayStart) / 3600000);
        if (h0 < 0 || h0 > 23) break;
        const hStart = dayStart + h0 * 3600000;
        const hEnd = Math.min(hStart + 3600000, dayEndMs);
        const segEnd = Math.min(t1, hEnd);
        const wa = w0 + ((w1 - w0) * (segStart - origT0)) / (origT1 - origT0);
        const wb = w0 + ((w1 - w0) * (segEnd - origT0)) / (origT1 - origT0);
        const dtH = (segEnd - segStart) / 3600000;
        hourlyWh[h0] += ((wa + wb) / 2) * dtH;
        segStart = segEnd;
      }
    }
    return hourlyWh.map((wh) => wh / 1000);
  }

  /**
   * Shadow-DOM-safe kWh bars (Statistics billing daily + room hourly). Apex bar hover breaks under retargeting (#3237).
   */
  _renderBillingBarChartNative(container, opts) {
    const {
      categories,
      values,
      seriesName,
      yFormatter,
      accent,
      textColor,
      ariaCountNoun = 'days',
      xLabelsMode = 'daily',
    } = opts;
    this._teardownBillingBarChartNative();
    container.innerHTML = '';
    const n = values.length;
    if (n === 0 || categories.length !== n) {
      container.innerHTML =
        '<p style="color:var(--secondary-text-color);padding:20px;text-align:center;">No data yet</p>';
      return;
    }
    const nums = values.map((v) => Math.max(0, Number(v) || 0));
    const maxV = Math.max(...nums, 1e-9);
    const tickSteps = 5;
    const tickVals = [];
    for (let t = 0; t <= tickSteps; t++) {
      tickVals.push((maxV * t) / tickSteps);
    }

    const wrap = document.createElement('div');
    wrap.className = 'billing-bar-chart-native';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', `${seriesName}, ${n} ${ariaCountNoun}`);

    const tooltip = document.createElement('div');
    tooltip.className = 'billing-bar-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.hidden = true;

    const body = document.createElement('div');
    body.className = 'billing-bar-chart-body';

    const yAxis = document.createElement('div');
    yAxis.className = 'billing-bar-y-axis';
    yAxis.setAttribute('aria-hidden', 'true');
    for (let i = tickVals.length - 1; i >= 0; i--) {
      const el = document.createElement('span');
      el.textContent = yFormatter(tickVals[i]);
      yAxis.appendChild(el);
    }

    const plot = document.createElement('div');
    plot.className = 'billing-bar-plot';

    for (let t = 1; t <= tickSteps; t++) {
      const line = document.createElement('div');
      line.className = 'billing-bar-grid-line';
      line.style.bottom = `${(t / tickSteps) * 100}%`;
      plot.appendChild(line);
    }

    const positionTooltip = (anchorEl) => {
      const wrapRect = wrap.getBoundingClientRect();
      const ar = anchorEl.getBoundingClientRect();
      tooltip.hidden = false;
      requestAnimationFrame(() => {
        const tw = tooltip.offsetWidth || 160;
        const th = tooltip.offsetHeight || 48;
        let left = ar.left - wrapRect.left + ar.width / 2 - tw / 2;
        left = Math.max(6, Math.min(left, wrapRect.width - tw - 6));
        let top = ar.top - wrapRect.top - th - 8;
        if (top < 6) top = ar.bottom - wrapRect.top + 8;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      });
    };

    const setTipContent = (i) => {
      const cat = categories[i];
      const v = nums[i];
      tooltip.replaceChildren();
      const t1 = document.createElement('div');
      t1.style.fontWeight = '600';
      t1.style.marginBottom = '4px';
      t1.textContent = cat;
      const t2 = document.createElement('div');
      t2.style.color = textColor || '#e1e1e1';
      t2.textContent = `${seriesName}: ${yFormatter(v)}`;
      tooltip.appendChild(t1);
      tooltip.appendChild(t2);
    };

    const ac = new AbortController();
    const sig = ac.signal;
    const supportsTouchTap =
      typeof window.matchMedia === 'function' &&
      (window.matchMedia('(pointer: coarse)').matches ||
        window.matchMedia('(hover: none)').matches);
    /** Tap-pinned bar (touch/coarse); mouse hover unchanged on fine pointer. */
    let tapPinnedBar = null;

    nums.forEach((v, i) => {
      const col = document.createElement('div');
      col.className = 'billing-bar-column';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'billing-bar-hit';
      btn.setAttribute('aria-label', `${categories[i]}: ${yFormatter(v)}`);
      const fill = document.createElement('span');
      fill.className = 'billing-bar-fill';
      const pct = maxV > 0 ? (v / maxV) * 100 : 0;
      fill.style.height = v > 0 ? `${Math.max(pct, 1.2)}%` : '0px';
      fill.style.background = accent;
      btn.appendChild(fill);
      col.appendChild(btn);
      plot.appendChild(col);

      const show = () => {
        setTipContent(i);
        positionTooltip(btn);
      };
      const hide = () => {
        tooltip.hidden = true;
      };
      btn.addEventListener('pointerenter', show, { signal: sig });
      btn.addEventListener('pointerleave', hide, { signal: sig });
      btn.addEventListener('focus', show, { signal: sig });
      btn.addEventListener('blur', hide, { signal: sig });

      if (supportsTouchTap) {
        btn.addEventListener(
          'click',
          (e) => {
            e.stopPropagation();
            if (tapPinnedBar === btn && !tooltip.hidden) {
              hide();
              tapPinnedBar = null;
              return;
            }
            tapPinnedBar = btn;
            show();
          },
          { signal: sig },
        );
      }
    });

    if (supportsTouchTap) {
      wrap.addEventListener(
        'click',
        (e) => {
          if (!e.target.closest('.billing-bar-hit')) {
            tooltip.hidden = true;
            tapPinnedBar = null;
          }
        },
        { signal: sig },
      );
    }

    this._billingBarNativeCleanup = () => ac.abort();

    const xRow = document.createElement('div');
    const dense = n > 12;
    xRow.className = [
      'billing-bar-x-labels',
      dense ? 'billing-bar-x-labels--dense' : '',
      xLabelsMode === 'hourly' ? 'billing-bar-x-labels--hourly' : '',
    ]
      .filter(Boolean)
      .join(' ');
    categories.forEach((cat) => {
      const x = document.createElement('span');
      x.className = 'billing-bar-x-label';
      x.textContent = cat;
      x.title = cat;
      xRow.appendChild(x);
    });

    body.appendChild(yAxis);
    body.appendChild(plot);
    wrap.appendChild(body);
    wrap.appendChild(xRow);
    wrap.appendChild(tooltip);
    container.appendChild(wrap);
  }

  async _initApexChart() {
    const container = this.shadowRoot.getElementById('graph-apex-chart');
    if (!container || !this._graphData || !this._graphOpen) return;
    const type = this._graphOpen.type;
    const roomId = this._graphOpen.roomId;
    const roomName = this._graphOpen.roomName || '';

    const isIntraday =
      type === 'total_watts_intraday' ||
      type === 'total_wh_intraday' ||
      type === 'room_wh' ||
      type === 'outlet_wh';
    const isStatBillingModal = type === 'stat_total_wh' || type === 'stat_room_wh';
    const outletSeriesLabel = this._graphOpen.outletSeriesLabel || '';
    /** Daily billing bars: category axis + numeric series (datetime bars mis-map hover/tooltip in Apex). */
    let billingCategories = null;
    let billingValues = null;
    /** Room intraday kWh: native 24 hourly bars (not cumulative area). */
    let useRoomHourlyBars = false;
    let roomHourlyCategories = null;
    let roomHourlyValues = null;
    /** Set for intraday kWh charts: tighter y-axis + label precision */
    let intradayKwhYMax = null;

    let seriesData = [];
    let seriesName = 'Value';
    let yFormatter = (v) => {
      if (v == null || Number.isNaN(v)) return '—';
      const n = Number(v);
      return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
    };
    let strokeCurve = 'smooth';

    if (isIntraday) {
      const timestamps = this._graphData.timestamps || [];
      const watts = this._graphData.watts || [];
      const n = Math.min(timestamps.length, watts.length);
      const dayStart = this._startOfLocalDayMs();
      const dayEnd = Date.now();
      if (type === 'room_wh' || type === 'outlet_wh') {
        const tsDay = [];
        const wDay = [];
        for (let i = 0; i < n; i++) {
          const x = this._parseChartTimeMs(timestamps[i]);
          if (Number.isNaN(x) || x < dayStart || x > dayEnd) continue;
          tsDay.push(timestamps[i]);
          wDay.push(watts[i]);
        }
        useRoomHourlyBars = true;
        if (tsDay.length === 0) {
          roomHourlyValues = null;
          roomHourlyCategories = null;
        } else {
          roomHourlyValues = this._aggregateHourlyKwh(tsDay, wDay);
          roomHourlyCategories = Array.from({ length: 24 }, (_, h) =>
            this._hourLabel12h(h),
          );
          const peakKwh = roomHourlyValues.reduce(
            (m, x) => Math.max(m, Number(x) || 0),
            0,
          );
          const decimals = peakKwh <= 0.02 ? 3 : peakKwh <= 0.5 ? 2 : 2;
          yFormatter = (v) => (v == null ? '—' : `${Number(v).toFixed(decimals)} kWh`);
          const labelForSeries =
            type === 'outlet_wh'
              ? outletSeriesLabel || 'Outlet'
              : roomName || 'Room';
          seriesName = `${labelForSeries} kWh per hour`;
        }
        seriesData = [];
      } else if (type === 'total_wh_intraday') {
        seriesName = 'kWh (cumulative today)';
        const tsDay = [];
        const wDay = [];
        for (let i = 0; i < n; i++) {
          const x = this._parseChartTimeMs(timestamps[i]);
          if (Number.isNaN(x) || x < dayStart || x > dayEnd) continue;
          tsDay.push(timestamps[i]);
          wDay.push(watts[i]);
        }
        const cum = this._cumulativeKwhFromPowerSamples(tsDay, wDay);
        seriesData = [];
        for (let i = 0; i < tsDay.length; i++) {
          const x = this._parseChartTimeMs(tsDay[i]);
          if (!Number.isNaN(x)) seriesData.push([x, cum[i]]);
        }
        seriesData.sort((a, b) => a[0] - b[0]);
        strokeCurve = 'straight';
        const refKwh = Number(this._graphData.reference_kwh_today);
        if (
          Number.isFinite(refKwh) &&
          refKwh >= 0 &&
          seriesData.length > 0
        ) {
          const lastIntegrated =
            Number(seriesData[seriesData.length - 1][1]) || 0;
          // Never shift the curve negative at t0 when integrated > ledger reference.
          const offset = Math.max(0, refKwh - lastIntegrated);
          for (let i = 0; i < seriesData.length; i++) {
            seriesData[i][1] = (Number(seriesData[i][1]) || 0) + offset;
          }
        }
        const peakKwh = seriesData.reduce((m, p) => Math.max(m, Number(p[1]) || 0), 0);
        intradayKwhYMax = peakKwh <= 0 ? 1 : Math.max(peakKwh * 1.2, 0.005);
        const decimals = intradayKwhYMax <= 0.02 ? 3 : intradayKwhYMax <= 0.5 ? 2 : 2;
        yFormatter = (v) => (v == null ? '—' : `${Number(v).toFixed(decimals)} kWh`);
      } else {
        seriesName = 'W';
        seriesData = [];
        for (let i = 0; i < n; i++) {
          const x = this._parseChartTimeMs(timestamps[i]);
          if (Number.isNaN(x) || x < dayStart || x > dayEnd) continue;
          seriesData.push([x, Number(watts[i]) || 0]);
        }
        seriesData.sort((a, b) => a[0] - b[0]);
        yFormatter = (v) => (v == null ? '—' : `${Math.round(Number(v))} W`);
      }
    } else if (type === 'stat_total_wh' || type === 'stat_room_wh') {
      const dates = this._graphData.dates || [];
      let raw;
      if (type === 'stat_total_wh') {
        raw = this._graphData.total_wh || [];
        seriesName = 'kWh per day (home)';
      } else {
        raw = this._graphData.rooms?.[roomId]?.wh || [];
        seriesName = `${roomName || 'Room'} kWh per day`;
      }
      const values = raw.map((v) => v / 1000);
      const pairs = [];
      const m = Math.min(dates.length, values.length);
      for (let i = 0; i < m; i++) {
        const x = this._parseChartTimeMs(dates[i]);
        if (!Number.isNaN(x)) pairs.push({ x, v: values[i] });
      }
      pairs.sort((a, b) => a.x - b.x);
      billingValues = pairs.map((p) => p.v);
      billingCategories = pairs.map((p) =>
        new Date(p.x).toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        }),
      );
      seriesData = pairs.map((p) => [p.x, p.v]);
      strokeCurve = 'straight';
      yFormatter = (v) => `${Number(v).toFixed(2)} kWh`;
    } else if (type.startsWith('room_')) {
      const key = type.replace('room_', '');
      const raw = this._graphData.rooms?.[roomId]?.[key] || [];
      const dates = this._graphData.dates || [];
      seriesName = key === 'wh' ? 'kWh' : key;
      const values = raw.map((v) => (key === 'wh' ? v / 1000 : v));
      seriesData = [];
      const m = Math.min(dates.length, values.length);
      for (let i = 0; i < m; i++) {
        const x = this._parseChartTimeMs(dates[i]);
        if (!Number.isNaN(x)) seriesData.push([x, values[i]]);
      }
      strokeCurve = 'straight';
      if (key === 'wh') yFormatter = (v) => `${Number(v).toFixed(2)} kWh`;
    } else {
      const tail = type.replace(/^total_/, '');
      const dailyKey = tail === 'wh' ? 'total_wh' : `total_${tail}`;
      const rawArr = this._graphData[dailyKey] || [];
      const dates = this._graphData.dates || [];
      const values = rawArr.map((v) => (dailyKey === 'total_wh' ? v / 1000 : v));
      seriesName = dailyKey === 'total_wh' ? 'kWh' : dailyKey.replace('total_', '');
      seriesData = [];
      const m = Math.min(dates.length, values.length);
      for (let i = 0; i < m; i++) {
        const x = this._parseChartTimeMs(dates[i]);
        if (!Number.isNaN(x)) seriesData.push([x, values[i]]);
      }
      strokeCurve = 'straight';
      if (dailyKey === 'total_wh') yFormatter = (v) => `${Number(v).toFixed(2)} kWh`;
    }

    if (this._apexChartInstance) {
      this._apexChartInstance.destroy();
      this._apexChartInstance = null;
    }
    this._teardownBillingBarChartNative();

    const accent = getComputedStyle(this).getPropertyValue('--panel-accent').trim() || '#03a9f4';
    const textColor = getComputedStyle(this).getPropertyValue('--primary-text-color').trim() || '#e1e1e1';

    if (useRoomHourlyBars) {
      container.innerHTML = '';
      if (
        !roomHourlyValues ||
        !roomHourlyCategories ||
        roomHourlyCategories.length !== roomHourlyValues.length
      ) {
        container.innerHTML =
          '<p style="color:var(--secondary-text-color);padding:20px;text-align:center;">No data yet</p>';
        return;
      }
      this._renderBillingBarChartNative(container, {
        categories: roomHourlyCategories,
        values: roomHourlyValues,
        seriesName,
        yFormatter,
        accent,
        textColor,
        ariaCountNoun: 'hours',
        xLabelsMode: 'hourly',
      });
      return;
    }

    const useBillingBars =
      isStatBillingModal &&
      Array.isArray(billingValues) &&
      billingValues.length > 0 &&
      Array.isArray(billingCategories) &&
      billingCategories.length === billingValues.length;

    if (isStatBillingModal) {
      container.innerHTML = '';
      if (!useBillingBars) {
        container.innerHTML =
          '<p style="color:var(--secondary-text-color);padding:20px;text-align:center;">No data yet</p>';
        return;
      }
      this._renderBillingBarChartNative(container, {
        categories: billingCategories,
        values: billingValues,
        seriesName,
        yFormatter,
        accent,
        textColor,
      });
      return;
    }

    try {
      const ApexCharts = (await import('https://cdn.jsdelivr.net/npm/apexcharts@3.45.1/dist/apexcharts.esm.min.js')).default;
      const gridColor = getComputedStyle(this).getPropertyValue('--card-border').trim() || 'rgba(255,255,255,0.08)';

      const options = {
        chart: {
          type: 'area',
          height: 300,
          fontFamily: 'inherit',
          background: 'transparent',
          toolbar: { show: false },
          zoom: { enabled: false },
          parentHeightOffset: 0,
          redrawOnParentResize: true,
          animations: { enabled: true },
        },
        series: [{ name: seriesName, data: seriesData }],
        xaxis: {
          type: 'datetime',
          labels: {
            style: { colors: textColor, fontSize: '11px' },
            datetimeUTC: false,
          },
          axisBorder: { show: true, color: gridColor },
          axisTicks: { show: true, color: gridColor },
        },
        yaxis: {
          labels: {
            show: true,
            style: { colors: textColor, fontSize: '11px' },
            formatter: (val) => yFormatter(val),
            maxWidth: 64,
          },
          axisBorder: { show: false },
          ...(intradayKwhYMax != null
            ? {
                min: 0,
                max: intradayKwhYMax,
                tickAmount: 5,
                decimalsInFloat: intradayKwhYMax <= 0.02 ? 3 : 2,
              }
            : {}),
        },
        colors: [accent],
        fill: {
          type: 'gradient',
          gradient: { shadeIntensity: 0.25, opacityFrom: 0.45, opacityTo: 0.04 },
        },
        stroke: { curve: strokeCurve, width: 2 },
        grid: {
          borderColor: gridColor,
          strokeDashArray: 4,
          padding: { right: 8, bottom: 4, left: 4 },
          xaxis: { lines: { show: false } },
          yaxis: { lines: { show: true } },
        },
        dataLabels: { enabled: false },
        tooltip: {
          theme: 'dark',
          x: {
            formatter: (val) => {
              const d = new Date(val);
              return isIntraday
                ? d.toLocaleString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : d.toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  });
            },
          },
          y: { formatter: (val) => yFormatter(val) },
        },
        plotOptions: { area: { fillTo: 'origin' } },
        markers: {
          size: seriesData.length <= 8 ? 3 : 0,
          hover: { size: 5 },
        },
      };
      if (!seriesData.length) {
        options.noData = { text: 'No data yet', style: { color: textColor } };
      }
      if (isIntraday) {
        options.xaxis.min = this._startOfLocalDayMs();
        options.xaxis.max = Date.now();
      }
      this._apexChartInstance = new ApexCharts(container, options);
      await this._apexChartInstance.render();
      requestAnimationFrame(() => {
        try {
          this._apexChartInstance?.resize();
        } catch (_e) {
          /* stale instance */
        }
        requestAnimationFrame(() => {
          try {
            this._apexChartInstance?.resize();
          } catch (_e2) {
            /* stale instance */
          }
        });
      });
    } catch (e) {
      console.error('ApexCharts failed to load:', e);
      container.innerHTML = '<p style="color:var(--secondary-text-color);padding:20px;text-align:center;">Chart failed to load. Check network or try again.</p>';
    }
  }

  /** After any full _render(), modal DOM is recreated; re-bind close + chart if a graph is open. */
  _syncGraphModalAfterRender() {
    if (!this._graphOpen) return;
    this._attachGraphModalListeners();
    if (this._graphLoading || this._graphLoadError || !this._graphData) return;
    if (!this._isEventLogType(this._graphOpen.type)) {
      queueMicrotask(() => void this._initApexChart());
    }
  }

  _attachGraphModalListeners() {
    if (this._graphModalEscapeHandler) {
      window.removeEventListener('keydown', this._graphModalEscapeHandler);
      this._graphModalEscapeHandler = null;
    }
    const overlay = this.shadowRoot.getElementById('graph-modal-overlay');
    const closeBtn = this.shadowRoot.getElementById('graph-modal-close');
    const close = () => {
      if (this._graphModalEscapeHandler) {
        window.removeEventListener('keydown', this._graphModalEscapeHandler);
        this._graphModalEscapeHandler = null;
      }
      if (this._apexChartInstance) {
        this._apexChartInstance.destroy();
        this._apexChartInstance = null;
      }
      this._teardownBillingBarChartNative();
      this._graphOpen = null;
      this._graphData = null;
      this._graphLoading = false;
      this._graphLoadError = null;
      this._render();
    };
    this._graphModalEscapeHandler = (e) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', this._graphModalEscapeHandler);
    if (overlay) overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    if (closeBtn) closeBtn.addEventListener('click', close);
  }

  _formatDateRange(dateStr) {
    if (!dateStr || typeof dateStr !== 'string') return '—';
    const parts = dateStr.trim().split('-');
    if (parts.length !== 3) return dateStr;
    const y = parts[0], m = parts[1], d = parts[2];
    if (!/^\d{4}$/.test(y) || !/^\d{1,2}$/.test(m) || !/^\d{1,2}$/.test(d)) return dateStr;
    return `${m.padStart(2, '0')}/${d.padStart(2, '0')}/${y}`;
  }

  /** Parse HA date or "YYYY-MM-DD HH:mm" to epoch ms (local wall time). */
  _parseChartTimeMs(ts) {
    if (ts == null || ts === '') return NaN;
    if (typeof ts === 'number' && !Number.isNaN(ts)) return ts;
    const s = String(ts).trim();
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T\s]+(\d{1,2}):(\d{2}))?/);
    if (!m) return Date.parse(s);
    const y = +m[1];
    const mo = +m[2] - 1;
    const d = +m[3];
    if (m[4] === undefined) return new Date(y, mo, d, 12, 0, 0, 0).getTime();
    return new Date(y, mo, d, +m[4], +m[5], 0, 0).getTime();
  }

  /** Cumulative kWh from W samples and uneven minute timestamps (trapezoid between points). */
  _cumulativeKwhFromPowerSamples(timestamps, watts) {
    const n = Math.min(timestamps.length, watts.length);
    if (n === 0) return [];
    const cum = new Array(n).fill(0);
    let totalKwh = 0;
    for (let i = 1; i < n; i++) {
      const t0 = this._parseChartTimeMs(timestamps[i - 1]);
      const t1 = this._parseChartTimeMs(timestamps[i]);
      if (!(t1 > t0)) continue;
      const dtH = (t1 - t0) / 3600000;
      const w0 = Number(watts[i - 1]) || 0;
      const w1 = Number(watts[i]) || 0;
      totalKwh += ((w0 + w1) / 2) * dtH / 1000;
      cum[i] = totalKwh;
    }
    return cum;
  }

  _renderStatisticsView() {
    const s = this._statsData || {};
    const dateStart = s.date_start || '';
    const dateEnd = s.date_end || '';
    const isNarrowed = s.is_narrowed === true;
    const startFormatted = this._formatDateRange(dateStart);
    const endFormatted = this._formatDateRange(dateEnd);
    const rangeBanner = dateStart && dateEnd
      ? `${startFormatted} – ${endFormatted}`
      : 'No date range available';
    const sensorValues = s.sensor_values || {};
    const currentUsage = sensorValues.current_usage;
    const projectedUsage = sensorValues.projected_usage;
    const kwhCost = sensorValues.kwh_cost;
    const totalKwh = s.total_kwh ?? 0;
    const totalWarnings = s.total_warnings ?? 0;
    const totalShutoffs = s.total_shutoffs ?? 0;
    const totalPowerCycles = s.total_power_cycles ?? 0;
    const rooms = s.rooms || [];
    const roomsPieView = this._statsRoomsView === 'pie';
    const sensorMeta = s.sensor_meta || {};
    const sensorStates = sensorMeta.sensor_states || {};
    const showSupplier = this._statisticsSupplierConfigured();
    const supplierUpdLine = sensorMeta.supplier_last_updated
      ? `Bill cycle usage last changed · ${this._formatSupplierLastUpdated(sensorMeta.supplier_last_updated)}`
      : 'Configure supplier sensors in Settings to show live utility reads.';

    const fmt = (v) => (v == null ? '—' : (typeof v === 'number' ? v.toFixed(2) : String(v)));
    const sensorDiagnostic = (key, parsedVal) => {
      if (parsedVal != null) return '';
      const info = sensorStates[key];
      if (!info) return '';
      if (!info.entity) return '<span class="sensor-diagnostic">(not configured)</span>';
      if (info.raw === 'entity_not_found') return '<span class="sensor-diagnostic">(entity not found)</span>';
      if (info.raw === 'unknown' || info.raw === 'unavailable') return `<span class="sensor-diagnostic">(${info.raw})</span>`;
      if (info.raw) return `<span class="sensor-diagnostic">(raw: ${String(info.raw).replace(/</g, '&lt;').substring(0, 20)})</span>`;
      return '<span class="sensor-diagnostic">(empty)</span>';
    };
    const showOverlay = this._statsLoading;
    const staleLine = s.statistics_pending
      ? 'Full usage totals are building in the background — this page updates automatically when the snapshot is ready.'
      : this._statsFetchedAt
        ? `Showing last known values · updated ${this._statsDataAgeLabel()} · refreshing in background`
        : 'Loading statistics…';

    return `
      <div class="statistics-view-shell">
        <div class="statistics-loading-overlay" id="statistics-loading-overlay" style="display:${showOverlay ? 'flex' : 'none'}">
          <div class="statistics-loading-inner">
            <div class="statistics-loading-spinner"></div>
            <p class="statistics-loading-title">Updating statistics…</p>
            <p class="statistics-loading-sub" id="statistics-loading-sub">${staleLine}</p>
            ${this._statsFetchError ? `<p class="statistics-loading-err">${String(this._statsFetchError).replace(/</g, '&lt;')}</p>` : ''}
          </div>
        </div>
        <div class="statistics-view">
        <div class="statistics-banner">
          <div class="statistics-banner-row">
            <span class="statistics-banner-label" id="stat-period-label">${s.period_source === 'billing' ? 'Current billing cycle (tracked totals)' : 'Tracked totals window'}</span>
            <span class="statistics-range" id="stat-range-banner">${rangeBanner}</span>
            <span class="statistics-narrowed" id="stat-narrowed" style="${isNarrowed ? '' : 'display:none'}">Narrowed to dates you picked.</span>
          </div>
          ${s.statistics_pending ? `<div class="statistics-pending-banner" id="stat-pending-banner">Full usage totals are building in the background — numbers update automatically when the snapshot is ready.</div>` : ''}
        </div>
        <div class="statistics-cards">
          <div class="statistics-overview-card card">
            <div class="statistics-overview-grid${showSupplier ? '' : ' statistics-overview-grid--tracked-only'}">
              ${showSupplier ? `
              <div class="statistics-overview-col--supplier">
                <p class="statistics-card-sub">Supplier</p>
                <h3 class="statistics-card-title">Utility read</h3>
                <div class="statistics-kpi-big">
                  <span class="lbl">So far <span style="font-weight:500;opacity:0.85">(bill cycle)</span></span>
                  <span class="val"><span id="stat-current-usage">${fmt(currentUsage)}</span> <span style="font-size:0.55em;font-weight:600;opacity:0.85">kWh</span> ${sensorDiagnostic('current_usage', currentUsage)}</span>
                </div>
                <div class="statistics-totals-grid">
                  <div class="statistics-total-item">
                    <span class="statistics-total-label">Estimate end <span style="font-weight:500;opacity:0.8;font-size:10px">(cycle)</span></span>
                    <span class="statistics-total-value" id="stat-projected-usage">${fmt(projectedUsage)} kWh ${sensorDiagnostic('projected_usage', projectedUsage)}</span>
                  </div>
                  <div class="statistics-total-item">
                    <span class="statistics-total-label">$/kWh</span>
                    <span class="statistics-total-value" id="stat-kwh-cost">$${fmt(kwhCost)} ${sensorDiagnostic('kwh_cost', kwhCost)}</span>
                  </div>
                </div>
                <p class="statistics-supplier-updated" id="stat-supplier-updated">${supplierUpdLine.replace(/</g, '&lt;')}</p>
              </div>` : ''}
              <div class="statistics-overview-col--tracked">
                <p class="statistics-card-sub">What we measure</p>
                <h3 class="statistics-card-title">Tracked usage</h3>
                <div class="statistics-kpi-big">
                  <span class="lbl">Tracked total for dates above</span>
                  <span class="val"><span id="stat-total-kwh">${totalKwh.toFixed(2)}</span> <span style="font-size:0.55em;font-weight:600;opacity:0.85">kWh</span></span>
                </div>
                <div class="statistics-totals-grid">
                  <div class="statistics-total-item${dateStart && dateEnd ? ' graph-clickable' : ''}" ${dateStart && dateEnd ? 'data-graph-type="stat_total_warnings" title="Open threshold warning log for dates above"' : ''}>
                    <span class="statistics-total-label">Voice warnings</span>
                    <span class="statistics-total-value" id="stat-total-warnings">${totalWarnings}</span>
                  </div>
                  <div class="statistics-total-item${dateStart && dateEnd ? ' graph-clickable' : ''}" ${dateStart && dateEnd ? 'data-graph-type="stat_total_shutoffs" title="Open safety shutoff log for dates above"' : ''}>
                    <span class="statistics-total-label">Plug shutoffs</span>
                    <span class="statistics-total-value" id="stat-total-shutoffs">${totalShutoffs}</span>
                  </div>
                  <div class="statistics-total-item${dateStart && dateEnd ? ' graph-clickable' : ''}" ${dateStart && dateEnd ? 'data-graph-type="stat_total_power_cycles" title="Open enforcement cycle log for dates above"' : ''}>
                    <span class="statistics-total-label">Enforcement cycles</span>
                    <span class="statistics-total-value" id="stat-total-power-cycles">${totalPowerCycles}</span>
                  </div>
                </div>
                <div class="statistics-chart-actions">
                  ${dateStart && dateEnd ? `<button type="button" class="btn-stat-chart" id="stat-chart-billing-home" title="Daily kWh per day for the date range at the top">Open usage graph (whole home)</button>` : ''}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="statistics-rooms-card card statistics-rooms-fullbleed">
          <p class="statistics-card-sub">Rooms</p>
          <h3 class="statistics-card-title">kWh and events</h3>
          <div class="stat-rooms-segment-wrap" role="tablist" aria-label="Rooms data view">
            <button type="button" role="tab" class="stat-rooms-segment ${roomsPieView ? 'active' : ''}" id="stat-rooms-tab-chart" data-stat-rooms-view="pie" aria-selected="${roomsPieView}" aria-controls="stat-rooms-panel-pie">Chart</button>
            <button type="button" role="tab" class="stat-rooms-segment ${!roomsPieView ? 'active' : ''}" id="stat-rooms-tab-table" data-stat-rooms-view="table" aria-selected="${!roomsPieView}" aria-controls="stat-rooms-panel-table">Table</button>
          </div>
          <div id="stat-rooms-panel-table" class="stat-rooms-panel" role="tabpanel" aria-labelledby="stat-rooms-tab-table" style="display:${roomsPieView ? 'none' : 'block'}">
            <div class="statistics-table-wrap">
              <table class="statistics-table" aria-describedby="stat-table-desc">
                <caption id="stat-table-desc" style="caption-side:bottom;text-align:left;padding-top:8px;font-size:11px;color:var(--secondary-text-color);">Usage and Percent apply to the same dates shown at the top of this page. High, low, and average are daily kWh (local days in range). Total cost is period Usage (kWh) × $/kWh from supplier when configured. Warnings, shutoffs, and cycles sum daily snapshots. Tap a count (when a date range is set) for the event log. Open a room graph from the pie chart.</caption>
                <thead>
                  <tr>
                    <th scope="col">Room</th>
                    <th scope="col"><abbr title="Efficiency (billing period)">Efficiency</abbr></th>
                    <th scope="col"><abbr title="kWh this period">Usage</abbr></th>
                    <th scope="col"><abbr title="Percent of tracked kWh this period">Percent</abbr></th>
                    <th scope="col"><abbr title="Voice threshold warnings">Warnings</abbr></th>
                    <th scope="col"><abbr title="Safety plug shutoffs">Shutoffs</abbr></th>
                    <th scope="col"><abbr title="Enforcement outlet cycles">Cycles</abbr></th>
                    <th scope="col"><abbr title="Highest kWh in a single local day">High</abbr></th>
                    <th scope="col"><abbr title="Lowest kWh in a single local day">Low</abbr></th>
                    <th scope="col"><abbr title="Average kWh per day (usage ÷ days in range)">Average</abbr></th>
                    <th scope="col"><abbr title="Period Usage (kWh) × $/kWh">Total cost</abbr></th>
                  </tr>
                </thead>
                <tbody id="stat-rooms-tbody">
                  ${rooms.length === 0 ? '<tr><td colspan="11" class="statistics-empty">No room data for this range.</td></tr>' : ''}
                  ${rooms.map((r) => {
                  const rname = (r.name || r.id || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
                  const rid = String(r.id || '').replace(/"/g, '&quot;');
                  const effRatings = r.ratings;
                  const effStars =
                    effRatings != null &&
                    effRatings.stars != null &&
                    Number.isFinite(Number(effRatings.stars))
                      ? Number(effRatings.stars)
                      : 0;
                  const effPrefix = `stat_${String(r.id || 'room').replace(/[^a-zA-Z0-9_-]/g, '_')}`;
                  const effStarsHtml = this._formatEfficiencyStarsSvg(effStars, effPrefix);
                  const effCell = `<button type="button" class="stat-room-efficiency-rating has-tooltip" data-stat-room-rating="${rid}"
                    title="Efficiency (billing period) — tap for details" aria-label="Room efficiency for this period, tap for details">
                    <span class="room-efficiency-stars stat-room-efficiency-stars">${effStarsHtml}</span>
                  </button>`;
                  const warnCell = dateStart && dateEnd
                    ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_warnings" data-room-id="${rid}" data-room-name="${rname}" title="Room warning log (billing period)">${r.warnings ?? 0}</span>`
                    : `${r.warnings ?? 0}`;
                  const shutCell = dateStart && dateEnd
                    ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_shutoffs" data-room-id="${rid}" data-room-name="${rname}" title="Room shutoff log (billing period)">${r.shutoffs ?? 0}</span>`
                    : `${r.shutoffs ?? 0}`;
                  const cycCell = dateStart && dateEnd
                    ? `<span class="graph-clickable stat-room-events" role="button" tabindex="0" data-graph-type="stat_room_power_cycles" data-room-id="${rid}" data-room-name="${rname}" title="Room cycle log (billing period)">${r.power_cycles ?? 0}</span>`
                    : `${r.power_cycles ?? 0}`;
                  const kc = kwhCost;
                  const costOk = kc != null && Number.isFinite(Number(kc));
                  const fmtTotalCost = (periodKwh) => {
                    if (!costOk) return '—';
                    const n = Number(periodKwh) * Number(kc);
                    if (!Number.isFinite(n)) return '—';
                    return `$${n.toFixed(2)}`;
                  };
                  const hi = (r.daily_high_kwh != null ? Number(r.daily_high_kwh) : 0).toFixed(2);
                  const lo = (r.daily_low_kwh != null ? Number(r.daily_low_kwh) : 0).toFixed(2);
                  const avg = (r.daily_avg_kwh != null ? Number(r.daily_avg_kwh) : 0).toFixed(2);
                  const totalCost = fmtTotalCost(r.kwh);
                  return `
                  <tr>
                    <td>${(r.name || r.id || '').replace(/</g, '&lt;')}</td>
                    <td class="stat-efficiency-cell">${effCell}</td>
                    <td>${(r.kwh ?? 0).toFixed(2)} kWh</td>
                    <td>${(r.pct ?? 0).toFixed(1)}%</td>
                    <td>${warnCell}</td>
                    <td>${shutCell}</td>
                    <td>${cycCell}</td>
                    <td>${hi}</td>
                    <td>${lo}</td>
                    <td>${avg}</td>
                    <td>${totalCost}</td>
                  </tr>`;
                }).join('')}
                </tbody>
              </table>
            </div>
          </div>
          <div id="stat-rooms-panel-pie" class="stat-rooms-panel" role="tabpanel" aria-labelledby="stat-rooms-tab-chart" style="display:${roomsPieView ? 'block' : 'none'}">
            <div id="stat-rooms-pie-chart" class="stat-rooms-pie-mount" aria-hidden="${roomsPieView ? 'false' : 'true'}"></div>
            <div id="stat-pie-selection" class="stat-pie-selection" role="region" aria-live="polite">
              <p class="stat-pie-selection-meta">Tap a slice for room details and to open a usage graph. Rooms with 0 kWh this period appear in the table only.</p>
            </div>
            <p id="stat-pie-desc" class="stat-pie-caption">Pie shares use the same tracked kWh total and dates as the banner above (non-zero rooms only). Use the table for every room, daily high/low/average, and zero-load rows; tap a slice here to open that room usage graph.</p>
          </div>
        </div>
        </div>
      </div>
    `;
  }

  /** Match Python datetime.weekday(): Monday=0 … Sunday=6. */
  _weekdayPythonFromDate(d) {
    const js = d.getDay();
    return (js + 6) % 7;
  }

  _isBudgetBoostDayClient(tts) {
    const t = tts || {};
    if (!t.budget_boost_enabled) return false;
    const mult = parseFloat(t.budget_boost_multiplier) || 1;
    if (mult <= 1) return false;
    const days = t.budget_boost_weekdays;
    if (!Array.isArray(days) || days.length === 0) return false;
    const wk = this._weekdayPythonFromDate(new Date());
    return days.some((d) => parseInt(String(d), 10) === wk);
  }

  /** Mirror config_manager.effective_kwh_budget_for_moment (local date). */
  _effectiveKwhBudgetClient(baseKwh, tts, useRoomBoost = true) {
    const base = Math.max(0, Number(baseKwh) || 0);
    if (base <= 0) return base;
    if (useRoomBoost === false) return base;
    if (!this._isBudgetBoostDayClient(tts)) return base;
    const mult = Math.max(1, Math.min(5, parseFloat((tts || {}).budget_boost_multiplier) || 2));
    return Math.round(base * mult * 10000) / 10000;
  }

  _resolvePowerRoomRow(roomId) {
    const rooms = this._powerData?.rooms;
    if (!Array.isArray(rooms) || roomId == null || roomId === '') return null;
    let row = rooms.find((r) => r.id === roomId);
    if (row) return row;
    const norm = (s) => String(s || '').toLowerCase().replace(/\s+/g, '_');
    const nid = norm(roomId);
    row = rooms.find((r) => norm(r.id) === nid);
    return row || null;
  }

  /** Exactly four strictly increasing positive thresholds; else default [5,10,15,20]. */
  _parseRoomKwhIntervals(raw) {
    const DEFAULT = [5, 10, 15, 20];
    const toNums = (arr) =>
      arr.map((x) => Number(x)).filter((n) => Number.isFinite(n) && n > 0);
    let nums;
    if (Array.isArray(raw)) {
      nums = toNums(raw);
    } else if (typeof raw === 'string') {
      nums = toNums(raw.split(',').map((s) => s.trim()).filter(Boolean));
    } else {
      return { intervals: [...DEFAULT], valid: false };
    }
    if (nums.length !== 4) return { intervals: [...DEFAULT], valid: false };
    const sorted = [...nums].sort((a, b) => a - b);
    const uniq = [...new Set(sorted)];
    if (uniq.length !== 4) return { intervals: [...DEFAULT], valid: false };
    for (let i = 1; i < 4; i++) {
      if (uniq[i] <= uniq[i - 1]) return { intervals: [...DEFAULT], valid: false };
    }
    return { intervals: uniq, valid: true };
  }

  _kwhTierFromUsed(usedKwh, t) {
    const [t0, t1, t2] = t;
    if (usedKwh < t0) return 0;
    if (usedKwh < t1) return 1;
    if (usedKwh < t2) return 2;
    return 3;
  }

  /** Three increasing cutpoints for tier colors: global [t0,t1,t2] or merged with eff when room has a budget. */
  _kwhTierCutpointsMerged(baseKwh, effKwh, intervalsSorted) {
    const [t0, t1, t2] = intervalsSorted;
    if (!(baseKwh > 0)) return [t0, t1, t2];
    const merged = [...new Set([effKwh, t1, t2])].sort((a, b) => a - b);
    const eps = 1e-9;
    const has = (arr, x) => arr.some((v) => Math.abs(v - x) < eps);
    while (merged.length < 3) {
      let added = false;
      for (const g of [t0, t1, t2]) {
        if (!has(merged, g)) {
          merged.push(g);
          merged.sort((a, b) => a - b);
          added = true;
          break;
        }
      }
      if (!added) break;
    }
    return merged.slice(0, 3).sort((a, b) => a - b);
  }

  _budgetBarSubtitle(b) {
    if (!b.showBar) return 'Configure kWh intervals';
    if (b.over) return 'Over range';
    if (b.overBudget) {
      const aud = b.audibleKwh;
      if (aud != null && b.usedKwh + 1e-6 < aud) {
        return `Past ${b.effKwh.toFixed(1)} kWh budget`;
      }
      return 'Over budget';
    }
    if (b.boost) return 'Boost active';
    return '';
  }

  /** Daily kWh bar: scale = 4th threshold; fill vs scale; budget marker at effective kWh budget. */
  _roomBudgetUiState(roomData, roomConfig) {
    const pe = this._config?.power_enforcement || {};
    const rawIntervals = pe.room_kwh_intervals;
    const { intervals: intervalsSorted } = this._parseRoomKwhIntervals(
      Array.isArray(rawIntervals) && rawIntervals.length
        ? rawIntervals
        : [5, 10, 15, 20],
    );
    const maxInterval = intervalsSorted[3];

    const cfgBase = Number(roomConfig?.kwh_budget);
    const dataBase = Number(roomData.kwh_budget);
    const baseRaw = Number.isFinite(cfgBase)
      ? cfgBase
      : Number.isFinite(dataBase)
        ? dataBase
        : Number(roomConfig?.kwh_budget ?? 5);
    const baseKwh = Number.isFinite(baseRaw) ? Math.max(0, baseRaw) : 0;
    const tts = this._config?.tts_settings || {};
    const roomUsesBoost = roomConfig?.kwh_budget_use_boost !== false;
    let effKwh = baseKwh;
    const apiEff = roomData.kwh_budget_effective;
    if (apiEff != null && Number.isFinite(Number(apiEff))) {
      effKwh = Math.max(0, Number(apiEff));
    } else {
      effKwh = this._effectiveKwhBudgetClient(baseKwh, tts, roomUsesBoost);
    }
    const usedKwh = Math.max(0, (roomData.total_day_wh || 0) / 1000);
    const showBar = maxInterval > 0;
    const fillPct = showBar ? Math.min(100, (usedKwh / maxInterval) * 100) : 0;
    const overScale = showBar && usedKwh > maxInterval;
    const overBudget = showBar && effKwh > 0 && usedKwh > effKwh;
    const boost = baseKwh > 0 && effKwh > baseKwh + 0.0001;
    const budgetMarkerPct =
      showBar && effKwh > 0
        ? Math.min(100, (effKwh / maxInterval) * 100)
        : null;
    const upperIntervals = intervalsSorted.slice(1);
    let plottedIntervals;
    if (baseKwh > 0) {
      plottedIntervals = boost
        ? upperIntervals.filter((v) => v >= effKwh - 1e-9)
        : upperIntervals.filter((v) => v >= baseKwh - 1e-9);
    } else {
      plottedIntervals = boost
        ? intervalsSorted.filter((v) => v >= effKwh - 1e-9)
        : [...intervalsSorted];
    }
    const audibleKwh = plottedIntervals.length ? plottedIntervals[0] : null;
    const audiblePct =
      audibleKwh != null && showBar
        ? Math.min(100, (audibleKwh / maxInterval) * 100)
        : null;
    const budgetCoincidesAudible =
      budgetMarkerPct != null &&
      audiblePct != null &&
      Math.abs(budgetMarkerPct - audiblePct) < 0.9;
    const showSeparateBudget = Boolean(
      budgetMarkerPct != null && showBar && effKwh > 0,
    );
    const plottedIntervalMarkers = plottedIntervals.map((value) => ({
      value,
      pct: showBar ? Math.min(100, (value / maxInterval) * 100) : 0,
      kind:
        audibleKwh != null && Math.abs(value - audibleKwh) < 1e-6
          ? 'audible'
          : 'interval',
    }));
    const tierCutpoints = this._kwhTierCutpointsMerged(
      baseKwh,
      effKwh,
      intervalsSorted,
    );
    const kwhTier = showBar ? this._kwhTierFromUsed(usedKwh, tierCutpoints) : 0;
    return {
      usedKwh,
      effKwh,
      baseKwh,
      maxInterval,
      intervalsSorted,
      plottedIntervals,
      audibleKwh,
      plottedIntervalMarkers,
      budgetMarkerPct,
      budgetCoincidesAudible,
      showSeparateBudget,
      showBar,
      fillPct,
      over: overScale,
      overBudget,
      boost,
      kwhTier,
    };
  }

  _roomBudgetMarkersHtml(budget) {
    if (!budget.showBar) return '';
    const esc = (s) => String(s).replace(/"/g, '&quot;');
    const chunks = [];

    // Budget marker (prominent blue style) - render first so it's behind tier markers if overlapping
    if (budget.showSeparateBudget && budget.budgetMarkerPct != null) {
      const budgetTip = esc(
        `Daily budget ${budget.effKwh.toFixed(2)} kWh` +
          (budget.boost ? ` (boosted from ${budget.baseKwh} kWh)` : ''),
      );
      chunks.push(`<div class="room-budget-marker-wrap" data-marker-role="budget" style="left:${budget.budgetMarkerPct}%">
          <span class="room-budget-marker-tick room-budget-marker--audible has-tooltip" title="${budgetTip}"></span>
          <span class="room-budget-marker-label room-budget-marker-label--audible">${budget.effKwh.toFixed(1)} kWh</span>
        </div>`);
    }

    // Voice tier markers (secondary style) - skip if coincides with budget marker
    for (const m of budget.plottedIntervalMarkers) {
      const coincidesWithBudget =
        budget.showSeparateBudget &&
        budget.budgetMarkerPct != null &&
        Math.abs(m.pct - budget.budgetMarkerPct) < 0.9;
      if (coincidesWithBudget) continue;
      const tip = esc(`Voice alerts at ${m.value} kWh`);
      chunks.push(`<div class="room-budget-marker-wrap" data-kwh="${m.value}" style="left:${m.pct}%">
          <span class="room-budget-marker-tick room-budget-marker--interval has-tooltip" title="${tip}"></span>
          <span class="room-budget-marker-label room-budget-marker-label--kwh">${m.value} kWh</span>
        </div>`);
    }

    return `<div class="room-budget-markers" aria-hidden="true">${chunks.join('')}</div>`;
  }

  _enforcementBadgeHtml(roomId, phase, inline = false) {
    const pe = this._config?.power_enforcement || {};
    const roomsEnabled = pe.rooms_enabled || [];
    const enabled = pe.enabled && roomsEnabled.includes(roomId);
    if (!enabled || !icons?.shield) return '';
    const p = Math.max(0, Math.min(2, Number(phase) || 0));
    const esc = (s) => String(s).replace(/"/g, '&quot;');
    const inlineCls = inline ? ' enforcement-badge--inline' : '';
    const svgDim = inline
      ? 'clamp(8px, 2vw, 10px)'
      : 'clamp(10px, 2.5vw, 12px)';
    return `
              <span class="enforcement-badge enforcement-phase-${p}${inlineCls} has-tooltip" title="${esc(ENFORCEMENT_PHASE_TITLES[p])}">
                <svg viewBox="0 0 24 24" style="width: ${svgDim}; height: ${svgDim}; flex-shrink: 0; fill: #fff;">${icons.shield}</svg>
                <span class="enforcement-badge-label">${ENFORCEMENT_BADGE_LABELS[p]}</span>
              </span>`;
  }

  _renderEmptyState() {
    return `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24">${icons.flash}</svg>
        <h3 class="empty-state-title">No Rooms Configured</h3>
        <p class="empty-state-desc">Set up rooms and outlets to monitor power usage with automatic alerts.</p>
        <button class="btn btn-primary" id="empty-settings-btn">
          <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
          Open Settings
        </button>
      </div>
    `;
  }

  /** Material-style star path (24x24). */
  _efficiencyStarPath() {
    return 'M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z';
  }

  _formatEfficiencyStarsSvg(stars, idPrefix) {
    let s = 0;
    if (stars !== null && stars !== undefined && Number.isFinite(Number(stars))) {
      s = Math.max(0, Math.min(5, Number(stars)));
    }
    const path = this._efficiencyStarPath();
    const gold = '#ffb300';
    const dim = 'rgba(255,255,255,0.22)';
    let html = '';
    for (let i = 0; i < 5; i++) {
      const gid = `effg_${idPrefix}_${i}`;
      if (s >= i + 1) {
        html += `<svg class="room-efficiency-star" viewBox="0 0 24 24" aria-hidden="true"><path fill="${gold}" d="${path}"/></svg>`;
      } else if (s >= i + 0.5) {
        html += `<svg class="room-efficiency-star" viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="${gid}"><stop offset="50%" stop-color="${gold}"/><stop offset="50%" stop-color="${dim}"/></linearGradient></defs><path fill="url(#${gid})" stroke="${dim}" stroke-width="0.6" d="${path}"/></svg>`;
      } else {
        html += `<svg class="room-efficiency-star" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="${dim}" stroke-width="1.2" d="${path}"/></svg>`;
      }
    }
    return html;
  }

  _roomEfficiencyRatingRowHtml(roomId, idPrefix) {
    const esc = (x) => String(x || '').replace(/"/g, '&quot;');
    const loadingLike = this._loading || !this._powerData;
    if (loadingLike) {
      return `
      <button type="button" class="room-header-rating room-header-rating--loading has-tooltip" data-room-rating="${esc(roomId)}"
        title="Loading efficiency rating…" aria-label="Efficiency rating loading" disabled>
        <span class="room-efficiency-placeholder" aria-hidden="true">…</span>
      </button>`;
    }
    const row = this._resolvePowerRoomRow(roomId);
    const r = row?.ratings;
    const starValue =
      r != null && r.stars != null && Number.isFinite(Number(r.stars))
        ? Number(r.stars)
        : 0;
    const starsHtml = this._formatEfficiencyStarsSvg(starValue, idPrefix);
    return `
      <button type="button" class="room-header-rating has-tooltip" data-room-rating="${esc(roomId)}"
        title="Efficiency rating — tap for details" aria-label="Efficiency rating for this room, tap for details">
        <span class="room-efficiency-stars">${starsHtml}</span>
      </button>`;
  }

  _startRoomRatingsAndHeartbeat() {
    if (!this._hass?.callWS) return;
    if (this._dashboardHeartbeatInterval != null) return;
    this._dashboardHeartbeatInterval = setInterval(
      () => this._sendDashboardHeartbeat(),
      30 * 60 * 1000,
    );
    this._sendDashboardHeartbeat();
  }

  _stopRoomRatingsAndHeartbeat() {
    if (this._dashboardHeartbeatInterval) {
      clearInterval(this._dashboardHeartbeatInterval);
      this._dashboardHeartbeatInterval = null;
    }
  }

  async _sendDashboardHeartbeat() {
    if (!this._hass?.callWS) return;
    try {
      await this._hass.callWS({ type: 'smart_dashboards/dashboard_heartbeat' });
    } catch (e) {
      /* non-fatal */
    }
  }

  _handleRoomRatingClick(e) {
    const statBtn = e.target?.closest?.('[data-stat-room-rating]');
    if (statBtn && this.shadowRoot.contains(statBtn)) {
      e.preventDefault();
      e.stopPropagation();
      const roomId = statBtn.getAttribute('data-stat-room-rating');
      if (!roomId) return;
      const statRow = (this._statsData?.rooms || []).find(
        (row) => String(row.id) === String(roomId),
      );
      this._openRoomRatingModal(roomId, {
        mode: 'monthly',
        ratings: statRow?.ratings || null,
      });
      return;
    }
    const btn = e.target?.closest?.('[data-room-rating]');
    if (!btn || !this.shadowRoot.contains(btn)) return;
    e.preventDefault();
    e.stopPropagation();
    if (btn.disabled) return;
    const roomId = btn.getAttribute('data-room-rating');
    if (roomId) this._openRoomRatingModal(roomId, { mode: 'intraday' });
  }

  /**
   * @param {string} roomId
   * @param {{ mode?: 'intraday'|'monthly', ratings?: object|null }} [options]
   */
  _openRoomRatingModal(roomId, options = {}) {
    const mode = options.mode === 'monthly' ? 'monthly' : 'intraday';
    const room = this._config?.rooms?.find(
      (r) => this._canonicalRoomId(r) === roomId,
    );
    const titleName = room?.name || roomId;
    let r = {};
    if (options.ratings != null && typeof options.ratings === 'object') {
      r = options.ratings;
    } else if (mode === 'intraday') {
      r = this._resolvePowerRoomRow(roomId)?.ratings || {};
    }
    const esc = (s) =>
      String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/"/g, '&quot;');
    const starN =
      r.stars != null && Number.isFinite(Number(r.stars)) ? Number(r.stars) : 0;
    const modalStarId = `m_${String(roomId).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    const starsHtml = this._formatEfficiencyStarsSvg(starN, modalStarId);
    const avgRounded =
      r.average != null && Number.isFinite(Number(r.average))
        ? Math.round(Number(r.average))
        : null;
    const pillarMeta = r.pillar_meta || {};
    const scoreRow = (pillarNum, key, title, desc) => {
      const meta = pillarMeta[key] || 'ok';
      const raw = r[key];
      let v =
        raw != null && Number.isFinite(Number(raw)) ? Math.round(Number(raw)) : null;
      if (meta === 'no_data') v = 0;
      if (meta === 'na') v = null;
      const pct =
        meta === 'na' ? 0 : v != null ? Math.max(0, Math.min(100, v)) : 0;
      const show =
        meta === 'na' ? '—' : meta === 'no_data' ? '0' : v != null ? `${v}` : '—';
      const statusNote =
        meta === 'no_data'
          ? 'No data yet'
          : meta === 'na'
            ? 'Non applicable'
            : '';
      const barLabel =
        meta === 'no_data'
          ? `${title}, no data yet`
          : meta === 'na'
            ? `${title}, not applicable`
            : v != null
              ? `${title}, ${v} out of 100`
              : `${title}, score not available`;
      const barAria =
        meta === 'na'
          ? ' aria-valuetext="not applicable"'
          : '';
      return `
        <div class="room-rating-modal-metric">
          <div class="room-rating-modal-metric-top">
            <div class="room-rating-modal-metric-text">
              <span class="room-rating-modal-metric-kicker">Pillar ${pillarNum}</span>
              <span class="room-rating-modal-metric-title">${esc(title)}</span>
              ${
                statusNote
                  ? `<span class="room-rating-modal-metric-status">${esc(statusNote)}</span>`
                  : ''
              }
              <span class="room-rating-modal-metric-desc">${esc(desc)}</span>
            </div>
            <span class="room-rating-modal-metric-value" aria-hidden="true">${show}</span>
          </div>
          <div class="room-rating-modal-metric-bar" role="progressbar" aria-valuenow="${meta === 'na' ? 0 : v != null ? v : 0}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(barLabel)}"${barAria}>
            <div class="room-rating-modal-metric-fill" style="width: ${pct}%${meta === 'na' ? '; opacity: 0.35' : ''}"></div>
          </div>
        </div>`;
    };

    const heroStarsLabel = `Overall efficiency, ${starN} out of 5 stars`;
    const engagementNa = pillarMeta.engagement === 'na';
    const scopePhrase =
      mode === 'monthly' ? 'this statistics period' : 'today';
    const heroIntro = engagementNa
      ? `Engagement is off without an assigned person. The score above is the average of the four pillars below (0–100 each) for ${scopePhrase}.`
      : `The score above is the average of five pillars (0–100 each) for ${scopePhrase}, including engagement from this room’s assignee.`;

    const personEnt = String(room?.presence_person_entity || '').trim();
    const personState =
      personEnt && this._hass?.states ? this._hass.states[personEnt] : null;
    const personNameRaw =
      (personState?.attributes?.friendly_name || '').trim() ||
      (personEnt.startsWith('person.')
        ? personEnt.slice(7).replace(/_/g, ' ')
        : 'This person');
    const loadHighRaw = this._config?.efficiency_settings?.load_high_watts;
    const loadHighW =
      loadHighRaw != null && Number.isFinite(Number(loadHighRaw))
        ? Math.max(1, Math.round(Number(loadHighRaw)))
        : 100;
    const loadPatternDesc =
      mode === 'monthly'
        ? `Rewards steadier use; sustained heavy draw in this period (from daily use above your budget tolerance, expressed as time near about ${loadHighW} W) lowers this score.`
        : `Rewards steadier use; more time above about ${loadHighW} W today (counted as hours in the window) lowers this score.`;

    const engMeta = pillarMeta.engagement || 'ok';
    let engagementDesc;
    if (engMeta === 'na') {
      engagementDesc =
        'Only applies when this room has an assigned person in settings.';
    } else if (engMeta === 'no_data') {
      engagementDesc =
        mode === 'monthly'
          ? `How often ${personNameRaw} opened this dashboard in this period; steadier use scores higher. No activity in range yet.`
          : `How often ${personNameRaw} opens this dashboard today; steadier use scores higher. No activity yet.`;
    } else {
      engagementDesc =
        mode === 'monthly'
          ? `How often ${personNameRaw} opened this dashboard across this period; steadier use scores higher.`
          : `How often ${personNameRaw} opens this dashboard today; steadier use scores higher.`;
    }

    const complianceDesc =
      mode === 'monthly'
        ? 'Share of days in this period under your room kWh budget (with tolerance).'
        : 'Today’s energy vs your room kWh budget (with tolerance).';
    const warningDesc =
      mode === 'monthly'
        ? 'Alerts, shutoffs, and enforcement cycles in this period—fewer is better.'
        : 'Today’s alerts, shutoffs, and enforcement cycles—fewer is better.';
    const consumptionDesc =
      mode === 'monthly'
        ? 'Average daily use vs your other rooms this period.'
        : 'Today’s use vs your other rooms today.';
    const footnote =
      mode === 'monthly'
        ? 'Based on the statistics date range (updates when statistics refresh).'
        : 'Updates with live power data.';

    this.shadowRoot.querySelector('.room-rating-modal-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.className = 'room-rating-modal-overlay';
    overlay.innerHTML = `
      <div class="room-rating-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="room-rating-modal-room">
        <div class="room-rating-modal-header">
          <div class="room-rating-modal-header-text">
            <p class="room-rating-modal-eyebrow">Efficiency</p>
            <h2 id="room-rating-modal-room" class="room-rating-modal-room">${esc(titleName)}</h2>
          </div>
          <button type="button" class="room-rating-modal-close" aria-label="Close">&times;</button>
        </div>
        <div class="room-rating-modal-hero">
          <div class="room-rating-modal-stars" role="img" aria-label="${esc(heroStarsLabel)}">${starsHtml}</div>
          ${
            avgRounded != null
              ? `<div class="room-rating-modal-index">
            <span class="room-rating-modal-index-value">${avgRounded}</span>
            <span class="room-rating-modal-index-suffix">/ 100</span>
          </div>
          <p class="room-rating-modal-index-caption">Overall score</p>`
              : ''
          }
          <p class="room-rating-modal-hero-intro">${esc(heroIntro)}</p>
        </div>
        <div class="room-rating-modal-body">
          ${scoreRow(1, 'compliance', 'Compliance', complianceDesc)}
          ${scoreRow(2, 'warning', 'Warnings', warningDesc)}
          ${scoreRow(3, 'consumption', 'Consumption', consumptionDesc)}
          ${scoreRow(4, 'load', 'Load', loadPatternDesc)}
          ${scoreRow(5, 'engagement', 'Engagement', engagementDesc)}
        </div>
        <p class="room-rating-modal-footnote">${esc(footnote)}</p>
      </div>
    `;
    const close = () => {
      overlay.remove();
      if (this._roomRatingModalEsc) {
        window.removeEventListener('keydown', this._roomRatingModalEsc);
        this._roomRatingModalEsc = null;
      }
    };
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) close();
    });
    overlay.querySelector('.room-rating-modal-close')?.addEventListener('click', close);
    this._roomRatingModalEsc = (kev) => {
      if (kev.key === 'Escape') close();
    };
    window.addEventListener('keydown', this._roomRatingModalEsc);
    this.shadowRoot.appendChild(overlay);
    overlay.querySelector('.room-rating-modal-close')?.focus();
  }

  _renderRoomCard(room) {
    const roomId = this._canonicalRoomId(room);
    const baseBudget = Number(room.kwh_budget);
    const fallbackBudget = Number.isFinite(baseBudget) ? baseBudget : 5;
    const roomData = this._resolvePowerRoomRow(roomId) || {
      total_watts: 0,
      total_day_wh: 0,
      warnings: 0,
      shutoffs: 0,
      power_cycles: 0,
      outlets: [],
      kwh_budget: fallbackBudget,
    };

    const isOverThreshold = room.threshold > 0 && roomData.total_watts > room.threshold;
    const warnings = roomData.warnings || 0;
    const shutoffs = roomData.shutoffs || 0;
    const powerCycles = roomData.power_cycles || 0;
    const enfPhase = typeof roomData.enforcement_phase === 'number' ? roomData.enforcement_phase : 0;
    const budget = this._roomBudgetUiState(roomData, room);
    let fillClass = `room-budget-bar-fill kwh-tier-${budget.kwhTier}`;
    if (budget.over) fillClass += ' over';
    else if (budget.overBudget) fillClass += ' over-budget';
    const budgetSub = this._budgetBarSubtitle(budget);
    const markersHtml = this._roomBudgetMarkersHtml(budget);
    const trackTitle =
      "Open today's kWh chart — scale 0–" +
      budget.maxInterval +
      ' kWh; blue tick = first voice alert tier' +
      (budget.showSeparateBudget ? '; dashed tick = daily budget' : '');

    const thresholdPill = room.threshold > 0
      ? `<span class="room-threshold-pill has-tooltip" title="Room power threshold: spoken alert when exceeded">
           <svg viewBox="0 0 24 24">${icons.warning}</svg>${room.threshold} W
         </span>`
      : '';

    const enforcementInline = this._enforcementBadgeHtml(roomId, enfPhase, true);
    const badgesInner = `${thresholdPill}${enforcementInline}`.trim();
    const badgesHtml = badgesInner
      ? `<div class="room-header-badges">${badgesInner}</div>`
      : '';
    const roomCardIcon = this._effectiveRoomIcon(room).replace(/"/g, '&quot;');

    const personEntRaw = (room.presence_person_entity || '').trim();
    const personEntKey = personEntRaw.toLowerCase();
    const zoneHealthIssue =
      personEntKey &&
      this._zoneHealthData?.persons?.some(p => p.entity_id === personEntKey && !p.is_healthy);
    const iconClass = `room-icon${zoneHealthIssue ? ' zone-health-issue' : ''}`;
    const iconDataAttr = personEntRaw
      ? ` data-zone-health-person="${personEntKey.replace(/"/g, '&quot;')}"`
      : '';
    const escAttr = (s) =>
      String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
    const escHtmlText = (s) =>
      String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    const roomNameEsc = escHtmlText(room.name || '');

    let roomNameHtml = `<h3 class="room-name">${roomNameEsc}</h3>`;
    if (personEntRaw) {
      const personState =
        this._hass?.states?.[personEntKey] || this._hass?.states?.[personEntRaw];
      const presencePlain = this._presenceLabelFromPersonState(personState);
      const presenceLabel = escHtmlText(presencePlain);
      const ariaCycle = escAttr(
        `Alternates: ${room.name || roomId}, then ${presencePlain}`,
      );
      roomNameHtml = `<h3 class="room-name room-name--cycling" data-has-presence="true" aria-label="${ariaCycle}">
              <span class="room-name-text">${roomNameEsc}</span>
              <span class="room-name-presence">${presenceLabel}</span>
            </h3>`;
    }

    let iconTitle = (room.name || '').trim();
    let iconAriaLabel = iconTitle || roomId;
    if (personEntRaw) {
      const personState =
        this._hass?.states?.[personEntKey] || this._hass?.states?.[personEntRaw];
      if (personState) {
        const personName =
          personState.attributes?.friendly_name ||
          personEntKey.replace('person.', '').replace(/_/g, ' ');
        const location = this._formatPresenceLocationDisplay(personState);
        iconTitle = `${personName}: ${location}`;
        iconAriaLabel = `${room.name || roomId}, presence: ${personName}, ${location}`;
      }
    }
    const iconTitleAttr = iconTitle ? ` title="${escAttr(iconTitle)}"` : '';
    const iconAriaAttr = ` aria-label="${escAttr(iconAriaLabel)}"`;

    const ratingIdSafe = String(roomId).replace(/[^a-zA-Z0-9_-]/g, '_');
    const starsRowHtml = this._roomEfficiencyRatingRowHtml(roomId, ratingIdSafe);

    return `
      <div class="room-card" data-room-id="${roomId}">
        <div class="room-header">
          <div class="room-header-inner room-header-rail">
            <div class="${iconClass}"${iconDataAttr}${iconTitleAttr}${iconAriaAttr}>
              <ha-icon icon="${roomCardIcon}"></ha-icon>
            </div>
            <div class="room-header-title-wrap">
              ${roomNameHtml}
              ${starsRowHtml}
              ${badgesHtml}
            </div>
            <div class="room-event-chips">
              <span class="event-count graph-clickable has-tooltip" data-event="warnings" data-graph-type="room_warnings" data-room-id="${roomId}" title="Threshold warnings today (tap for log)">W ${warnings}</span>
              <span class="event-count graph-clickable has-tooltip" data-event="shutoffs" data-graph-type="room_shutoffs" data-room-id="${roomId}" title="Safety shutoffs today">S ${shutoffs}</span>
              <span class="event-count graph-clickable has-tooltip" data-event="power_cycles" data-graph-type="room_power_cycles" data-room-id="${roomId}" title="Enforcement outlet cycles today">C ${powerCycles}</span>
            </div>
            <div class="room-header-watts-col">
              <span class="room-total-watts ${isOverThreshold ? 'over-threshold' : ''}">${roomData.total_watts.toFixed(1)} W</span>
            </div>
          </div>
        </div>

        <div class="room-content">
          <div class="outlets-grid">
            ${(room.outlets || []).map((device, oi) => this._renderDeviceCard(device, oi, (roomData.outlets || [])[oi])).join('')}
          </div>
        </div>

        <div class="room-footer">
          <div class="room-budget-section${budget.showBar ? '' : ' room-budget-section--na'}" role="group" aria-label="Daily kilowatt-hours, scale and budget markers">
            <div class="room-budget-bar-track graph-clickable" data-graph-type="room_wh" data-room-id="${roomId}" title="${trackTitle.replace(/"/g, '&quot;')}">
              <div class="${fillClass}" style="width: ${budget.showBar ? budget.fillPct : 0}%"></div>
              ${markersHtml}
              <div class="room-budget-bar-labels">
                <span class="room-budget-values">${budget.showBar ? `${budget.usedKwh.toFixed(2)} kWh` : '—'}</span>
                ${budgetSub ? `<span class="room-budget-sub">${budgetSub}</span>` : ''}
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderDeviceCard(device, index, deviceData) {
    const type = device.type || 'outlet';
    if (type === 'stove') return this._renderStoveCard(device, index, deviceData);
    if (type === 'microwave') return this._renderMicrowaveCard(device, index, deviceData);
    if (type === 'minisplit') return this._renderMinisplitCard(device, index, deviceData);
    if (type === 'fridge') return this._renderFridgeCard(device, index, deviceData);
    if (isVentLikeType(type)) return this._renderVentLikeCard(device, index, deviceData);
    if (type === 'light') return this._renderLightCard(device, index, deviceData);
    return this._renderOutletCard(device, index, deviceData);
  }

  _formatStoveTimerRemaining(phase, remSec) {
    const r = remSec != null ? Number(remSec) : 0;
    if (phase === '15min' && r > 0) {
      const m = Math.floor(r / 60);
      const s = Math.floor(r % 60);
      return `${m}:${String(s).padStart(2, '0')} left`;
    }
    if (phase === '30sec' && r > 0) {
      return `${Math.ceil(r)}s left`;
    }
    return '';
  }

  /** Compact readout for vent/heater card; kW + title when >= 1000 W. */
  _formatCeilingVentWatts(watts) {
    const w = Number(watts) || 0;
    const full = `${w.toFixed(1)} W`;
    if (w >= 1000) {
      return { text: `${(w / 1000).toFixed(2)} kW`, title: full };
    }
    return { text: full, title: '' };
  }

  /** Wall heater run segment countdown (matches stove-style compact line). */
  _formatHeaterRunRemaining(totalSec) {
    const t = Math.max(0, Math.floor(Number(totalSec) || 0));
    if (t <= 0) return '';
    const m = Math.floor(t / 60);
    const s = t % 60;
    if (m > 0) return `${m}:${String(s).padStart(2, '0')} left`;
    return `${s}s left`;
  }

  _renderStoveCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;
    const timerPhase = data.timer_phase || 'none';
    const timerRem = data.time_remaining;
    const timerLine = this._formatStoveTimerRemaining(timerPhase, timerRem);
    const timerHidden = !timerLine;

    return `
      <div class="device-card stove-card" data-outlet-index="${index}">
        <div class="stove-faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="stove-body">
            <div class="stove-control-panel">
              <div class="stove-display"></div>
              <div class="stove-knobs">
                <div class="stove-knob ${isActive ? 'active' : ''}"></div>
                <div class="stove-knob"></div>
                <div class="stove-knob"></div>
                <div class="stove-knob"></div>
              </div>
              <div class="stove-display"></div>
            </div>
            <div class="stove-oven-door ${isActive ? 'active' : ''}">
              <div class="stove-handle"></div>
              <div class="stove-oven-window">
                <div class="stove-door-watts ${isOverThreshold ? 'over-threshold' : ''}">${watts.toFixed(1)} W</div>
                <div class="stove-timer-remaining" style="${timerHidden ? 'display:none;' : ''}" title="Unattended cooking timer">${timerLine}</div>
              </div>
            </div>
            <div class="stove-lower-panel"></div>
            <div class="stove-kickplate"></div>
          </div>
          <div class="outlet-meta stove-meta">
            <div class="outlet-threshold">
              <span class="threshold-badge">∞ W</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderMicrowaveCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;

    return `
      <div class="device-card microwave-card" data-outlet-index="${index}">
        <div class="mw-faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="mw-body ${isActive ? 'mw-on' : ''}">
            <div class="mw-door">
              <div class="mw-window"></div>
              <div class="mw-handle"></div>
            </div>
            <div class="mw-controls">
              <div class="mw-lcd">
                <div class="mw-lcd-watts ${isOverThreshold ? 'over-threshold' : ''}">${watts.toFixed(1)} W</div>
              </div>
              <div class="mw-keys">
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
                <div class="mw-key"></div>
              </div>
              <div class="mw-actions">
                <div class="mw-btn-pill"></div>
                <div class="mw-btn-round"></div>
              </div>
              <div class="mw-door-btn-wrap">
                <div class="mw-door-btn"></div>
              </div>
            </div>
          </div>
          <div class="outlet-meta mw-meta">
            <div class="outlet-threshold">
              <span class="threshold-badge">${device.threshold > 0 ? `${device.threshold}W` : '∞ W'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderLightCard(device, index, deviceData) {
    const isOn = deviceData?.switch_state === true;
    const totalWatts = isOn ? (deviceData?.plug1?.watts || 0) : 0;
    return `
      <div class="outlet-card outlet-face light-outlet ${isOn ? 'light-on' : ''}" data-outlet-index="${index}">
        <div class="faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="center-screw plate-screw" aria-hidden="true"></div>
          <div class="light-switch-plate ${isOn ? 'active' : ''}">
            <div class="light-toggle-lever ${isOn ? 'on' : 'off'}">
              <span class="light-toggle-label">${isOn ? 'ON' : 'OFF'}</span>
            </div>
          </div>
          <div class="center-screw plate-screw" aria-hidden="true"></div>
          <div class="outlet-meta light-outlet-meta">
            <div class="outlet-total light-watts-display">${totalWatts.toFixed(1)} W</div>
          </div>
        </div>
      </div>
    `;
  }

  _renderMinisplitCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;

    return `
      <div class="device-card minisplit-card" data-outlet-index="${index}">
        <div class="ms-faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="ms-unit ${isActive ? 'ms-on' : ''}">
            <div class="ms-upper-panel">
              <div class="ms-lcd">
                <div class="ms-lcd-watts ${isOverThreshold ? 'over-threshold' : ''}">${watts.toFixed(1)} W</div>
              </div>
            </div>
            <div class="ms-body"></div>
            <div class="ms-vent">
              <div class="ms-vent-inner">
                <span class="ms-slat"></span>
                <span class="ms-slat"></span>
                <span class="ms-slat"></span>
                <span class="ms-slat"></span>
              </div>
            </div>
          </div>
          <div class="outlet-meta ms-meta">
            <div class="outlet-threshold">
              <span class="threshold-badge">${device.threshold > 0 ? `${device.threshold}W` : '∞ W'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderFridgeCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;

    return `
      <div class="device-card fridge-card" data-outlet-index="${index}">
        <div class="fridge-faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="fridge-body ${isActive ? 'fridge-on' : ''}">
            <div class="fridge-freezer-door">
              <div class="fridge-door-panel"></div>
              <div class="fridge-handle-vert"></div>
            </div>
            <div class="fridge-seam"></div>
            <div class="fridge-fresh-door">
              <div class="fridge-door-panel"></div>
              <div class="fridge-handle-vert"></div>
            </div>
            <div class="fridge-kickplate"></div>
            <div class="fridge-watts ${isOverThreshold ? 'over-threshold' : ''}">${watts.toFixed(1)} W</div>
          </div>
          <div class="outlet-meta fridge-meta">
            <div class="outlet-threshold">
              <span class="threshold-badge">${device.threshold > 0 ? `${device.threshold}W` : '∞ W'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderVentLikeCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;
    const kind = (device.type || 'vent') === 'wall_heater' ? 'Wall heater' : 'Vent';
    const displayTitle = device.name || kind;
    const isWallHeater = (device.type || 'vent') === 'wall_heater';
    const belowN = device.heater_on_below_temperature ?? 65;
    const belowDec = belowN % 1 === 0 ? 0 : 1;
    let tempStr = '—';
    const hc = data.heater_current_temperature;
    if (isWallHeater && hc != null && hc !== '' && !Number.isNaN(Number(hc))) {
      tempStr = `${Number(hc).toFixed(1)}°`;
    }
    const ht = isWallHeater ? (data.heater_time_remaining_sec || 0) : 0;
    const timerStr = ht > 0 ? this._formatHeaterRunRemaining(ht) : '';
    const heaterDash = isWallHeater ? `
            <div class="heater-dash-meta">
              <div class="heater-dash-row heater-dash-row-temps">
                <span class="heater-dash-lbl">Now</span><span class="heater-dash-val heater-dash-now-val">${tempStr}</span>
                <span class="heater-dash-dot">·</span>
                <span class="heater-dash-lbl">On≤</span><span class="heater-dash-val heater-dash-threshold-val">${Number(belowN).toFixed(belowDec)}°</span>
              </div>
              <div class="heater-dash-row heater-dash-row-run"${timerStr ? '' : ' style="display:none"'}>
                <span class="heater-dash-lbl">Run</span><span class="heater-dash-val heater-dash-timer">${timerStr}</span>
              </div>
            </div>` : '';
    const wFmt = this._formatCeilingVentWatts(watts);
    const cvTitleAttr = wFmt.title ? ` title="${wFmt.title.replace(/"/g, '&quot;')}"` : '';

    return `
      <div class="device-card ceiling-vent-card" data-outlet-index="${index}">
        <div class="ceiling-vent-faceplate">
          <div class="outlet-name outlet-name-top" title="${displayTitle.replace(/"/g, '&quot;')}">${displayTitle.replace(/</g, '&lt;')}</div>
          <div class="ceiling-vent-body ${isActive ? 'vent-on' : ''}">
            <div class="ceiling-vent-grill-wrap">
              <div class="ceiling-vent-grill">
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
                <span class="cv-slat"></span>
              </div>
              ${isActive ? '<div class="cv-air-particles"><span class="cv-particle"></span><span class="cv-particle"></span><span class="cv-particle"></span><span class="cv-particle"></span><span class="cv-particle"></span></div>' : ''}
            </div>
            <div class="ceiling-vent-watts-row">
              <div class="ceiling-vent-watts ${isOverThreshold ? 'over-threshold' : ''}"${cvTitleAttr}>${wFmt.text}</div>
            </div>
          </div>
          <div class="outlet-meta ceiling-vent-meta">
            <div class="outlet-threshold">
              <span class="threshold-badge">${device.threshold > 0 ? `${device.threshold}W` : '∞ W'}</span>
            </div>
            ${heaterDash}
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletCard(outlet, index, outletData) {
    const isSingleOutlet = (outlet.type || 'outlet') === 'single_outlet';
    const data = outletData || { plug1: { watts: 0 }, plug2: { watts: 0 } };
    const outletTotal = isSingleOutlet
      ? (data.plug1?.watts || 0)
      : (data.plug1?.watts || 0) + (data.plug2?.watts || 0);
    const isOverThreshold = outlet.threshold > 0 && outletTotal > outlet.threshold;
    const plug1Active = (data.plug1?.watts || 0) > 0.1;
    const plug2Active = (data.plug2?.watts || 0) > 0.1;

    if (isSingleOutlet) {
      return `
      <div class="outlet-card outlet-face single-outlet" data-outlet-index="${index}">
        <div class="faceplate">
          <div class="outlet-name outlet-name-top" title="${(outlet.name || '').replace(/"/g, '&quot;')}">${outlet.name || ''}</div>
          <div class="center-screw plate-screw" aria-hidden="true"></div>
          <div class="receptacle single-receptacle ${plug1Active ? 'active' : ''}">
            <div class="holes" aria-hidden="true">
              <span class="slot left"></span>
              <span class="slot right"></span>
              <span class="ground"></span>
            </div>
            <div class="plug-readout">
              <span class="plug-label">Plug</span>
              <span class="plug-watts plug1-watts">${(data.plug1?.watts || 0).toFixed(1)}W</span>
            </div>
          </div>
          <div class="center-screw plate-screw" aria-hidden="true"></div>
          <div class="outlet-meta">
            <div class="outlet-total ${isOverThreshold ? 'over-threshold' : ''}">${outletTotal.toFixed(1)} W</div>
            <div class="outlet-threshold">
              <span class="threshold-badge">${outlet.threshold > 0 ? `${outlet.threshold}W` : '∞ W'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
    }

    return `
      <div class="outlet-card outlet-face" data-outlet-index="${index}">
        <div class="faceplate">
          <div class="outlet-name outlet-name-top" title="${(outlet.name || '').replace(/"/g, '&quot;')}">${outlet.name || ''}</div>
          <div class="receptacle plug-receptacle ${plug1Active ? 'active' : ''}" data-plug-index="1" title="Click to toggle Plug 1">
            <div class="holes" aria-hidden="true">
              <span class="slot left"></span>
              <span class="slot right"></span>
              <span class="ground"></span>
            </div>
            <div class="plug-readout">
              <span class="plug-label">P1</span>
              <span class="plug-watts plug1-watts">${(data.plug1?.watts || 0).toFixed(1)}W</span>
            </div>
          </div>

          <div class="center-screw" aria-hidden="true"></div>

          <div class="receptacle plug-receptacle ${plug2Active ? 'active' : ''}" data-plug-index="2" title="Click to toggle Plug 2">
            <div class="holes" aria-hidden="true">
              <span class="slot left"></span>
              <span class="slot right"></span>
              <span class="ground"></span>
            </div>
            <div class="plug-readout">
              <span class="plug-label">P2</span>
              <span class="plug-watts plug2-watts">${(data.plug2?.watts || 0).toFixed(1)}W</span>
            </div>
          </div>

          <div class="outlet-meta">
            <div class="outlet-total ${isOverThreshold ? 'over-threshold' : ''}">${outletTotal.toFixed(1)} W</div>
            <div class="outlet-threshold">
              <span class="threshold-badge">${outlet.threshold > 0 ? `${outlet.threshold}W` : '∞ W'}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _updateStoveDisplay() {
    if (!this._stoveData || this._showSettings || this._dashboardView !== 'stove') return;

    const panel = this.shadowRoot.querySelector('.stove-safety-panel');
    if (!panel) return;

    // Update timer display if present
    const timerTime = panel.querySelector('.stove-timer-time');
    if (timerTime && this._stoveData.timer_phase !== 'none') {
      const timeRemaining = this._stoveData.time_remaining || 0;
      const timerPhase = this._stoveData.timer_phase;
      
      if (timerPhase === '15min') {
        const mins = Math.floor(timeRemaining / 60);
        const secs = timeRemaining % 60;
        timerTime.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
      } else {
        timerTime.textContent = `${timeRemaining}s`;
      }
    }

    // Update status indicators
    const statusState = panel.querySelector('.stove-status-state');
    if (statusState) {
      statusState.textContent = this._stoveData.stove_state === 'on' ? 'ON' : 'OFF';
      statusState.className = `stove-status-state ${this._stoveData.stove_state}`;
    }

    const statusIcon = panel.querySelector('.stove-status-icon');
    if (statusIcon) {
      statusIcon.className = `stove-status-icon ${this._stoveData.stove_state}`;
    }

    const powerValue = panel.querySelector('.stove-detail-value');
    if (powerValue && panel.querySelector('.stove-detail-label')?.textContent === 'Current Power') {
      powerValue.textContent = `${this._stoveData.current_power.toFixed(1)} W`;
    }

    const presenceValue = panel.querySelector('.stove-detail-value.present, .stove-detail-value.absent');
    if (presenceValue) {
      const isPresent = this._stoveData.presence_detected;
      presenceValue.textContent = isPresent ? 'Detected' : 'Not Detected';
      presenceValue.className = `stove-detail-value ${isPresent ? 'present' : 'absent'}`;
    }
  }

  _escapeForSettingsTextarea(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
  }

  /** Parse AM/PM time string to 24h HH:MM. */
  _parseAmPmTo24h(s, fallback = '12:00') {
    if (!s) return fallback;
    const match = String(s).trim().match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/i);
    if (!match) return fallback;
    let h = parseInt(match[1], 10);
    const m = parseInt(match[2], 10);
    const ampm = (match[3] || '').toUpperCase();
    if (ampm === 'PM' && h < 12) h += 12;
    if (ampm === 'AM' && h === 12) h = 0;
    if (h < 0 || h > 23 || m < 0 || m > 59) return fallback;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }

  /** Budget boost schedule (enforcement tab); merged into tts_settings on save. */
  _collectBudgetBoostFromDom() {
    const root = this.shadowRoot;
    const enabled = root.querySelector('#pe-budget-boost-enabled')?.checked === true;
    const mult = Math.max(1, Math.min(5, parseFloat(root.querySelector('#pe-budget-boost-mult')?.value) || 2));
    const winStartRaw = (root.querySelector('#pe-budget-boost-win-start')?.value || '').trim();
    const winEndRaw = (root.querySelector('#pe-budget-boost-win-end')?.value || '').trim();
    const winStart = this._parseAmPmTo24h(winStartRaw, '09:00');
    const winEnd = this._parseAmPmTo24h(winEndRaw, '21:00');
    const repeatMin = Math.max(
      60,
      Math.min(720, parseInt(root.querySelector('#pe-budget-boost-repeat')?.value, 10) || 120),
    );
    const mo = Math.max(0, Math.min(59, parseInt(root.querySelector('#pe-budget-boost-mo')?.value, 10) || 0));
    const weekdays = [];
    root.querySelectorAll('.pe-budget-boost-day:checked').forEach((cb) => {
      const n = parseInt(cb.value, 10);
      if (!Number.isNaN(n) && n >= 0 && n <= 6 && !weekdays.includes(n)) weekdays.push(n);
    });
    weekdays.sort((a, b) => a - b);
    return {
      budget_boost_enabled: enabled,
      budget_boost_multiplier: mult,
      budget_boost_weekdays: weekdays,
      budget_boost_window_start: winStart,
      budget_boost_window_end: winEnd,
      budget_boost_repeat_minutes: repeatMin,
      budget_boost_minute_offset: mo,
      budget_boost_announce_time: winStart,
    };
  }

  /** Per-line TTS on/off (saved as `${lineKey}_tts_enabled`, default on). */
  _ttsLineEnableHtml(tsSettings, lineKey, controlsSelector = '') {
    const storageKey = `${lineKey}_tts_enabled`;
    const on = tsSettings[storageKey] !== false;
    const id = `tts-enable-${lineKey.replace(/_/g, '-')}`;
    const dataAttr = controlsSelector
      ? ` data-tts-controls="${controlsSelector.replace(/"/g, '&quot;')}"`
      : '';
    return `
      <div class="toggle-row tts-line-enable-row">
        <label class="toggle-switch">
          <input type="checkbox" id="${id}" class="tts-line-enable"${dataAttr} data-tts-line="${lineKey}" ${on ? 'checked' : ''} />
          <span class="toggle-slider"></span>
        </label>
        <span class="toggle-label" style="font-size:11px;">Enable speech</span>
      </div>
    `;
  }

  _bindTtsLineEnableToggles() {
    const tab = this.shadowRoot.querySelector('#tab-tts');
    if (!tab) return;
    const applyOne = (cb) => {
      const controls = cb.getAttribute('data-tts-controls');
      const on = cb.checked;
      if (controls) {
        const el = this.shadowRoot.querySelector(controls);
        if (el) el.disabled = !on;
        return;
      }
      const group = cb.closest('.tts-msg-group');
      if (!group) return;
      group.querySelectorAll('input.form-input, textarea.tts-msg-textarea').forEach((el) => {
        if (el.classList.contains('tts-line-enable')) return;
        el.disabled = !on;
      });
    };
    tab.querySelectorAll('.tts-line-enable').forEach((cb) => {
      applyOne(cb);
      cb.addEventListener('change', () => applyOne(cb));
    });
    const ventCb = tab.querySelector('#tts-vent-automation-enabled');
    const ventMsg = tab.querySelector('#tts-vent-automation-msg');
    if (ventCb && ventMsg) {
      const syncVent = () => {
        ventMsg.disabled = !ventCb.checked;
      };
      syncVent();
      ventCb.addEventListener('change', syncVent);
    }
    const hCb = tab.querySelector('#tts-heater-automation-enabled');
    const hMsg = tab.querySelector('#tts-heater-automation-msg');
    if (hCb && hMsg) {
      const syncH = () => {
        hMsg.disabled = !hCb.checked;
      };
      syncH();
      hCb.addEventListener('change', syncH);
    }
  }

  _renderSettings(styles) {
    const rooms = this._config?.rooms || [];
    const mediaPlayers = this._entities?.media_players || [];
    const powerSensors = this._entities?.power_sensors || [];
    const sensors = this._entities?.sensors || this._entities?.power_sensors || [];
    const ttsSettings = this._config?.tts_settings || {};
    const statsSettings = this._config?.statistics_settings || {};
    const effSettings = this._config?.efficiency_settings || {};
    const pe = this._config?.power_enforcement || {};
    const roomsEnabled = pe.rooms_enabled || [];
    const bbwRaw = ttsSettings.budget_boost_weekdays;
    const budgetBoostWeekdaySet = new Set(
      Array.isArray(bbwRaw)
        ? bbwRaw.map((n) => Number(n)).filter((n) => !Number.isNaN(n) && n >= 0 && n <= 6)
        : [5, 6],
    );
    const bbDayChk = (d) => (budgetBoostWeekdaySet.has(d) ? 'checked' : '');
    const bbWinStart24 = ttsSettings.budget_boost_window_start || ttsSettings.budget_boost_announce_time || '09:00';
    const bbWinEnd24 = ttsSettings.budget_boost_window_end || '21:00';
    const toAmPm = (hhmm) => {
      const [h, m] = (hhmm || '12:00').split(':').map(Number);
      const hr = h % 12 || 12;
      const ampm = h < 12 ? 'AM' : 'PM';
      return `${hr}:${String(m || 0).padStart(2, '0')} ${ampm}`;
    };
    const bbWinStartAmPm = toAmPm(bbWinStart24);
    const bbWinEndAmPm = toAmPm(bbWinEnd24);
    const bbRepeat = ttsSettings.budget_boost_repeat_minutes ?? 120;
    const bbMo = ttsSettings.budget_boost_minute_offset ?? 0;
    const repeatOpts = [
      { val: 60, label: 'Every Hour' },
      { val: 120, label: 'Every 2 Hours' },
      { val: 180, label: 'Every 3 Hours' },
      { val: 240, label: 'Every 4 Hours' },
      { val: 360, label: 'Every 6 Hours' },
    ];
    const repeatOptHtml = repeatOpts.map(
      (o) => `<option value="${o.val}" ${bbRepeat === o.val ? 'selected' : ''}>${o.label}</option>`,
    ).join('');
    const schedEsc = this._escapeForSettingsTextarea(
      ttsSettings.budget_boost_scheduled_msg || TTS_DEFAULTS.budget_boost_scheduled_msg,
    );
    const p1BoostEsc = this._escapeForSettingsTextarea(
      ttsSettings.phase1_warn_msg_boost_day || TTS_DEFAULTS.phase1_warn_msg_boost_day,
    );
    const stoveProgressEsc = this._escapeForSettingsTextarea(
      ttsSettings.stove_timer_progress_msg || TTS_DEFAULTS.stove_timer_progress_msg,
    );
    const ttsDefaultMpVal =
      (ttsSettings.tts_default_media_player || ttsSettings.budget_boost_announce_media_player || '').trim();

    this.shadowRoot.innerHTML = `
      <style>
        ${styles}
        
        .settings-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 16px;
          background: var(--secondary-background-color);
          padding: 4px;
          border-radius: 8px;
        }
        
        .settings-tab {
          flex: 1;
          padding: 10px 16px;
          border: none;
          background: transparent;
          color: var(--disabled-text-color);
          cursor: pointer;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 500;
          transition: all 0.2s;
        }
        
        .settings-tab:hover {
          background: rgba(255, 255, 255, 0.05);
        }
        
        .settings-tab.active {
          background: var(--panel-accent);
          color: white;
        }
        
        .settings-tab-content {
          display: none;
        }
        
        .settings-tab-content.active {
          display: block;
        }
        
        .tts-msg-group {
          margin-bottom: 16px;
          padding: 14px;
          background: var(--input-bg);
          border-radius: 8px;
          border: 1px solid var(--card-border);
        }
        
        .tts-msg-title {
          font-size: 11px;
          font-weight: 600;
          color: var(--panel-accent);
          margin-bottom: 6px;
        }
        
        .tts-msg-desc {
          font-size: 10px;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        
        .tts-var-help {
          font-size: 9px;
          color: var(--secondary-text-color);
          margin-top: 6px;
          padding: 6px 8px;
          background: rgba(0, 0, 0, 0.2);
          border-radius: 4px;
        }
        .tts-msg-textarea {
          width: 100%;
          min-height: 92px;
          resize: vertical;
          font-family: inherit;
          font-size: 14px;
          line-height: 1.45;
          padding: 12px 14px;
          border-radius: 8px;
          border: 1px solid var(--input-border, rgba(255, 255, 255, 0.12));
          background: var(--input-bg, #282828);
          color: var(--primary-text-color, #e0e0e0);
          box-sizing: border-box;
          transition: border-color 0.2s, background 0.2s;
        }
        .tts-msg-textarea:focus {
          outline: none;
          border-color: var(--panel-accent);
          background: var(--input-bg, #282828);
        }
        .tts-msg-textarea:disabled {
          opacity: 0.55;
          cursor: not-allowed;
        }
        .tts-msg-header-row {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          gap: 8px;
          margin-bottom: 8px;
        }
        .tts-msg-header-row .tts-line-enable-row {
          margin: 0 !important;
          align-self: flex-end;
          flex-shrink: 0;
          justify-content: flex-end;
        }
        .form-input:disabled {
          opacity: 0.55;
          cursor: not-allowed;
        }
        .pe-budget-boost-section {
          margin-bottom: 16px;
        }
        
        .tts-var-help code {
          color: var(--panel-accent);
          background: rgba(3, 169, 244, 0.15);
          padding: 1px 4px;
          border-radius: 3px;
          font-size: 9px;
        }
      </style>
      <div class="panel-container">
        <div class="panel-header">
          <button class="menu-btn" id="menu-btn" title="Menu">
            <svg viewBox="0 0 24 24">${icons.menu}</svg>
          </button>
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.settings}</svg>
            Energy Settings
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="back-btn">Back to Dashboard</button>
            <button class="btn btn-primary" id="save-btn">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.check}</svg>
              Save Changes
            </button>
          </div>
        </div>

        <div class="content-area">
          <div class="settings-tabs">
            <button class="settings-tab ${this._settingsTab === 'rooms' ? 'active' : ''}" data-tab="rooms">
              Rooms & Devices
            </button>
            <button class="settings-tab ${this._settingsTab === 'tts' ? 'active' : ''}" data-tab="tts">
              TTS Settings
            </button>
            <button class="settings-tab ${this._settingsTab === 'notifications' ? 'active' : ''}" data-tab="notifications">
              Notifications
            </button>
            <button class="settings-tab ${this._settingsTab === 'zone-health' ? 'active' : ''}" data-tab="zone-health">
              Zone Health
            </button>
            <button class="settings-tab ${this._settingsTab === 'statistics' ? 'active' : ''}" data-tab="statistics">
              Statistics
            </button>
            <button class="settings-tab ${this._settingsTab === 'efficiency' ? 'active' : ''}" data-tab="efficiency">
              Efficiency
            </button>
            <button class="settings-tab ${this._settingsTab === 'enforcement' ? 'active' : ''}" data-tab="enforcement">
              Power Enforcement
            </button>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'rooms' ? 'active' : ''}" id="tab-rooms">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Rooms</h2>
                <button class="btn btn-secondary" id="add-room-btn">
                  <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
                  Add Room
                </button>
              </div>
              <div id="rooms-list">
                ${rooms.length === 0 ? `
                  <p style="color: var(--secondary-text-color); text-align: center; padding: 20px;">
                    No rooms configured. Add a room to start monitoring.
                  </p>
                ` : rooms.map((room, i) => this._renderRoomSettings(room, i, mediaPlayers, powerSensors)).join('')}
              </div>
            </div>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'tts' ? 'active' : ''}" id="tab-tts">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">TTS Alert Settings</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px;">
                Customize how alert messages are spoken. All messages are prefixed and can be customized below.
              </p>
              <details class="settings-fold">
                <summary class="settings-fold-summary">General</summary>
                <div class="settings-fold-body">
              <div class="grid-2" style="margin-bottom: 16px;">
                <div class="form-group">
                  <label class="form-label">Language</label>
                  <select class="form-select" id="tts-language">
                    <option value="en" ${ttsSettings.language === 'en' ? 'selected' : ''}>English</option>
                    <option value="es" ${ttsSettings.language === 'es' ? 'selected' : ''}>Spanish</option>
                    <option value="fr" ${ttsSettings.language === 'fr' ? 'selected' : ''}>French</option>
                    <option value="de" ${ttsSettings.language === 'de' ? 'selected' : ''}>German</option>
                  </select>
                </div>
                <div class="form-group">
                  <label class="form-label">Min Interval Between TTS (seconds)</label>
                  <input type="number" class="form-input" id="tts-min-interval" 
                    value="${ttsSettings.min_interval_seconds ?? 3}" min="1" max="60" 
                    title="Minimum seconds between TTS sends per media player. Prevents rapid repeated alerts from hanging.">
                </div>
              </div>
              <div class="form-group" style="margin-bottom: 16px;">
                <label class="form-label">Default media player</label>
                ${this._renderEntityAutocomplete(ttsDefaultMpVal, 'media_player', 'tts', 'tts-default-mp', 'media_player.living_room')}
                <div class="tts-msg-desc" style="margin-top:6px;">Used for budget boost reminders and other announcements that are not tied to a room.</div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Message Prefix</div>
                <div class="tts-msg-desc">Added to the beginning of all alert messages</div>
                <input type="text" class="form-input" id="tts-prefix" 
                  value="${ttsSettings.prefix || TTS_DEFAULTS.prefix}" 
                  placeholder="Message from Home Energy.">
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Thresholds, budget, and overload</summary>
                <div class="settings-fold-body">
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Room Warning Message</div>
                    <div class="tts-msg-desc">Spoken when room total exceeds threshold</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'room_warn')}
                </div>
                <input type="text" class="form-input" id="tts-room-warn" 
                  value="${ttsSettings.room_warn_msg || TTS_DEFAULTS.room_warn_msg}" 
                  placeholder="{room_name} is using {watts} watts — over your {threshold} watt limit.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{watts}</code> <code>{threshold}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Outlet Warning Message</div>
                    <div class="tts-msg-desc">Spoken when outlet total exceeds threshold</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'outlet_warn')}
                </div>
                <input type="text" class="form-input" id="tts-outlet-warn" 
                  value="${ttsSettings.outlet_warn_msg || TTS_DEFAULTS.outlet_warn_msg}" 
                  placeholder="{outlet_name} in {room_name} is using {watts} watts — over the {threshold} watt limit.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{watts}</code> <code>{threshold}</code>
                </div>
              </div>

              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Budget Exceeded Message</div>
                    <div class="tts-msg-desc">Spoken when room first meets its daily kWh budget and threshold warnings become active</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'budget_exceeded')}
                </div>
                <input type="text" class="form-input" id="tts-budget-exceeded" 
                  value="${ttsSettings.budget_exceeded_msg || TTS_DEFAULTS.budget_exceeded_msg}" 
                  placeholder="{room_name} at {kwh_used} kWh — power alerts are on.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{kwh_used}</code>
                </div>
              </div>

              <div class="tts-msg-group">
                <div class="tts-msg-title">Budget boost — TTS messages</div>
                <div class="tts-msg-desc">
                  Configure boost days, time window, and repeat interval under <strong>Enforcement</strong>.
                  Set <strong>Default media player</strong> above for scheduled reminders. If Saturday and Sunday are both selected, templates may use “weekend” in <code>{period_label}</code>.
                </div>
                <div class="tts-msg-header-row" style="margin-top:4px;">
                  <div class="tts-msg-title" style="margin-bottom:0;">Scheduled reminder message</div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'budget_boost_scheduled', '#tts-budget-boost-scheduled')}
                </div>
                <textarea class="tts-msg-textarea" id="tts-budget-boost-scheduled" rows="4" spellcheck="false">${schedEsc}</textarea>
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{budget_multiplier}</code> <code>{period_label}</code></div>
                <div class="tts-msg-header-row" style="margin-top:12px;">
                  <div>
                    <div class="tts-msg-title" style="margin-bottom:4px;">Phase 1 message on boost days</div>
                    <div class="tts-msg-desc">Used when entering volume escalation on a boost day (per room). Leave empty to use the standard Phase 1 message only.</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'phase1_warn_boost_day', '#tts-phase1-boost-day')}
                </div>
                <textarea class="tts-msg-textarea" id="tts-phase1-boost-day" rows="5" spellcheck="false">${p1BoostEsc}</textarea>
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{warning_count}</code> <code>{threshold}</code> <code>{kwh_budget}</code> <code>{kwh_budget_effective}</code> <code>{budget_multiplier}</code> <code>{period_label}</code></div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Shutoff Reset Message</div>
                    <div class="tts-msg-desc">Spoken when a plug is shut off and reset due to overload</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'shutoff')}
                </div>
                <input type="text" class="form-input" id="tts-shutoff" 
                  value="${ttsSettings.shutoff_msg || TTS_DEFAULTS.shutoff_msg}" 
                  placeholder="{room_name} {outlet_name} {plug} reset after overload — reduce power use.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{plug}</code>
                </div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Stove</summary>
                <div class="settings-fold-body">
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Turned On Message</div>
                    <div class="tts-msg-desc">Spoken when stove is detected as turned on</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_on')}
                </div>
                <input type="text" class="form-input" id="tts-stove-on" 
                  value="${ttsSettings.stove_on_msg || '{prefix} Stove has been turned on'}" 
                  placeholder="{prefix} Stove has been turned on">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Turned Off Message</div>
                    <div class="tts-msg-desc">Spoken when stove is detected as turned off</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_off')}
                </div>
                <input type="text" class="form-input" id="tts-stove-off" 
                  value="${ttsSettings.stove_off_msg || '{prefix} Stove has been turned off'}" 
                  placeholder="{prefix} Stove has been turned off">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Timer Started Message</div>
                    <div class="tts-msg-desc">Spoken when stove is on and no one is in the kitchen (timer just started)</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_timer_started')}
                </div>
                <input type="text" class="form-input" id="tts-stove-timer-started" 
                  value="${ttsSettings.stove_timer_started_msg || '{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.'}" 
                  placeholder="{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{cooking_time_minutes}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove timer — progress announcements</div>
                    <div class="tts-msg-desc">Spoken periodically during the long unattended phase (before the final countdown). Interval is set per stove under room settings.</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_timer_progress')}
                </div>
                <textarea class="tts-msg-textarea" id="tts-stove-timer-progress" rows="3" spellcheck="false">${stoveProgressEsc}</textarea>
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{minutes_remaining}</code> <code>{seconds_remaining}</code></div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Cooking-Time Warning</div>
                    <div class="tts-msg-desc">Spoken when stove has been on for the configured cooking time with no presence detected</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_15min_warn')}
                </div>
                <input type="text" class="form-input" id="tts-stove-15min" 
                  value="${ttsSettings.stove_15min_warn_msg || '{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns'}" 
                  placeholder="{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{cooking_time_minutes}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Final Warning</div>
                    <div class="tts-msg-desc">Spoken when final countdown begins before auto-shutoff</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_30sec_warn')}
                </div>
                <input type="text" class="form-input" id="tts-stove-30sec" 
                  value="${ttsSettings.stove_30sec_warn_msg || '{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen'}" 
                  placeholder="{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Stove Auto-Shutoff Message</div>
                    <div class="tts-msg-desc">Spoken when stove is automatically turned off for safety</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'stove_auto_off')}
                </div>
                <input type="text" class="form-input" id="tts-stove-auto-off" 
                  value="${ttsSettings.stove_auto_off_msg || '{prefix} Stove has been automatically turned off for safety'}" 
                  placeholder="{prefix} Stove has been automatically turned off for safety">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Vent and heater automation</summary>
                <div class="settings-fold-body">
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
                Spoken when presence or temperature automation turns on the vent or wall heater switch from the appliance card. Uses each room's media player and volume. Heater TTS is off by default.
              </p>
              <div class="form-group" style="margin-bottom: 12px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-vent-automation-enabled" ${ttsSettings.vent_automation_tts_enabled ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Speak when vent automation turns the fan on</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Vent automation — on message</div>
                <input type="text" class="form-input" id="tts-vent-automation-msg"
                  value="${(ttsSettings.vent_automation_on_msg || TTS_DEFAULTS.vent_automation_on_msg).replace(/"/g, '&quot;')}" />
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code></div>
              </div>
              <div class="form-group" style="margin: 16px 0 12px 0;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-heater-automation-enabled" ${ttsSettings.heater_automation_tts_enabled ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Speak when heater automation turns the heater on</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Heater automation — on message</div>
                <input type="text" class="form-input" id="tts-heater-automation-msg"
                  value="${(ttsSettings.heater_automation_on_msg || TTS_DEFAULTS.heater_automation_on_msg).replace(/"/g, '&quot;')}" />
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{threshold}</code> <code>{temperature}</code> (spoken whole numbers)</div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Power enforcement and daily kWh</summary>
                <div class="settings-fold-body">
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 1 Warning (Volume Escalation)</div>
                    <div class="tts-msg-desc">Spoken when warning count triggers volume escalation phase</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'phase1_warn')}
                </div>
                <input type="text" class="form-input" id="tts-phase1-warn" 
                  value="${ttsSettings.phase1_warn_msg || TTS_DEFAULTS.phase1_warn_msg}" 
                  placeholder="{room_name} has exceeded electricity threshold {warning_count} times. Volume will rise until under {threshold} watts.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{warning_count}</code> <code>{threshold}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 2 Warning (Power Cycling)</div>
                    <div class="tts-msg-desc">Spoken before power cycle (outlets will be cycled)</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'phase2_warn')}
                </div>
                <input type="text" class="form-input" id="tts-phase2-warn" 
                  value="${ttsSettings.phase2_warn_msg || TTS_DEFAULTS.phase2_warn_msg}" 
                  placeholder="{room_name} has exceeded electricity threshold {warning_count} times. Cycling outlets now.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{warning_count}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 2 After Message</div>
                    <div class="tts-msg-desc">Spoken after power cycle completes (adhere to warning)</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'phase2_after')}
                </div>
                <input type="text" class="form-input" id="tts-phase2-after" 
                  value="${ttsSettings.phase2_after_msg || TTS_DEFAULTS.phase2_after_msg}" 
                  placeholder="Cycle complete in {room_name}. Stay under limit.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 2 — Mini-Split Warning</div>
                    <div class="tts-msg-desc">When a qualifying mini-split is cut first (room overload attributed to that unit). Uses spoken cardinals for {restore_delay} and {room_threshold}.</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'minisplit_phase2_warn')}
                </div>
                <input type="text" class="form-input" id="tts-minisplit-phase2-warn"
                  value="${(ttsSettings.minisplit_phase2_warn_msg ?? TTS_DEFAULTS.minisplit_phase2_warn_msg).replace(/"/g, '&quot;')}"
                  placeholder="Mini-split enforcement warning...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{warning_count}</code> <code>{restore_delay}</code> <code>{room_threshold}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 2 — Mini-Split After Message</div>
                    <div class="tts-msg-desc">After minimum off time and any excluded outlet cycle</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'minisplit_phase2_after')}
                </div>
                <input type="text" class="form-input" id="tts-minisplit-phase2-after"
                  value="${(ttsSettings.minisplit_phase2_after_msg ?? TTS_DEFAULTS.minisplit_phase2_after_msg).replace(/"/g, '&quot;')}"
                  placeholder="Mini-split after message...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{room_threshold}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase 2 — Mini-Split Restore (optional)</div>
                    <div class="tts-msg-desc">When room is back under threshold and power is restored. Leave empty for silent restore.</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'minisplit_phase2_restore')}
                </div>
                <input type="text" class="form-input" id="tts-minisplit-phase2-restore"
                  value="${(ttsSettings.minisplit_phase2_restore_msg ?? TTS_DEFAULTS.minisplit_phase2_restore_msg).replace(/"/g, '&quot;')}"
                  placeholder="Restore announcement...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{room_threshold}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Phase Reset Message</div>
                    <div class="tts-msg-desc">Spoken when room maintains power below threshold for reset time</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'phase_reset')}
                </div>
                <input type="text" class="form-input" id="tts-phase-reset" 
                  value="${ttsSettings.phase_reset_msg || TTS_DEFAULTS.phase_reset_msg}" 
                  placeholder="{room_name} under limit — enforcement reset.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Room kWh Warning</div>
                    <div class="tts-msg-desc">Spoken when room exceeds daily kWh interval</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'room_kwh_warn')}
                </div>
                <input type="text" class="form-input" id="tts-room-kwh-warn" 
                  value="${ttsSettings.room_kwh_warn_msg || TTS_DEFAULTS.room_kwh_warn_msg}" 
                  placeholder="{room_name} used {kwh_limit} kWh today ({percentage}% of home) — reduce use.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{kwh_limit}</code> <code>{percentage}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-header-row">
                  <div>
                    <div class="tts-msg-title">Home kWh Warning</div>
                    <div class="tts-msg-desc">Spoken when home exceeds daily kWh limit</div>
                  </div>
                  ${this._ttsLineEnableHtml(ttsSettings, 'home_kwh_warn')}
                </div>
                <input type="text" class="form-input" id="tts-home-kwh-warn" 
                  value="${ttsSettings.home_kwh_warn_msg || TTS_DEFAULTS.home_kwh_warn_msg}" 
                  placeholder="Home over {kwh_limit} kWh today — reduce consumption.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{kwh_limit}</code></div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Zone Health TTS</summary>
                <div class="settings-fold-body">
                  <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
                    Customize the TTS and push notification messages for zone health alerts. Use <code>{name}</code> for the person's friendly name.
                  </p>
                  <div class="tts-msg-group" style="margin-bottom: 12px;">
                    <div class="tts-msg-title">First alert / Push notification message</div>
                    <input type="text" class="form-input" id="zone-health-notification-msg"
                      value="${(ttsSettings.zone_health_notification_msg || "Hi {name}, your Home Assistant Companion app location doesn't appear to be set up correctly. Zone-based presence isn't working.").replace(/"/g, '&quot;')}"
                      placeholder="Hi {name}, your zone tracking...">
                    <div class="tts-var-help">Variables: <code>{name}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Repeat reminder TTS message</div>
                    <input type="text" class="form-input" id="zone-health-reminder-tts-msg"
                      value="${(ttsSettings.zone_health_reminder_tts_msg || "{name}, your zone-based location setup needs attention. Please check your Companion app settings.").replace(/"/g, '&quot;')}"
                      placeholder="{name}, your zone-based location...">
                    <div class="tts-var-help">Variables: <code>{name}</code></div>
                  </div>
                </div>
              </details>
            </div>
          </div>

          <div class="settings-tab-content ${this._settingsTab === 'notifications' ? 'active' : ''}" id="tab-notifications">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Push Notifications</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px;">
                Assign a <strong>Presence person</strong> per room to enable mobile alerts. <strong>Personal</strong> alerts (room budget exceeded, enforcement phase changes, presence-based AC off/on) go only to that room’s person. <strong>Universal</strong> alerts (optional below) go to <em>every</em> person who is set as Presence person on <em>any</em> room when a monitored switch changes from the dashboard, Home Assistant UI, or an automation. Use <strong>Notification title</strong> as <code>{notification_title}</code> in title templates (separate from the TTS message prefix). Delivery uses each person’s <code>notify.mobile_app_*</code> target from devices linked under <strong>Settings → People</strong> (e.g. <code>Brandon’s Iphone</code> → <code>notify.mobile_app_brandons_iphone</code>).
              </p>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Global</summary>
                <div class="settings-fold-body">
              <div class="form-group" style="margin-bottom: 16px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notifications-enabled" ${ttsSettings.notifications_enabled ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label"><strong>Enable push notifications</strong></span>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Notification title</div>
                <div class="tts-msg-desc">Shown at the start of push notification titles via <code>{notification_title}</code> (independent of TTS message prefix).</div>
                <input type="text" class="form-input" id="notify-notification-title"
                  value="${(ttsSettings.notification_title || TTS_DEFAULTS.notification_title).replace(/"/g, '&quot;')}"
                  placeholder="Home Energy">
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Budget exceeded</summary>
                <div class="settings-fold-body">
              <div class="form-group" style="margin-bottom: 12px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-room-budget-hit" ${ttsSettings.notify_room_budget_hit !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when room budget is exceeded</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Title</div>
                <input type="text" class="form-input" id="notify-budget-hit-title"
                  value="${(ttsSettings.notify_budget_hit_title || TTS_DEFAULTS.notify_budget_hit_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Budget Exceeded">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Message</div>
                <input type="text" class="form-input" id="notify-budget-hit-msg"
                  value="${(ttsSettings.notify_budget_hit_msg || TTS_DEFAULTS.notify_budget_hit_msg).replace(/"/g, '&quot;')}"
                  placeholder="{room_name} has exceeded its daily budget of {kwh_budget} kWh (used {kwh_used} kWh).">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{kwh_budget}</code> <code>{kwh_used}</code></div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Enforcement phase changes</summary>
                <div class="settings-fold-body">
              <div class="form-group" style="margin-bottom: 12px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-enforcement-phase-change" ${ttsSettings.notify_enforcement_phase_change !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify on enforcement phase changes</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 1 Title</div>
                <input type="text" class="form-input" id="notify-enforcement-phase1-title"
                  value="${(ttsSettings.notify_enforcement_phase1_title || TTS_DEFAULTS.notify_enforcement_phase1_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Enforcement Phase 1">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 1 Message</div>
                <input type="text" class="form-input" id="notify-enforcement-phase1-msg"
                  value="${(ttsSettings.notify_enforcement_phase1_msg || TTS_DEFAULTS.notify_enforcement_phase1_msg).replace(/"/g, '&quot;')}"
                  placeholder="{room_name} has entered enforcement phase 1 (volume escalation). Please reduce power usage.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 2 Title</div>
                <input type="text" class="form-input" id="notify-enforcement-phase2-title"
                  value="${(ttsSettings.notify_enforcement_phase2_title || TTS_DEFAULTS.notify_enforcement_phase2_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Enforcement Phase 2">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 2 Message</div>
                <input type="text" class="form-input" id="notify-enforcement-phase2-msg"
                  value="${(ttsSettings.notify_enforcement_phase2_msg || TTS_DEFAULTS.notify_enforcement_phase2_msg).replace(/"/g, '&quot;')}"
                  placeholder="{room_name} has entered enforcement phase 2 (power cycling). Please reduce power usage.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code></div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Air conditioner presence</summary>
                <div class="settings-fold-body">
              <div class="form-group" style="margin-bottom: 12px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-ac-auto-off" ${ttsSettings.notify_ac_auto_off !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when air conditioner auto-off (presence)</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">AC Auto-Off Title</div>
                <input type="text" class="form-input" id="notify-ac-auto-off-title"
                  value="${(ttsSettings.notify_ac_auto_off_title || TTS_DEFAULTS.notify_ac_auto_off_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Air Conditioner Off">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">AC Auto-Off Message</div>
                <input type="text" class="form-input" id="notify-ac-auto-off-msg"
                  value="${(ttsSettings.notify_ac_auto_off_msg || TTS_DEFAULTS.notify_ac_auto_off_msg).replace(/"/g, '&quot;')}"
                  placeholder="{outlet_name} was turned off because {person_name} left the monitored zone.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{outlet_name}</code> <code>{person_name}</code> <code>{person}</code> <code>{room_name}</code></div>
              </div>
              <div class="form-group" style="margin: 16px 0 12px 0;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-ac-auto-on" ${ttsSettings.notify_ac_auto_on !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when air conditioner restored (presence)</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">AC Auto-On Title</div>
                <input type="text" class="form-input" id="notify-ac-auto-on-title"
                  value="${(ttsSettings.notify_ac_auto_on_title || TTS_DEFAULTS.notify_ac_auto_on_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Air Conditioner On">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">AC Auto-On Message</div>
                <input type="text" class="form-input" id="notify-ac-auto-on-msg"
                  value="${(ttsSettings.notify_ac_auto_on_msg || TTS_DEFAULTS.notify_ac_auto_on_msg).replace(/"/g, '&quot;')}"
                  placeholder="{outlet_name} was turned back on because {person_name} is nearby.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{outlet_name}</code> <code>{person_name}</code> <code>{person}</code> <code>{room_name}</code></div>
              </div>
                </div>
              </details>
              <details class="settings-fold">
                <summary class="settings-fold-summary">Appliance toggles, zone health, and templates</summary>
                <div class="settings-fold-body">
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
                Control which appliance on/off changes trigger notifications.
              </p>
              <div class="form-group" style="margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-zone-health-check" ${ttsSettings.zone_health_check_enabled !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Zone tracking health check (TTS + push when setup looks wrong)</span>
                </div>
                <p style="color: var(--secondary-text-color); font-size: 10px; margin: 4px 0 0 0;">Settings for this feature are on the <strong>Zone Health</strong> tab.</p>
              </div>
              <div class="form-group" style="margin-bottom: 8px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-person-toggle" ${ttsSettings.notify_person_toggle !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when a person toggles an appliance</span>
                </div>
              </div>
              <div class="form-group" style="margin-bottom: 8px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-integration-auto" ${ttsSettings.notify_integration_auto !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when this integration's automations toggle an appliance</span>
                </div>
              </div>
              <!-- Sub-toggles for integration automations -->
              <div id="integration-sub-toggles" style="margin-left: 32px; margin-bottom: 12px; ${ttsSettings.notify_integration_auto === false ? 'display: none;' : ''}">
                <div class="form-group" style="margin-bottom: 6px;">
                  <div class="toggle-row" style="padding: 4px 0;">
                    <label class="toggle-switch" style="transform: scale(0.85);">
                      <input type="checkbox" id="tts-notify-heater-auto" ${ttsSettings.notify_heater_auto !== false ? 'checked' : ''} />
                      <span class="toggle-slider"></span>
                    </label>
                    <span class="toggle-label" style="font-size: 12px;">Heater auto on/off</span>
                  </div>
                </div>
                <div class="form-group" style="margin-bottom: 6px;">
                  <div class="toggle-row" style="padding: 4px 0;">
                    <label class="toggle-switch" style="transform: scale(0.85);">
                      <input type="checkbox" id="tts-notify-vent-auto" ${ttsSettings.notify_vent_auto !== false ? 'checked' : ''} />
                      <span class="toggle-slider"></span>
                    </label>
                    <span class="toggle-label" style="font-size: 12px;">Vent auto on/off</span>
                  </div>
                </div>
                <p class="tts-msg-desc" style="margin: 8px 0 0 0; font-size: 11px;">AC presence on/off notifications use the toggles in <strong>Air Conditioner Presence Notifications</strong> above (same settings; not duplicated here).</p>
              </div>
              <div class="form-group" style="margin-bottom: 12px;">
                <div class="toggle-row">
                  <label class="toggle-switch">
                    <input type="checkbox" id="tts-notify-external-auto" ${ttsSettings.notify_external_auto !== false ? 'checked' : ''} />
                    <span class="toggle-slider"></span>
                  </label>
                  <span class="toggle-label">Notify when external automations toggle an appliance</span>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Person/External Toggle Title</div>
                <input type="text" class="form-input" id="notify-toggle-title"
                  value="${(ttsSettings.notify_toggle_title || TTS_DEFAULTS.notify_toggle_title).replace(/"/g, '&quot;')}"
                  placeholder="{notification_title} Appliance Toggled">
                <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Person/External Toggle Message</div>
                <input type="text" class="form-input" id="notify-toggle-msg"
                  value="${(ttsSettings.notify_toggle_msg || TTS_DEFAULTS.notify_toggle_msg).replace(/"/g, '&quot;')}"
                  placeholder="{user_name} turned {action} {outlet_name} in {room_name}.">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{user_name}</code> <code>{action}</code></div>
              </div>

              <!-- Heater/Vent Auto Messages -->
              <details style="margin-top: 16px;">
                <summary style="cursor: pointer; font-weight: 500; color: var(--primary-text-color); margin-bottom: 8px;">Integration Automation Messages</summary>
                <div style="padding-left: 12px; border-left: 2px solid var(--divider-color); margin-top: 8px;">
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Heater Auto-On Title</div>
                    <input type="text" class="form-input" id="notify-heater-auto-on-title"
                      value="${(ttsSettings.notify_heater_auto_on_title || TTS_DEFAULTS.notify_heater_auto_on_title).replace(/"/g, '&quot;')}"
                      placeholder="{notification_title} Heater On">
                    <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Heater Auto-On Message</div>
                    <input type="text" class="form-input" id="notify-heater-auto-on-msg"
                      value="${(ttsSettings.notify_heater_auto_on_msg || TTS_DEFAULTS.notify_heater_auto_on_msg).replace(/"/g, '&quot;')}"
                      placeholder="{room_name} is {temperature}°, turning on {outlet_name}.">
                    <div class="tts-var-help">Variables: <code>{room_name}</code> <code>{outlet_name}</code> <code>{temperature}</code> <code>{threshold}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Heater Auto-Off Title</div>
                    <input type="text" class="form-input" id="notify-heater-auto-off-title"
                      value="${(ttsSettings.notify_heater_auto_off_title || TTS_DEFAULTS.notify_heater_auto_off_title).replace(/"/g, '&quot;')}"
                      placeholder="{notification_title} Heater Off">
                    <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Heater Auto-Off Message</div>
                    <input type="text" class="form-input" id="notify-heater-auto-off-msg"
                      value="${(ttsSettings.notify_heater_auto_off_msg || TTS_DEFAULTS.notify_heater_auto_off_msg).replace(/"/g, '&quot;')}"
                      placeholder="{room_name} reached {temperature}°, turning off {outlet_name}.">
                    <div class="tts-var-help">Variables: <code>{room_name}</code> <code>{outlet_name}</code> <code>{temperature}</code> <code>{comfort}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Vent Auto-On Title</div>
                    <input type="text" class="form-input" id="notify-vent-auto-on-title"
                      value="${(ttsSettings.notify_vent_auto_on_title || TTS_DEFAULTS.notify_vent_auto_on_title).replace(/"/g, '&quot;')}"
                      placeholder="{notification_title} Vent On">
                    <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Vent Auto-On Message</div>
                    <input type="text" class="form-input" id="notify-vent-auto-on-msg"
                      value="${(ttsSettings.notify_vent_auto_on_msg || TTS_DEFAULTS.notify_vent_auto_on_msg).replace(/"/g, '&quot;')}"
                      placeholder="Motion detected in {room_name}, turning on {outlet_name}.">
                    <div class="tts-var-help">Variables: <code>{room_name}</code> <code>{outlet_name}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Vent Auto-Off Title</div>
                    <input type="text" class="form-input" id="notify-vent-auto-off-title"
                      value="${(ttsSettings.notify_vent_auto_off_title || TTS_DEFAULTS.notify_vent_auto_off_title).replace(/"/g, '&quot;')}"
                      placeholder="{notification_title} Vent Off">
                    <div class="tts-var-help">Variables: <code>{notification_title}</code></div>
                  </div>
                  <div class="tts-msg-group">
                    <div class="tts-msg-title">Vent Auto-Off Message</div>
                    <input type="text" class="form-input" id="notify-vent-auto-off-msg"
                      value="${(ttsSettings.notify_vent_auto_off_msg || TTS_DEFAULTS.notify_vent_auto_off_msg).replace(/"/g, '&quot;')}"
                      placeholder="No motion in {room_name}, turning off {outlet_name}.">
                    <div class="tts-var-help">Variables: <code>{room_name}</code> <code>{outlet_name}</code></div>
                  </div>
                </div>
              </details>
                </div>
              </details>

              <details class="settings-fold">
                <summary class="settings-fold-summary">Test notification</summary>
                <div class="settings-fold-body">
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
                Send a test notification to verify your setup. Select a person and notification type, then click Send Test.
              </p>
              <div class="grid-2" style="margin-bottom: 12px;">
                <div class="form-group">
                  <label class="form-label">Target Person</label>
                  <select class="form-select" id="notify-test-person">
                    <option value="">Select a person...</option>
                    ${(Array.isArray(this._entities?.persons) ? this._entities.persons : [])
                      .filter(p => (p.entity_id || '').startsWith('person.'))
                      .map(p => `<option value="${(p.entity_id || '').replace(/"/g, '&quot;')}">${(p.friendly_name || p.entity_id || '').replace(/</g, '&lt;')}</option>`)
                      .join('')}
                  </select>
                </div>
                <div class="form-group">
                  <label class="form-label">Notification Type</label>
                  <select class="form-select" id="notify-test-type">
                    <option value="budget_hit">Budget Exceeded</option>
                    <option value="enforcement_phase1">Enforcement Phase 1</option>
                    <option value="enforcement_phase2">Enforcement Phase 2</option>
                    <option value="ac_auto_off">AC Auto-Off</option>
                    <option value="ac_auto_on">AC Auto-On</option>
                    <option value="heater_auto_on">Heater Auto-On</option>
                    <option value="heater_auto_off">Heater Auto-Off</option>
                    <option value="vent_auto_on">Vent Auto-On</option>
                    <option value="vent_auto_off">Vent Auto-Off</option>
                    <option value="manual_toggle">Manual Toggle</option>
                  </select>
                </div>
              </div>
              <button type="button" class="btn btn-secondary" id="notify-send-test" style="margin-top: 8px;">
                Send Test Notification
              </button>
                </div>
              </details>
            </div>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'zone-health' ? 'active' : ''}" id="tab-zone-health">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Zone Health Tracking</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
                Monitor zone-based presence for each room’s <strong>Presence person</strong>. Snapshots from recorder pulls are saved under <code>config/data/smart_dashboards_zone_health.json</code>.
                For each person, <strong>no TTS or push alerts</strong> run until <strong>Home Assistant has been up for 10 minutes</strong> and a <strong>warm-up period</strong> (same length as the history window, 1–3 days) has finished.
                After warm-up, <strong>healthy</strong> means <code>home</code>, <code>nearby</code>, and <code>away</code> all appear in that saved snapshot window. Live <code>person.*</code> and recorder columns below are for reference only.
              </p>
              <details class="settings-fold" style="margin-bottom: 16px;">
                <summary class="settings-fold-summary">Zone health settings</summary>
                <div class="settings-fold-body">
                  <div class="form-group" style="margin-bottom: 12px;">
                    <label class="form-label">Check history window</label>
                    <select class="form-input" id="zone-health-history-days" style="max-width: 200px;">
                      <option value="1" ${(() => { let d = Number(ttsSettings.zone_health_history_days); if (!Number.isFinite(d) || d < 1 || d > 3) d = 3; return d === 1 ? 'selected' : ''; })()}>1 day</option>
                      <option value="2" ${(() => { let d = Number(ttsSettings.zone_health_history_days); if (!Number.isFinite(d) || d < 1 || d > 3) d = 3; return d === 2 ? 'selected' : ''; })()}>2 days</option>
                      <option value="3" ${(() => { let d = Number(ttsSettings.zone_health_history_days); if (!Number.isFinite(d) || d < 1 || d > 3) d = 3; return d === 3 ? 'selected' : ''; })()}>3 days</option>
                    </select>
                    <div class="tts-msg-desc" style="margin-top: 4px;">Alert if <strong>home</strong>, <strong>nearby</strong>, and <strong>away</strong> are not all seen in <strong>recorder history</strong> on the person’s linked <strong>device_tracker</strong> entities within this window.</div>
                  </div>
                  <div class="form-group" style="margin-bottom: 8px;">
                    <label class="form-label">Reminder frequency (hours)</label>
                    <input type="number" class="form-input" id="zone-health-reminder-hours"
                      value="${ttsSettings.zone_health_reminder_hours ?? 1}" min="1" max="24" style="width: 80px;"
                      title="How often to send repeat TTS and push for unresolved zone health issues">
                    <div class="tts-msg-desc" style="margin-top: 4px;">Hours between repeat TTS and push reminders (1–24). First alert is immediate.</div>
                  </div>
                  <p style="color: var(--secondary-text-color); font-size: 10px; font-style: italic; margin: 0;">
                    Enable/disable the health check on the <strong>Notifications</strong> tab. Message templates: <strong>TTS Settings</strong> tab → Zone Health TTS.
                  </p>
                </div>
              </details>
              <div id="zone-health-content">
                <p style="color: var(--secondary-text-color); font-size: 12px;">Loading zone health status...</p>
              </div>
              <button type="button" class="btn btn-secondary" id="zone-health-refresh" style="margin-top: 12px;">
                Refresh status (recheck recorder + device trackers)
              </button>
            </div>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'statistics' ? 'active' : ''}" id="tab-statistics">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Statistics Settings</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px;">
                Configure Opower/utility sensors for billing dates, usage, and cost. Statistics are computed from daily totals.
              </p>
              
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Opower / Utility Sensors</div>
                <div class="tts-msg-desc">Sensor entities that provide billing and usage data (YYYY-MM-DD for dates, kWh for usage)</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Billing Start Date</label>
                    ${this._renderEntityAutocomplete(statsSettings.billing_start_sensor || '', 'sensor', 'stats', 'stats-billing-start', 'sensor.billing_start')}
                  </div>
                  <div class="form-group">
                    <label class="form-label">Billing End Date</label>
                    ${this._renderEntityAutocomplete(statsSettings.billing_end_sensor || '', 'sensor', 'stats', 'stats-billing-end', 'sensor.billing_end')}
                  </div>
                  <div class="form-group">
                    <label class="form-label">Current Usage (kWh)</label>
                    ${this._renderEntityAutocomplete(statsSettings.current_usage_sensor || '', 'sensor', 'stats', 'stats-current-usage', 'sensor.current_usage')}
                  </div>
                  <div class="form-group">
                    <label class="form-label">Projected Usage (kWh)</label>
                    ${this._renderEntityAutocomplete(statsSettings.projected_usage_sensor || '', 'sensor', 'stats', 'stats-projected-usage', 'sensor.projected_usage')}
                  </div>
                  <div class="form-group">
                    <label class="form-label">kWh Cost</label>
                    ${this._renderEntityAutocomplete(statsSettings.kwh_cost_sensor || '', 'cost_helper', 'stats', 'stats-kwh-cost', 'input_text.kwh_cost')}
                  </div>
                  <div class="form-group" style="grid-column: 1 / -1;">
                    <label class="form-label" for="stats-refresh-seconds">Statistics refresh rate (seconds)</label>
                    <input type="number" id="stats-refresh-seconds" class="form-input" min="15" max="600" step="1"
                      value="${(() => {
                        const r = statsSettings.statistics_refresh_seconds;
                        const n = typeof r === 'number' ? r : parseInt(String(r ?? ''), 10);
                        const sec = Number.isFinite(n) ? Math.max(15, Math.min(600, n)) : 60;
                        return sec;
                      })()}"
                      style="max-width: 140px;">
                    <p style="color: var(--secondary-text-color); font-size: 10px; margin: 8px 0 0;">
                      This interval drives background statistics computation in Home Assistant (recorder-heavy work) and refreshes the Statistics view while it is open. Range 15–600; default 60.
                    </p>
                  </div>
                </div>
              </div>
              <div style="margin-top: 16px;">
                <button type="button" class="btn btn-secondary" id="stat-refresh-cache" title="Clear cache and recalculate all statistics from Home Assistant recorder">
                  Refresh Statistics
                </button>
                <p style="color: var(--secondary-text-color); font-size: 10px; margin: 8px 0 0;">
                  Clears the statistics cache and forces a full recalculation from Home Assistant's recorder. Use this after changing sensor settings.
                </p>
              </div>
            </div>
          </div>

          <div class="settings-tab-content ${this._settingsTab === 'efficiency' ? 'active' : ''}" id="tab-efficiency">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Room efficiency ratings</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px;">
                Tune how the five efficiency pillars are scored (same formulas as the reference doc). Changes apply on the next recompute (hourly or when the panel loads ratings).
              </p>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Windows and compliance</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label" for="eff-history-window-days">Daily history window (days)</label>
                    <input type="number" id="eff-history-window-days" class="form-input" min="1" max="90" step="1"
                      value="${effSettings.history_window_days ?? 14}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-engagement-lookback">Engagement lookback (days)</label>
                    <input type="number" id="eff-engagement-lookback" class="form-input" min="1" max="30" step="1"
                      value="${effSettings.engagement_lookback_days ?? 7}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-compliance-tol">Compliance budget multiplier</label>
                    <input type="number" id="eff-compliance-tol" class="form-input" min="1" max="1.5" step="0.01"
                      value="${effSettings.compliance_tolerance ?? 1.0}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-warning-points">Warning points lost per event</label>
                    <input type="number" id="eff-warning-points" class="form-input" min="0.25" max="25" step="0.25"
                      value="${effSettings.warning_points_per_event ?? 5.5}">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Consumption and load</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label" for="eff-peer-mult">Consumption peer divisor multiplier</label>
                    <input type="number" id="eff-peer-mult" class="form-input" min="0.5" max="5" step="0.1"
                      value="${effSettings.consumption_peer_multiplier ?? 1.5}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-load-high-w">Load “high” threshold (watts per minute)</label>
                    <input type="number" id="eff-load-high-w" class="form-input" min="1" max="5000" step="1"
                      value="${effSettings.load_high_watts ?? 100}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-load-penalty">Load penalty per high-load hour</label>
                    <input type="number" id="eff-load-penalty" class="form-input" min="0" max="50" step="0.5"
                      value="${effSettings.load_penalty_per_high_hour ?? 11}">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Engagement (dashboard visits)</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label" for="eff-eng-distinct-hours">Distinct hours target (per day)</label>
                    <input type="number" id="eff-eng-distinct-hours" class="form-input" min="1" max="24" step="1"
                      value="${effSettings.engagement_distinct_hours_target ?? 14}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-eng-hours-weight">Hours component weight (0–100)</label>
                    <input type="number" id="eff-eng-hours-weight" class="form-input" min="0" max="100" step="1"
                      value="${effSettings.engagement_hours_weight ?? 70}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-eng-visits-weight">Visits component weight (0–100)</label>
                    <input type="number" id="eff-eng-visits-weight" class="form-input" min="0" max="100" step="1"
                      value="${effSettings.engagement_visits_weight ?? 30}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-eng-daily-norm">Visits daily norm (score scale)</label>
                    <input type="number" id="eff-eng-daily-norm" class="form-input" min="1" max="48" step="1"
                      value="${effSettings.engagement_visits_daily_norm ?? 3}">
                  </div>
                  <div class="form-group">
                    <label class="form-label" for="eff-eng-max-hour">Max visits counted per clock hour</label>
                    <input type="number" id="eff-eng-max-hour" class="form-input" min="1" max="10" step="1"
                      value="${effSettings.engagement_max_visits_per_hour ?? 2}">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Daily digest (push)</div>
                <p style="color: var(--secondary-text-color); font-size: 10px; margin: 0 0 10px;">
                  Sends once per day at the chosen local time for each room that has a <strong>Presence person</strong> (<code>person.*</code>).
                  Requires <strong>Notifications</strong> enabled and a mobile notify target for that person. Uses saved rating scores (engagement is per assigned person’s linked HA user).
                </p>
                <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer;">
                  <input type="checkbox" id="eff-digest-enabled" ${effSettings.efficiency_digest_enabled ? 'checked' : ''} style="width: 18px; height: 18px;">
                  <span>Enable daily efficiency digest</span>
                </label>
                <div class="form-group" style="margin-bottom: 12px;">
                  <label class="form-label" for="eff-digest-time">Send time (local)</label>
                  <input type="time" id="eff-digest-time" class="form-input" style="max-width: 160px;"
                    value="${String(effSettings.efficiency_digest_time || '08:00').slice(0, 5)}">
                </div>
                <div class="tts-msg-group" style="margin-bottom: 10px;">
                  <div class="tts-msg-title">Digest title template</div>
                  <textarea class="tts-msg-textarea" id="eff-digest-title" rows="2">${this._escapeForSettingsTextarea(
                    effSettings.efficiency_digest_title || EFFICIENCY_UI_DEFAULTS.efficiency_digest_title,
                  )}</textarea>
                  <div class="tts-var-help">Variables: <code>{notification_title}</code> <code>{room_name}</code> <code>{average}</code> <code>{stars}</code> <code>{compliance}</code> <code>{warning}</code> <code>{consumption}</code> <code>{load}</code> <code>{engagement}</code> <code>{worst_pillar}</code> <code>{worst_pillar_tip}</code></div>
                </div>
                <div class="tts-msg-group" style="margin-bottom: 10px;">
                  <div class="tts-msg-title">Digest message template</div>
                  <textarea class="tts-msg-textarea" id="eff-digest-message" rows="4">${this._escapeForSettingsTextarea(
                    effSettings.efficiency_digest_message || EFFICIENCY_UI_DEFAULTS.efficiency_digest_message,
                  )}</textarea>
                  <div class="tts-var-help">Same as title; <code>{worst_pillar_tip}</code> is a short line for the lowest-scoring pillar (excluding N/A / no-data pillars).</div>
                </div>
                <div class="grid-2" style="margin-bottom: 12px;">
                  <div class="form-group">
                    <label class="form-label">Test target person</label>
                    <select class="form-select" id="eff-digest-test-person">
                      <option value="">Select a person...</option>
                      ${(Array.isArray(this._entities?.persons) ? this._entities.persons : [])
                        .filter((p) => (p.entity_id || '').startsWith('person.'))
                        .map(
                          (p) =>
                            `<option value="${(p.entity_id || '').replace(/"/g, '&quot;')}">${(p.friendly_name || p.entity_id || '').replace(/</g, '&lt;')}</option>`,
                        )
                        .join('')}
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Room (optional)</label>
                    <select class="form-select" id="eff-digest-test-room">
                      <option value="">First room for this person</option>
                      ${rooms
                        .filter((r) => (r.presence_person_entity || '').trim().startsWith('person.'))
                        .map((r) => {
                          const rid = this._canonicalRoomId(r);
                          const nm = String(r.name || rid).replace(/</g, '&lt;');
                          return `<option value="${String(rid).replace(/"/g, '&quot;')}">${nm}</option>`;
                        })
                        .join('')}
                    </select>
                  </div>
                </div>
                <button type="button" class="btn btn-secondary" id="eff-digest-send-test">Send digest test</button>
                <p style="color: var(--secondary-text-color); font-size: 10px; margin: 8px 0 0;">
                  Sends one notification using current templates and saved ratings (does not mark the daily digest as sent).
                </p>
              </div>
            </div>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'enforcement' ? 'active' : ''}" id="tab-enforcement">
            <div class="card">
              <div class="card-header">
                <h2 class="card-title">Power Enforcement</h2>
              </div>
              <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px;">
                When enabled, repeated threshold warnings trigger escalating enforcement actions (volume escalation, power cycling).
              </p>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                  <input type="checkbox" id="pe-enabled" ${pe.enabled ? 'checked' : ''} style="width: 18px; height: 18px;">
                  <span>Enable Power Enforcement</span>
                </label>
                <span style="color: var(--secondary-text-color); font-size: 10px;">
                  When enabled, repeated threshold warnings trigger escalating enforcement actions.
                </span>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Phase 1: Volume Escalation</div>
                <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer;">
                  <input type="checkbox" id="pe-phase1-enabled" ${pe.phase1_enabled !== false ? 'checked' : ''} style="width: 18px; height: 18px;">
                  <span>Enable Phase 1</span>
                </label>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Warning Count to Trigger</label>
                    <input type="number" class="form-input" id="pe-phase1-count" value="${pe.phase1_warning_count || 20}" min="1" max="100">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Time Window (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase1-window" value="${pe.phase1_time_window_minutes || 60}" min="1" max="120">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Volume Increment (%)</label>
                    <input type="number" class="form-input" id="pe-phase1-vol-inc" value="${pe.phase1_volume_increment || 2}" min="1" max="20">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Reset After (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase1-reset" value="${pe.phase1_reset_minutes || 60}" min="1" max="180">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Phase 2: Power Cycling</div>
                <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer;">
                  <input type="checkbox" id="pe-phase2-enabled" ${pe.phase2_enabled !== false ? 'checked' : ''} style="width: 18px; height: 18px;">
                  <span>Enable Phase 2</span>
                </label>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Warning Count to Trigger</label>
                    <input type="number" class="form-input" id="pe-phase2-count" value="${pe.phase2_warning_count ?? 10}" min="1" max="200">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Time Window (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase2-window" value="${pe.phase2_time_window_minutes ?? 10}" min="1" max="120">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Cycle Delay (seconds)</label>
                    <input type="number" class="form-input" id="pe-phase2-delay" value="${pe.phase2_cycle_delay_seconds || 5}" min="1" max="30">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Reset After (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase2-reset" value="${pe.phase2_reset_minutes || 30}" min="1" max="180">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Max Volume (%) in Phase 2</label>
                    <input type="number" class="form-input" id="pe-phase2-max-volume" value="${pe.phase2_max_volume ?? 100}" min="0" max="100" title="Cap TTS volume when in phase 2">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group pe-budget-boost-section" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Budget boost days</div>
                <div class="tts-msg-desc">
                  On selected weekdays, each room's daily kWh budget is multiplied before power alerts apply.
                  Scheduled reminders repeat inside the time window (set <strong>Default media player</strong> on the TTS tab).
                  Edit spoken messages on the <strong>TTS</strong> tab.
                </div>
                <div class="form-group" style="margin-bottom:10px;">
                  <label class="form-label" style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                    <input type="checkbox" id="pe-budget-boost-enabled" ${ttsSettings.budget_boost_enabled ? 'checked' : ''}>
                    Enable budget boost
                  </label>
                </div>
                <div class="grid-2" style="margin-bottom:10px;">
                  <div class="form-group">
                    <label class="form-label">Budget multiplier</label>
                    <input type="number" class="form-input" id="pe-budget-boost-mult" min="1" max="5" step="0.1"
                      value="${ttsSettings.budget_boost_multiplier ?? 2}">
                  </div>
                </div>
                <div class="form-group" style="margin-bottom:10px;">
                  <label class="form-label">Boost weekdays</label>
                  <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="0" ${bbDayChk(0)}> Mon</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="1" ${bbDayChk(1)}> Tue</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="2" ${bbDayChk(2)}> Wed</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="3" ${bbDayChk(3)}> Thu</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="4" ${bbDayChk(4)}> Fri</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="5" ${bbDayChk(5)}> Sat</label>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;"><input type="checkbox" class="form-checkbox pe-budget-boost-day" value="6" ${bbDayChk(6)}> Sun</label>
                  </div>
                </div>
                <div class="grid-2" style="margin-bottom:10px;">
                  <div class="form-group">
                    <label class="form-label">Active hours start</label>
                    <input type="text" class="form-input" id="pe-budget-boost-win-start" placeholder="9:00 AM" value="${bbWinStartAmPm}">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Active hours end</label>
                    <input type="text" class="form-input" id="pe-budget-boost-win-end" placeholder="9:00 PM" value="${bbWinEndAmPm}">
                  </div>
                </div>
                <div class="grid-2" style="margin-bottom:0;">
                  <div class="form-group">
                    <label class="form-label">Announce every</label>
                    <select class="form-select" id="pe-budget-boost-repeat">${repeatOptHtml}</select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Minute offset (0–59)</label>
                    <input type="number" class="form-input" id="pe-budget-boost-mo" min="0" max="59" value="${bbMo}">
                    <div style="font-size:10px;color:var(--secondary-text-color);margin-top:4px;">e.g. 30 = announcements on the :30</div>
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Daily kWh Warnings</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Room kWh tier thresholds</label>
                    <input type="text" class="form-input" id="pe-room-kwh-intervals" value="${this._parseRoomKwhIntervals(pe.room_kwh_intervals || []).intervals.join(', ')}" placeholder="5, 10, 15, 20">
                    <div style="font-size:10px;color:var(--secondary-text-color);margin-top:4px;">Exactly four comma-separated increasing kWh values (e.g. 5, 10, 15, 20).</div>
                  </div>
                  <div class="form-group">
                    <label class="form-label">Home kWh Limit</label>
                    <input type="number" class="form-input" id="pe-home-kwh-limit" value="${pe.home_kwh_limit || 22}" min="1">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Rooms with Enforcement Enabled</div>
                <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px;">
                  ${rooms.map(room => {
                    const roomId = this._canonicalRoomId(room);
                    const isEnabled = roomsEnabled.includes(roomId);
                    return `
                      <label style="display: flex; align-items: center; gap: 6px; background: var(--card-background-color); padding: 8px 12px; border-radius: 8px; cursor: pointer;">
                        <input type="checkbox" class="pe-room-checkbox" data-room-id="${roomId}" ${isEnabled ? 'checked' : ''} style="width: 16px; height: 16px;">
                        <span>${(room.name || '').replace(/</g, '&lt;')}</span>
                      </label>
                    `;
                  }).join('')}
                  ${rooms.length === 0 ? '<span style="color: var(--secondary-text-color);">No rooms configured.</span>' : ''}
                </div>
              </div>
              <button class="btn btn-primary" id="save-enforcement-btn" style="margin-top: 16px;">
                Save Power Enforcement Settings
              </button>
            </div>
          </div>
        </div>
        <div class="room-icon-modal-overlay" id="room-icon-modal-overlay" style="display: none;" aria-hidden="true">
          <div class="room-icon-modal" role="dialog" aria-labelledby="room-icon-modal-title" aria-modal="true">
            <div class="room-icon-modal-header">
              <h2 class="room-icon-modal-title" id="room-icon-modal-title">Room icon</h2>
              <div class="room-icon-modal-actions">
                <button type="button" class="btn btn-secondary" id="room-icon-modal-reset">Reset to default</button>
                <button type="button" class="graph-modal-close" id="room-icon-modal-close" aria-label="Close">×</button>
              </div>
            </div>
            <div class="room-icon-modal-body" id="room-icon-modal-body"></div>
          </div>
        </div>
      </div>
    `;

    this._attachSettingsEventListeners();
    this._attachRoomIconPickerListeners();
    this.shadowRoot.querySelectorAll('.room-settings-card').forEach((c) => this._syncRoomPresenceLiveStrip(c));
    this._updateRoomPresenceLiveLabels();
    initCustomSelects(this.shadowRoot);
  }

  _getAllOutlets() {
    const rooms = this._config?.rooms || [];
    const outlets = [];
    rooms.forEach(room => {
      const roomId = this._canonicalRoomId(room);
      (room.outlets || []).forEach(outlet => {
        const outletId = `${roomId}_${(outlet.name || 'outlet').toLowerCase().replace(/\s+/g, '_')}`;
        outlets.push({
          id: outletId,
          room_id: roomId,
          room_name: room.name,
          outlet_name: outlet.name,
        });
      });
    });
    return outlets;
  }

  _roomHasResponsiveLightEligibility(room) {
    const outlets = room.outlets || [];
    const hasOutletWithThreshold = outlets.some(o => {
      const t = o.type || 'outlet';
      const th = o.threshold || 0;
      return (t === 'outlet' || t === 'single_outlet' || t === 'minisplit') && th > 0;
    });
    const hasWrgbLight = outlets.some(o => {
      if ((o.type || '') !== 'light') return false;
      const ents = o.light_entities || [];
      return ents.some(e => (typeof e === 'object' && e?.wrgb) || false);
    });
    return hasOutletWithThreshold && hasWrgbLight;
  }

  _renderResponsiveLightWarnings(room, index) {
    const eligible = this._roomHasResponsiveLightEligibility(room);
    const enabled = eligible && room.responsive_light_warnings === true;
    const rgb = room.responsive_light_color || [245, 0, 0];
    const rgbHex = '#' + [rgb[0], rgb[1], rgb[2]].map(x => Math.round(Math.min(255, Math.max(0, x))).toString(16).padStart(2, '0')).join('');
    const tempK = room.responsive_light_temp ?? 6500;
    const interval = room.responsive_light_interval ?? 1.5;
    return `
      <div class="form-group responsive-light-section" style="margin-bottom: 16px; padding: 12px; background: var(--panel-accent-dim); border-radius: 8px;">
        <div class="toggle-row ${!eligible ? 'toggle-disabled' : ''}">
          <label class="toggle-switch">
            <input type="checkbox" class="responsive-light-warnings-toggle" ${enabled ? 'checked' : ''} ${!eligible ? 'disabled' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <span class="toggle-label">Responsive light warnings</span>
        </div>
        ${!eligible ? '<div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 6px;">Requires at least one outlet with threshold and one light device with a smart WRGB light.</div>' : ''}
        ${eligible && enabled ? `
          <div class="responsive-light-pickers" style="margin-top: 12px; display: flex; gap: 16px; flex-wrap: wrap;">
            <div class="form-group">
              <label class="form-label">Warning color (RGB)</label>
              <input type="color" class="responsive-light-color-picker" value="${rgbHex}" title="Color when threshold exceeded">
            </div>
            <div class="form-group">
              <label class="form-label">Rest color (Kelvin)</label>
              <input type="number" class="form-input responsive-light-temp-picker" value="${tempK}" min="2000" max="6500" step="100" placeholder="6500" style="width: 90px;" title="Color temp when alternating">
            </div>
            <div class="form-group">
              <label class="form-label">Change frequency (seconds)</label>
              <input type="number" class="form-input responsive-light-interval-picker" value="${interval}" min="0.1" max="10" step="0.1" placeholder="1.5" style="width: 90px;" title="Interval between color changes">
            </div>
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderPresenceAutoOffRow(inputClass, checked, helpText) {
    const esc = (helpText || '').replace(/</g, '&lt;');
    return `
      <div class="form-group" style="margin-top: 12px;">
        <label class="toggle-row">
          <input type="checkbox" class="form-checkbox ${inputClass}" ${checked ? 'checked' : ''}>
          <span class="toggle-label">Turn off when person outside zones</span>
        </label>
        <div class="tts-msg-desc" style="margin-top: 4px;">${esc}</div>
      </div>
    `;
  }

  _renderRoomPresenceSection(room, index) {
    const persons = Array.isArray(this._entities?.persons) ? this._entities.persons : [];
    const zlist = Array.isArray(room.presence_zone_entities) && room.presence_zone_entities.length
      ? room.presence_zone_entities
      : [''];
    const curPerson = (room.presence_person_entity || '').trim();
    const zoneRows = zlist.map((z) => `
      <div class="room-zone-row" style="display:flex; gap:8px; align-items:center; margin-bottom:8px; flex-wrap:wrap;">
        <div style="flex:1; min-width:200px;">
          ${this._renderEntityAutocomplete((z || '').trim(), 'zone', index, 'room-zone-entity', 'zone.home')}
        </div>
        <button type="button" class="icon-btn danger room-zone-remove-btn" title="Remove zone">
          <svg viewBox="0 0 24 24">${icons.delete}</svg>
        </button>
      </div>
    `).join('');
    const personOptions = persons
      .filter((p) => (p.entity_id || '').startsWith('person.'))
      .map((p) => {
        const id = (p.entity_id || '').replace(/"/g, '&quot;');
        const name = (p.friendly_name || p.entity_id || '').replace(/</g, '&lt;');
        const sel = curPerson === (p.entity_id || '') ? ' selected' : '';
        return `<option value="${id}"${sel}>${name}</option>`;
      })
      .join('');
    return `
      <div class="divider" style="margin: 16px 0;"></div>
      <h4 style="margin: 0 0 8px; font-size: 11px; color: var(--secondary-text-color);">Presence &amp; zones</h4>
      <p class="tts-msg-desc" style="margin-bottom: 12px;">
        Optional: pick who this room tracks and which zones count as present. Leaving all selected zones turns off the configured switch.* entities (plugs, vent, light switch, etc.) for devices below that have this enabled. Entering any selected zone again turns those same switches back on only if this automation had turned them off (tracked per switch). Updates run on a short interval and when the person or selected zones change state.
        Persons appear only if they have a linked device tracker in Home Assistant.
      </p>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Person</label>
        <select class="form-select room-presence-person">
          <option value="">None</option>
          ${personOptions}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Zones (in any = present)</label>
        <div class="room-zone-rows">${zoneRows}</div>
        <button type="button" class="btn btn-secondary room-zone-add-btn" style="margin-top:8px;">+ Add zone</button>
      </div>
    `;
  }

  _effectiveRoomIcon(room) {
    const raw = room && room.room_icon != null ? String(room.room_icon).trim().toLowerCase() : '';
    if (raw && _ROOM_ICON_MDI_RE.test(raw) && raw.length <= 80) return raw;
    return 'mdi:home';
  }

  _roomIconStoredValue(room) {
    const raw = room && room.room_icon != null ? String(room.room_icon).trim().toLowerCase() : '';
    if (raw && _ROOM_ICON_MDI_RE.test(raw) && raw.length <= 80) return raw;
    return '';
  }

  _collectRoomIconFromCard(card) {
    const raw = (card.querySelector('.room-icon-mdi')?.value || '').trim().toLowerCase();
    if (!raw) return null;
    if (!_ROOM_ICON_MDI_RE.test(raw) || raw.length > 80) return null;
    return raw;
  }

  _scheduleUpdateRoomPresenceLiveLabels() {
    if (!this._showSettings || !this.shadowRoot) return;
    if (this._presenceLiveThrottleTimer) return;
    const now = Date.now();
    const elapsed = now - this._presenceLiveLastRun;
    const delay = elapsed >= 1000 ? 0 : 1000 - elapsed;
    this._presenceLiveThrottleTimer = setTimeout(() => {
      this._presenceLiveThrottleTimer = null;
      this._presenceLiveLastRun = Date.now();
      this._updateRoomPresenceLiveLabels();
    }, delay);
  }

  /**
   * Human-readable location for person or device_tracker state (matches typical HA UI: Home, Away, zone names).
   */
  _formatPresenceLocationDisplay(entityState) {
    if (!entityState || !this._hass?.states) return 'unknown';
    const raw = entityState.state;
    if (raw == null || String(raw).trim() === '') return 'unknown';
    const state = String(raw).trim();
    const lower = state.toLowerCase();
    if (lower === 'home') return 'Home';
    if (lower === 'not_home') return 'Away';
    if (lower === 'unknown') return 'unknown';
    if (lower === 'unavailable') return 'unavailable';

    const attrs = entityState.attributes || {};
    const loc = attrs.location_name;
    if (loc != null && String(loc).trim() !== '') {
      return String(loc).trim();
    }

    if (!state.includes('.')) {
      const zoneId = `zone.${state}`;
      const zst = this._hass.states[zoneId];
      if (zst && zst.attributes?.friendly_name != null && String(zst.attributes.friendly_name).trim() !== '') {
        return String(zst.attributes.friendly_name).trim();
      }
    } else if (state.startsWith('zone.')) {
      const zst = this._hass.states[state];
      if (zst && zst.attributes?.friendly_name != null && String(zst.attributes.friendly_name).trim() !== '') {
        return String(zst.attributes.friendly_name).trim();
      }
    }

    return state.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  /** Prefer linked device_tracker.* state over person.*; label formatted for display. */
  _presenceLabelFromPersonState(personState) {
    if (!personState || !this._hass?.states) return 'unknown';
    const attrs = personState.attributes || {};
    const source = attrs.source != null ? String(attrs.source).trim() : '';
    let trackerId = '';
    if (source.startsWith('device_tracker.')) {
      trackerId = source;
    } else if (source && !source.includes('.')) {
      const cand = `device_tracker.${source}`;
      if (this._hass.states[cand]) trackerId = cand;
    }
    if (!trackerId) {
      const raw = attrs.device_trackers;
      const list = Array.isArray(raw) ? raw : raw != null && String(raw).trim() ? [String(raw).trim()] : [];
      trackerId = list.map((t) => String(t).trim()).find((t) => t.startsWith('device_tracker.')) || '';
    }
    if (trackerId) {
      const ts = this._hass.states[trackerId];
      if (!ts) return 'unavailable';
      return this._formatPresenceLocationDisplay(ts);
    }
    return this._formatPresenceLocationDisplay(personState);
  }

  _updateRoomPresenceLiveLabels() {
    if (!this._hass?.states || !this.shadowRoot) return;
    this.shadowRoot.querySelectorAll('.room-settings-presence-live').forEach((strip) => {
      const pid = (strip.dataset.presencePerson || '').trim();
      const textEl = strip.querySelector('.room-settings-presence-live-text');
      if (!textEl) return;
      if (!pid.startsWith('person.')) {
        textEl.textContent = '';
        return;
      }
      const st = this._hass.states[pid];
      if (!st) {
        textEl.textContent = `${pid} — unavailable`;
        return;
      }
      const name = st.attributes?.friendly_name || pid;
      const report = this._presenceLabelFromPersonState(st);
      textEl.textContent = `${name} — ${report}`;
    });
  }

  _syncRoomPresenceLiveStrip(card) {
    if (!card) return;
    const slot = card.querySelector('.room-settings-header-presence');
    if (!slot) return;
    const pid = (card.querySelector('.room-presence-person')?.value || '').trim();
    let strip = slot.querySelector('.room-settings-presence-live');
    if (!pid.startsWith('person.')) {
      if (strip) strip.remove();
      return;
    }
    if (!strip) {
      strip = document.createElement('div');
      strip.className = 'room-settings-presence-live room-settings-presence-live--header';
      strip.innerHTML = '<span class="room-settings-presence-live-text">Loading…</span>';
      slot.appendChild(strip);
    }
    strip.dataset.presencePerson = pid;
    this._updateRoomPresenceLiveLabels();
  }

  _closeRoomIconModal() {
    const overlay = this.shadowRoot?.getElementById('room-icon-modal-overlay');
    if (overlay) {
      overlay.style.display = 'none';
      overlay.setAttribute('aria-hidden', 'true');
    }
    const body = this.shadowRoot?.getElementById('room-icon-modal-body');
    if (body) body.innerHTML = '';
    this._roomIconModalTargetCard = null;
    if (this._roomIconModalEscapeHandler) {
      window.removeEventListener('keydown', this._roomIconModalEscapeHandler);
      this._roomIconModalEscapeHandler = null;
    }
  }

  _applyRoomIconSelection(mdiId) {
    const card = this._roomIconModalTargetCard;
    if (!card) return;
    let normalized = (mdiId || '').trim().toLowerCase();
    if (normalized && (!_ROOM_ICON_MDI_RE.test(normalized) || normalized.length > 80)) return;
    const hidden = card.querySelector('.room-icon-mdi');
    const triggerIcon = card.querySelector('.room-icon-picker-trigger ha-icon');
    if (!normalized || normalized === 'mdi:home') {
      if (hidden) hidden.value = '';
      if (triggerIcon) triggerIcon.setAttribute('icon', 'mdi:home');
    } else {
      if (hidden) hidden.value = normalized;
      if (triggerIcon) triggerIcon.setAttribute('icon', normalized);
    }
    this._closeRoomIconModal();
  }

  _mountRoomIconModalBody(initialIcon) {
    const body = this.shadowRoot.getElementById('room-icon-modal-body');
    if (!body) return;
    body.innerHTML = '';
    const Picker = customElements.get('ha-icon-picker');
    if (Picker) {
      const picker = document.createElement('ha-icon-picker');
      picker.setAttribute('label', 'Icon');
      const startVal = initialIcon || 'mdi:home';
      picker.setAttribute('value', startVal);
      let lastVal = startVal;
      const onPick = (e) => {
        const v = String((e.detail && e.detail.value) != null ? e.detail.value : picker.value || '').trim();
        if (!v || v === lastVal) return;
        lastVal = v;
        this._applyRoomIconSelection(v);
      };
      picker.addEventListener('value-changed', onPick);
      picker.addEventListener('icon-selected', onPick);
      body.appendChild(picker);
      return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'room-icon-modal-fallback';
    wrap.innerHTML = `
      <p class="tts-msg-desc" style="margin:0 0 8px;">Pick an icon below or use the filter. Default is the home icon.</p>
      <input type="search" class="form-input room-icon-modal-search" placeholder="Filter icons…" style="width:100%;margin-bottom:12px;box-sizing:border-box;">
      <div class="room-icon-modal-grid"></div>
    `;
    body.appendChild(wrap);
    const search = wrap.querySelector('.room-icon-modal-search');
    const grid = wrap.querySelector('.room-icon-modal-grid');
    const renderGrid = (filter) => {
      const q = (filter || '').trim().toLowerCase();
      grid.innerHTML = '';
      ROOM_ICON_CURATED.filter((id) => !q || id.includes(q)).forEach((id) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'room-icon-modal-grid-btn';
        b.title = id;
        b.setAttribute('aria-label', id);
        const hi = document.createElement('ha-icon');
        hi.setAttribute('icon', id);
        b.appendChild(hi);
        b.addEventListener('click', () => this._applyRoomIconSelection(id));
        grid.appendChild(b);
      });
    };
    renderGrid('');
    search.addEventListener('input', () => renderGrid(search.value));
  }

  _openRoomIconModal(card) {
    if (!card || !this.shadowRoot) return;
    this._closeRoomIconModal();
    this._roomIconModalTargetCard = card;
    const hidden = card.querySelector('.room-icon-mdi');
    const stored = (hidden?.value || '').trim().toLowerCase();
    const initial =
      stored && _ROOM_ICON_MDI_RE.test(stored) && stored.length <= 80 ? stored : 'mdi:home';
    const overlay = this.shadowRoot.getElementById('room-icon-modal-overlay');
    if (!overlay) return;
    this._mountRoomIconModalBody(initial);
    overlay.style.display = 'flex';
    overlay.setAttribute('aria-hidden', 'false');
    this._roomIconModalEscapeHandler = (e) => {
      if (e.key === 'Escape') this._closeRoomIconModal();
    };
    window.addEventListener('keydown', this._roomIconModalEscapeHandler);
  }

  _attachRoomIconPickerListeners(card = null) {
    const scope = card || this.shadowRoot;
    if (!scope) return;
    scope.querySelectorAll('.room-icon-picker-trigger').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const c = btn.closest('.room-settings-card');
        if (c) this._openRoomIconModal(c);
      });
    });
    if (!card) {
      const overlay = this.shadowRoot.getElementById('room-icon-modal-overlay');
      if (overlay) {
        overlay.addEventListener('click', (e) => {
          if (e.target === overlay) this._closeRoomIconModal();
        });
      }
      this.shadowRoot.getElementById('room-icon-modal-close')
        ?.addEventListener('click', () => this._closeRoomIconModal());
      this.shadowRoot.getElementById('room-icon-modal-reset')
        ?.addEventListener('click', () => this._applyRoomIconSelection('mdi:home'));
    }
  }

  _collectPresencePersonFromCard(card) {
    const v = (card.querySelector('.room-presence-person')?.value || '').trim();
    return v.startsWith('person.') ? v : null;
  }

  _collectPresenceZonesFromCard(card) {
    const ids = [];
    card.querySelectorAll('.room-zone-row').forEach((row) => {
      const inp = row.querySelector('.entity-datalist-input.room-zone-entity');
      const z = (inp?.value || '').trim();
      if (z.startsWith('zone.')) ids.push(z);
    });
    return [...new Set(ids)];
  }

  _applyPresenceAutoOffFromItemToDevice(item, device) {
    const t = device.type;
    if (t === 'outlet') {
      device.presence_auto_off_plug1 = item.querySelector('.presence-auto-off-plug1')?.checked === true;
      device.presence_auto_off_plug2 = item.querySelector('.presence-auto-off-plug2')?.checked === true;
    } else if (
      ['single_outlet', 'minisplit', 'stove', 'light', 'vent', 'wall_heater', 'ceiling_vent_fan', 'fridge', 'microwave'].includes(t)
    ) {
      device.presence_auto_off = item.querySelector('.presence-auto-off-appliance')?.checked === true;
    }
  }

  _applyVentLikePowerFromItem(item, device) {
    const switchVal = (item.querySelector('input.ceiling-vent-switch') || item.querySelector('.entity-datalist-input.ceiling-vent-switch'))?.value;
    device.switch_entity = (switchVal && switchVal.startsWith('switch.')) ? switchVal : null;
    const cvps = item.querySelector('.ceiling-vent-power-source')?.value;
    device.power_source = cvps === 'sensor' ? 'sensor' : 'configured';
    const cvpseIn =
      item.querySelector('.entity-datalist-input.ceiling-vent-power-sensor-entity')
      || item.querySelector('input.ceiling-vent-power-sensor-entity');
    const cvpse = (cvpseIn?.value || '').trim();
    device.power_sensor_entity =
      device.power_source === 'sensor'
      && (cvpse.startsWith('sensor.') || cvpse.startsWith('switch.'))
        ? cvpse
        : null;
    device.watts_when_on =
      device.power_source === 'sensor'
        ? 0
        : parseInt(item.querySelector('.ceiling-vent-watts')?.value, 10) || 0;
  }

  _handleRoomZoneClick(e) {
    const addBtn = e.target.closest('.room-zone-add-btn');
    if (addBtn) {
      e.preventDefault();
      const card = addBtn.closest('.room-settings-card');
      const list = card?.querySelector('.room-zone-rows');
      const roomIndex = card?.dataset?.roomIndex;
      if (!list || roomIndex === undefined) return;
      const row = document.createElement('div');
      row.className = 'room-zone-row';
      row.style.cssText = 'display:flex; gap:8px; align-items:center; margin-bottom:8px; flex-wrap:wrap;';
      row.innerHTML = `
        <div style="flex:1; min-width:200px;">
          ${this._renderEntityAutocomplete('', 'zone', roomIndex, 'room-zone-entity', 'zone.home')}
        </div>
        <button type="button" class="icon-btn danger room-zone-remove-btn" title="Remove zone">
          <svg viewBox="0 0 24 24">${icons.delete}</svg>
        </button>
      `;
      list.appendChild(row);
      this._initEntityAutocompletes(row);
      return;
    }
    const remBtn = e.target.closest('.room-zone-remove-btn');
    if (remBtn) {
      e.preventDefault();
      const row = remBtn.closest('.room-zone-row');
      const list = row?.parentElement;
      if (!row || !list?.classList.contains('room-zone-rows')) return;
      const rows = list.querySelectorAll('.room-zone-row');
      if (rows.length <= 1) {
        const inp = row.querySelector('.entity-datalist-input.room-zone-entity');
        if (inp) inp.value = '';
        return;
      }
      row.remove();
    }
  }

  /**
   * Live heater temperature for wall_heater guard: prefer get_power_data outlet, else HA sensor state.
   * @returns {number|null} degrees, or null if unknown
   */
  _getWallHeaterLiveTemp(roomId, outletIndex, outletConfig) {
    const rooms = this._powerData?.rooms || [];
    const pr = rooms.find((r) => r.id === roomId);
    const po = pr?.outlets?.[outletIndex];
    if (po) {
      const hc = po.heater_current_temperature;
      if (hc != null && hc !== '' && !Number.isNaN(Number(hc))) {
        const n = Number(hc);
        if (Number.isFinite(n)) return n;
      }
    }
    const te = String(outletConfig?.heater_temperature_entity || '').trim();
    if (te.startsWith('sensor.')) {
      const st = this._hass?.states?.[te];
      if (st?.state != null && String(st.state) !== '') {
        const n = Number(st.state);
        if (!Number.isNaN(n) && Number.isFinite(n)) return n;
      }
    }
    return null;
  }

  _closeApplianceMenu() {
    if (this._applianceMenuEsc) {
      window.removeEventListener('keydown', this._applianceMenuEsc);
      this._applianceMenuEsc = null;
    }
    if (this._applianceMenuScrollClose) {
      window.removeEventListener('scroll', this._applianceMenuScrollClose, true);
      this._applianceMenuScrollClose = null;
    }
    this.shadowRoot?.querySelector('.appliance-context-menu-backdrop')?.remove();
  }

  _openOutletUsageGraph(roomId, outletIndex, outlet, plugSlot) {
    const name = outlet.name || 'Appliance';
    let seriesLabel = name;
    let graphTitle = `${name} usage by hour today`;
    if (plugSlot === 1) {
      seriesLabel = `${name} (Plug 1)`;
      graphTitle = `${name} (Plug 1) usage by hour today`;
    } else if (plugSlot === 2) {
      seriesLabel = `${name} (Plug 2)`;
      graphTitle = `${name} (Plug 2) usage by hour today`;
    }
    void this._openGraph('outlet_wh', roomId, '', null, {
      outletIndex,
      plugSlot,
      outletGraphTitle: graphTitle,
      outletSeriesLabel: seriesLabel,
    });
  }

  _openApplianceContextMenu(e, { roomId, outletIndex, outlet }) {
    e.preventDefault();
    e.stopPropagation();
    this._closeApplianceMenu();

    const otype = outlet.type || 'outlet';
    const hasP1 = Boolean(String(outlet.plug1_entity || '').trim());
    const hasP2 = Boolean(String(outlet.plug2_entity || '').trim());
    const dualReceptacle = otype === 'outlet' && hasP1 && hasP2;

    const backdrop = document.createElement('div');
    backdrop.className = 'appliance-context-menu-backdrop';
    const menu = document.createElement('div');
    menu.className = 'appliance-context-menu';
    menu.setAttribute('role', 'menu');

    const addItem = (label, action, plugSlot) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'appliance-context-menu-item';
      b.setAttribute('role', 'menuitem');
      b.textContent = label;
      b.dataset.applianceAction = action;
      if (plugSlot != null) b.dataset.plugSlot = String(plugSlot);
      b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this._closeApplianceMenu();
        if (action === 'graph') {
          this._openOutletUsageGraph(roomId, outletIndex, outlet, plugSlot);
        } else {
          void this._executeApplianceToggle({ roomId, outletIndex, plugSlot });
        }
      });
      menu.appendChild(b);
    };

    if (dualReceptacle) {
      addItem('Open usage graph (Plug 1)', 'graph', 1);
      if (this._resolveApplianceToggleTarget(outlet, 1)) {
        addItem('Turn Plug 1 on or off', 'toggle', 1);
      }
      addItem('Open usage graph (Plug 2)', 'graph', 2);
      if (this._resolveApplianceToggleTarget(outlet, 2)) {
        addItem('Turn Plug 2 on or off', 'toggle', 2);
      }
    } else if (otype === 'outlet') {
      if (hasP1) {
        addItem('Open usage graph', 'graph', 1);
        if (this._resolveApplianceToggleTarget(outlet, 1)) {
          addItem('Turn on or off', 'toggle', 1);
        }
      } else if (hasP2) {
        addItem('Open usage graph', 'graph', 2);
        if (this._resolveApplianceToggleTarget(outlet, 2)) {
          addItem('Turn on or off', 'toggle', 2);
        }
      } else {
        addItem('Open usage graph', 'graph', 1);
      }
    } else {
      addItem('Open usage graph', 'graph', null);
      if (this._resolveApplianceToggleTarget(outlet, null)) {
        addItem('Turn on or off', 'toggle', null);
      }
    }

    menu.addEventListener('click', (ev) => ev.stopPropagation());
    backdrop.addEventListener('click', () => this._closeApplianceMenu());

    backdrop.appendChild(menu);
    this.shadowRoot.appendChild(backdrop);

    const cx = e.clientX ?? 0;
    const cy = e.clientY ?? 0;
    menu.style.left = `${cx}px`;
    menu.style.top = `${cy}px`;

    const pad = 8;
    requestAnimationFrame(() => {
      const rect = menu.getBoundingClientRect();
      let left = cx;
      let top = cy;
      if (left + rect.width > window.innerWidth - pad) {
        left = Math.max(pad, window.innerWidth - rect.width - pad);
      }
      if (top + rect.height > window.innerHeight - pad) {
        top = Math.max(pad, window.innerHeight - rect.height - pad);
      }
      if (left < pad) left = pad;
      if (top < pad) top = pad;
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
    });

    const first = menu.querySelector('.appliance-context-menu-item');
    first?.focus?.();

    this._applianceMenuEsc = (kev) => {
      if (kev.key === 'Escape') this._closeApplianceMenu();
    };
    window.addEventListener('keydown', this._applianceMenuEsc);

    this._applianceMenuScrollClose = () => this._closeApplianceMenu();
    window.addEventListener('scroll', this._applianceMenuScrollClose, true);
  }

  _resolveApplianceToggleTarget(outlet, plugSlot) {
    const otype = outlet.type || 'outlet';
    if (otype === 'outlet') {
      if (plugSlot === 1) {
        const s = outlet.plug1_switch;
        return s && String(s).startsWith('switch.')
          ? { switchEntity: s, plugName: 'Plug 1' }
          : null;
      }
      if (plugSlot === 2) {
        const s = outlet.plug2_switch;
        return s && String(s).startsWith('switch.')
          ? { switchEntity: s, plugName: 'Plug 2' }
          : null;
      }
      return null;
    }
    if (otype === 'light') {
      const s = outlet.switch_entity;
      return s && String(s).startsWith('switch.')
        ? { switchEntity: s, plugName: '' }
        : null;
    }
    if (
      otype === 'single_outlet' ||
      otype === 'minisplit' ||
      otype === 'stove' ||
      otype === 'microwave' ||
      otype === 'fridge'
    ) {
      const s = outlet.plug1_switch;
      return s && String(s).startsWith('switch.')
        ? { switchEntity: s, plugName: '' }
        : null;
    }
    if (otype === 'vent' || otype === 'wall_heater') {
      const s = outlet.switch_entity;
      return s && String(s).startsWith('switch.')
        ? { switchEntity: s, plugName: '' }
        : null;
    }
    return null;
  }

  async _executeApplianceToggle({ roomId, outletIndex, plugSlot }) {
    const room = this._getRoomConfig(roomId);
    if (!room) return;
    const outlet = room.outlets?.[outletIndex];
    if (!outlet) return;
    const otype = outlet.type || 'outlet';
    const t = this._resolveApplianceToggleTarget(outlet, plugSlot);
    if (!t?.switchEntity) {
      showToast(this.shadowRoot, 'This device is not configured for switching.', 'error');
      return;
    }
    const { switchEntity, plugName } = t;
    const outletName = outlet.name || 'Appliance';

    try {
      const authResult = await this._hass.callWS({
        type: 'smart_dashboards/check_toggle_auth',
        room_id: roomId,
      });

      if (!authResult.authorized) {
        showToast(
          this.shadowRoot,
          `Not authorized. Only ${authResult.room_person || 'the assigned person'} can control devices in this room.`,
          'error',
        );
        return;
      }

      const currentState = this._hass.states[switchEntity]?.state;
      const actionWord = currentState === 'on' ? 'turn off' : 'turn on';
      const displayName = plugName ? `${outletName} ${plugName}` : outletName;

      if (otype === 'wall_heater' && currentState !== 'on') {
        const thRaw = outlet.heater_on_below_temperature;
        const threshold = Number(thRaw != null && thRaw !== '' ? thRaw : 65);
        const th = Number.isFinite(threshold) ? threshold : 65;
        const temp = this._getWallHeaterLiveTemp(roomId, outletIndex, outlet);
        if (temp != null && temp > th) {
          showToast(
            this.shadowRoot,
            `It's already ${Math.round(temp)}° in here—the heater only turns on below ${Math.round(th)}°.`,
            'error',
          );
          return;
        }
      }

      let confirmed = false;
      if (otype === 'minisplit' && authResult.is_admin !== true) {
        confirmed = await this._showMinisplitAcSafetyModal(displayName, actionWord);
      } else {
        confirmed = await this._showToggleConfirmation(displayName, actionWord);
      }
      if (!confirmed) return;

      const announceTts = authResult.requires_tts === true;
      await this._hass.callWS({
        type: 'smart_dashboards/toggle_switch',
        entity_id: switchEntity,
        room_id: roomId,
        outlet_name: outletName,
        plug_name: plugName,
        announce_tts: announceTts,
      });

      const newState = currentState === 'on' ? 'off' : 'on';
      showToast(this.shadowRoot, `${displayName} turned ${newState}`, 'success');
    } catch (err) {
      const code = err?.code ?? err?.error?.code;
      const m = err?.message || err?.error?.message || '';
      if (
        code === 'heater_too_warm' ||
        (typeof m === 'string' && m.includes('only turns on below'))
      ) {
        showToast(this.shadowRoot, m || "It's too warm in here to turn on the heater.", 'error');
        return;
      }
      showToast(this.shadowRoot, `Failed to toggle: ${err.message || err}`, 'error');
    }
  }

  _handleApplianceToggleClick(e) {
    if (this._showSettings) return;
    if (e.target.closest('.appliance-context-menu') || e.target.closest('.appliance-context-menu-backdrop')) {
      return;
    }

    const deviceCard = e.target.closest('.device-card, .outlet-card');
    if (!deviceCard) return;

    if (e.target.closest('.graph-clickable')) return;

    const roomCard = deviceCard.closest('.room-card');
    if (!roomCard) return;
    const roomId = roomCard.dataset.roomId;
    if (!roomId) return;

    const outletIndex = parseInt(deviceCard.dataset.outletIndex, 10);
    if (Number.isNaN(outletIndex)) return;

    const room = this._getRoomConfig(roomId);
    if (!room) return;
    const outlet = room.outlets?.[outletIndex];
    if (!outlet) return;

    const otype = outlet.type || 'outlet';
    if (
      !(
        otype === 'outlet' ||
        otype === 'light' ||
        otype === 'single_outlet' ||
        otype === 'minisplit' ||
        otype === 'stove' ||
        otype === 'microwave' ||
        otype === 'fridge' ||
        otype === 'vent' ||
        otype === 'wall_heater'
      )
    ) {
      return;
    }

    e.preventDefault();
    e.stopPropagation();

    this._openApplianceContextMenu(e, { roomId, outletIndex, outlet });
  }

  _showToggleConfirmation(applianceName, actionWord) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'toggle-confirm-overlay';
      overlay.innerHTML = `
        <div class="toggle-confirm-modal">
          <div class="toggle-confirm-title">Confirm Action</div>
          <div class="toggle-confirm-message">Are you sure you want to ${actionWord} <strong>${applianceName.replace(/</g, '&lt;')}</strong>?</div>
          <div class="toggle-confirm-buttons">
            <button type="button" class="toggle-confirm-cancel">Cancel</button>
            <button type="button" class="toggle-confirm-ok">Confirm</button>
          </div>
        </div>
      `;

      const cleanup = (result) => {
        overlay.remove();
        resolve(result);
      };

      overlay.querySelector('.toggle-confirm-cancel').addEventListener('click', () => cleanup(false));
      overlay.querySelector('.toggle-confirm-ok').addEventListener('click', () => cleanup(true));
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) cleanup(false);
      });

      this.shadowRoot.appendChild(overlay);
      overlay.querySelector('.toggle-confirm-ok').focus();
    });
  }

  /** Absolute URL for a file under the panel static root (/smart_dashboards_panel/). */
  _panelStaticFileUrl(filename) {
    const path = `/smart_dashboards_panel/ac-setup/${filename}`;
    const h = this._hass;
    if (h && typeof h.hassUrl === 'function') {
      return h.hassUrl(path);
    }
    return path;
  }

  /**
   * One-step modal for non-admin users toggling a mini-split (AC): zone automation warning,
   * privacy note, Companion / zone setup steps, then primary action to confirm toggle.
   */
  _showMinisplitAcSafetyModal(displayName, actionWord) {
    const actLabel = String(actionWord || 'turn on').replace(/^\w/, (c) => c.toUpperCase());
    const nameStr = String(displayName || 'AC');
    const escAttr = (s) => String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    const urlCompanion = escAttr(this._panelStaticFileUrl('companion-app-location.jpeg'));
    const urlIos = escAttr(this._panelStaticFileUrl('ios-system-location.jpeg'));
    const totalSteps = 4;

    return new Promise((resolve) => {
      let currentStep = 1;
      const overlay = document.createElement('div');
      overlay.className = 'ac-safety-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.innerHTML = `
        <div class="ac-safety-modal">
          <div class="ac-safety-title">Air conditioner / zone automation</div>
          <div class="ac-wizard-steps">
            <div class="ac-wizard-step-dot active" data-step="1"></div>
            <div class="ac-wizard-step-dot" data-step="2"></div>
            <div class="ac-wizard-step-dot" data-step="3"></div>
            <div class="ac-wizard-step-dot" data-step="4"></div>
          </div>
          <div class="ac-safety-body">
            <!-- Step 1: Introduction -->
            <div class="ac-wizard-step-content active" data-step="1">
              <div class="ac-wizard-step-title">
                <span class="ac-wizard-step-number">1</span>
                Why Zone Tracking Matters
              </div>
              <p class="ac-safety-lead">
                This room uses <strong>zone-based automation</strong> for air conditioning. The system knows when you're Home, Away, or Nearby and adjusts cooling automatically to save electricity.
              </p>
              <p class="ac-safety-lead">
                Manual changes at the wrong time can stress the compressor or conflict with automations. Use manual control only when you understand what's running.
              </p>
              <div class="ac-safety-note">
                <strong>Privacy:</strong> Your exact GPS coordinates are never shown on this dashboard or shared with other users. Home Assistant only sees zone-based presence states like "Home", "Away", or "Nearby".
              </div>
            </div>

            <!-- Step 2: Install Companion App -->
            <div class="ac-wizard-step-content" data-step="2">
              <div class="ac-wizard-step-title">
                <span class="ac-wizard-step-number">2</span>
                Install the Companion App
              </div>
              <p class="ac-safety-lead">
                Install <strong>Home Assistant Companion</strong> on your phone to enable zone tracking.
              </p>
              <ul class="ac-safety-steps">
                <li><strong>iPhone:</strong> Download from the <strong>iOS App Store</strong></li>
                <li><strong>Android:</strong> Download from <strong>Google Play</strong></li>
              </ul>
              <p class="ac-safety-lead" style="margin-top: 16px;">
                After installing, sign in to your Home Assistant server using your account credentials.
              </p>
            </div>

            <!-- Step 3: App Permissions -->
            <div class="ac-wizard-step-content" data-step="3">
              <div class="ac-wizard-step-title">
                <span class="ac-wizard-step-number">3</span>
                Configure App Permissions
              </div>
              <p class="ac-safety-lead">
                In the Companion app, configure location settings:
              </p>
              <ul class="ac-safety-steps">
                <li>Open <strong>App Configuration</strong> → <strong>Companion App</strong> → <strong>Location</strong></li>
                <li>Set <strong>Location permission</strong> to <strong>Always</strong> (not "While Using")</li>
                <li>Keep <strong>Location accuracy</strong> on <strong>Full</strong></li>
                <li>Enable <strong>Background refresh</strong></li>
              </ul>
              <details class="ac-safety-disclosure">
                <summary>Show screenshot: Companion app Location</summary>
                <img class="ac-safety-screenshot" loading="lazy" width="390" height="844" alt="Home Assistant Companion Location screen" src="${urlCompanion}">
              </details>
            </div>

            <!-- Step 4: System Settings -->
            <div class="ac-wizard-step-content" data-step="4">
              <div class="ac-wizard-step-title">
                <span class="ac-wizard-step-number">4</span>
                System Location Settings
              </div>
              <p class="ac-safety-lead">
                Configure your phone's system settings to allow precise location:
              </p>
              <ul class="ac-safety-steps">
                <li><strong>iPhone:</strong> Go to <strong>Settings</strong> → <strong>Home Assistant</strong> → <strong>Location</strong> → select <strong>Always</strong></li>
                <li><strong>Android:</strong> Go to <strong>Settings</strong> → <strong>Apps</strong> → <strong>Home Assistant</strong> → <strong>Permissions</strong> → <strong>Location</strong> → select <strong>Allow all the time</strong></li>
                <li>Enable <strong>Precise Location</strong> if your phone offers this option</li>
              </ul>
              <details class="ac-safety-disclosure">
                <summary>Show screenshot: iOS System Location Settings</summary>
                <img class="ac-safety-screenshot" loading="lazy" width="390" height="844" alt="iOS Settings Location Always" src="${urlIos}">
              </details>
              <div class="ac-wizard-privacy-warning">
                <strong>Privacy Notice:</strong> Your exact location is <strong>never shared</strong> with other users or stored by Home Assistant. Only zone-based presence is used (e.g., "John is Home", "John is Away", "John is Nearby"). This powers electricity-saving automations without compromising your privacy.
              </div>
            </div>
          </div>
          <div class="ac-wizard-nav">
            <div class="ac-wizard-nav-left">
              <button type="button" class="ac-wizard-btn ac-wizard-btn-back" style="display: none;">Back</button>
              <button type="button" class="ac-safety-cancel">Cancel</button>
            </div>
            <div class="ac-wizard-nav-right">
              <button type="button" class="ac-wizard-btn ac-wizard-btn-next">Next</button>
              <button type="button" class="ac-safety-ok" disabled></button>
            </div>
          </div>
        </div>
      `;

      const okBtn = overlay.querySelector('.ac-safety-ok');
      const nextBtn = overlay.querySelector('.ac-wizard-btn-next');
      const backBtn = overlay.querySelector('.ac-wizard-btn-back');
      if (okBtn) okBtn.textContent = `${actLabel} ${nameStr}`;

      const updateStep = () => {
        overlay.querySelectorAll('.ac-wizard-step-dot').forEach((dot) => {
          const step = parseInt(dot.dataset.step, 10);
          dot.classList.toggle('active', step === currentStep);
          dot.classList.toggle('completed', step < currentStep);
        });
        overlay.querySelectorAll('.ac-wizard-step-content').forEach((content) => {
          const step = parseInt(content.dataset.step, 10);
          content.classList.toggle('active', step === currentStep);
        });
        backBtn.style.display = currentStep > 1 ? '' : 'none';
        nextBtn.style.display = currentStep < totalSteps ? '' : 'none';
        okBtn.style.display = currentStep === totalSteps ? '' : 'none';
        okBtn.disabled = currentStep !== totalSteps;
      };

      const cleanup = (result) => {
        document.removeEventListener('keydown', onKey);
        overlay.remove();
        resolve(result);
      };

      const onKey = (ev) => {
        if (ev.key === 'Escape') {
          ev.preventDefault();
          cleanup(false);
        }
      };
      document.addEventListener('keydown', onKey);

      backBtn.addEventListener('click', () => {
        if (currentStep > 1) {
          currentStep--;
          updateStep();
        }
      });

      nextBtn.addEventListener('click', () => {
        if (currentStep < totalSteps) {
          currentStep++;
          updateStep();
        }
      });

      overlay.querySelector('.ac-safety-cancel').addEventListener('click', () => cleanup(false));
      okBtn.addEventListener('click', () => cleanup(true));
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) cleanup(false);
      });

      updateStep();
      this.shadowRoot.appendChild(overlay);
      nextBtn.focus();
    });
  }

  _handleZoneHealthIconClick(e) {
    const iconEl = e.target.closest('.room-icon.zone-health-issue');
    if (!iconEl || !this.shadowRoot.contains(iconEl)) return;
    const personEnt = iconEl.dataset.zoneHealthPerson;
    if (!personEnt) return;
    e.preventDefault();
    e.stopPropagation();
    const personKey = (personEnt || '').toLowerCase();
    const personData = this._zoneHealthData?.persons?.find(p => p.entity_id === personKey);
    if (!personData) return;
    this._showZoneHealthPopup(personData);
  }

  _showZoneHealthPopup(personData) {
    const historyDays = this._zoneHealthData?.history_days || 3;
    const windowLabel = historyDays === 1 ? '1 day' : `${historyDays} days`;
    const name = personData.friendly_name || personData.entity_id.replace('person.', '').replace(/_/g, ' ');
    const escHtml = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const checkIcon = '<span style="color: var(--success-color, #4caf50); font-size: 16px;">&#10003;</span>';
    const xIcon = '<span style="color: var(--error-color, #f44336); font-size: 16px;">&#10007;</span>';
    const formatTime = (iso) => iso ? new Date(iso).toLocaleString() : 'Not seen in window';
    const homeIcon = personData.seen_home ? checkIcon : xIcon;
    const nearbyIcon = personData.seen_nearby ? checkIcon : xIcon;
    const awayIcon = personData.seen_away ? checkIcon : xIcon;
    const warmingUp = personData.warming_up === true;
    const warmupEta = personData.warmup_complete_at
      ? new Date(personData.warmup_complete_at).toLocaleString()
      : '';

    let currentStep = 0;
    const steps = [
      {
        title: warmingUp ? 'Zone health warm-up' : 'Zone Tracking Issue',
        content: warmingUp
          ? `
          <p><strong>${escHtml(name)}'s</strong> zone health is still in the <strong>warm-up</strong> period (${escHtml(String(this._zoneHealthData?.history_days || 3))} day window). No alerts are sent until warm-up finishes and Home Assistant has been running for at least 10 minutes.</p>
          ${warmupEta ? `<p style="color: var(--secondary-text-color); font-size: 12px;">Warm-up completes about: <strong>${escHtml(warmupEta)}</strong></p>` : ''}
          <table style="margin-top: 12px; border-collapse: collapse; width: 100%;">
            <tr>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${homeIcon}</td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));"><strong>Home</strong> (recorder ref.)</td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_home)}</td>
            </tr>
            <tr>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${nearbyIcon}</td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));"><strong>Nearby</strong></td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_nearby)}</td>
            </tr>
            <tr>
              <td style="padding: 6px 8px;">${awayIcon}</td>
              <td style="padding: 6px 8px;"><strong>Away</strong></td>
              <td style="padding: 6px 8px; font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_not_home)}</td>
            </tr>
          </table>
        `
          : `
          <p><strong>${escHtml(name)}'s</strong> location tracking isn't set up correctly.</p>
          <p>Within the last <strong>${windowLabel}</strong>, your linked <strong>device_tracker</strong> must show <strong>home</strong>, <strong>nearby</strong>, and <strong>away</strong> in <strong>Home Assistant recorder</strong> (same idea as history for a sensor).</p>
          <table style="margin-top: 12px; border-collapse: collapse; width: 100%;">
            <tr>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${homeIcon}</td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));"><strong>Home</strong></td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_home)}</td>
            </tr>
            <tr>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${nearbyIcon}</td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));"><strong>Nearby</strong></td>
              <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_nearby)}</td>
            </tr>
            <tr>
              <td style="padding: 6px 8px;">${awayIcon}</td>
              <td style="padding: 6px 8px;"><strong>Away</strong></td>
              <td style="padding: 6px 8px; font-size: 11px; color: var(--secondary-text-color);">${formatTime(personData.last_not_home)}</td>
            </tr>
          </table>
          <p style="margin-top: 12px; color: var(--secondary-text-color); font-size: 12px;">
            Person state (reference): <strong>${escHtml(personData.current_state)}</strong>. Home/Nearby/Away above use <strong>recorder history on linked <code>device_tracker.*</code></strong> only.
          </p>
        `,
      },
      {
        title: 'Step 1: Open Companion App',
        content: `
          <p>On <strong>${escHtml(name)}'s</strong> phone:</p>
          <div class="zone-health-popup-fix">
            <ol>
              <li>Open the <strong>Home Assistant Companion</strong> app</li>
              <li>Tap <strong>Settings</strong> (gear icon)</li>
              <li>Select <strong>Companion App</strong></li>
              <li>Tap <strong>Location</strong></li>
            </ol>
          </div>
          <p style="margin-top: 12px; color: var(--secondary-text-color); font-size: 12px;">
            Make sure you're logged into the correct Home Assistant instance.
          </p>
        `,
      },
      {
        title: 'Step 2: Enable Location',
        content: `
          <p>In the <strong>Location</strong> settings:</p>
          <div class="zone-health-popup-fix">
            <ol>
              <li>Enable <strong>Location Enabled</strong></li>
              <li>Set <strong>Location Accuracy</strong> to "Full"</li>
              <li>Enable <strong>Zone Based Tracking</strong></li>
              <li>Enable <strong>Background Location</strong></li>
            </ol>
          </div>
          <p style="margin-top: 12px; color: var(--secondary-text-color); font-size: 12px;">
            "Full" accuracy ensures reliable zone detection.
          </p>
        `,
      },
      {
        title: 'Step 3: System Permissions',
        content: `
          <p>Check the phone's <strong>system settings</strong>:</p>
          <div class="zone-health-popup-fix">
            <h4 style="margin-bottom: 6px;">iOS:</h4>
            <ol style="margin-bottom: 10px;">
              <li>Go to <strong>Settings → Privacy & Security → Location Services</strong></li>
              <li>Find <strong>Home Assistant</strong> and set to "Always"</li>
              <li>Enable <strong>Precise Location</strong></li>
              <li>Go to <strong>Settings → General → Background App Refresh</strong> and enable it</li>
            </ol>
            <h4 style="margin-bottom: 6px;">Android:</h4>
            <ol>
              <li>Go to <strong>Settings → Apps → Home Assistant → Permissions</strong></li>
              <li>Set <strong>Location</strong> to "Allow all the time"</li>
              <li>Enable <strong>Use precise location</strong></li>
              <li>Disable battery optimization for the app</li>
            </ol>
          </div>
        `,
      },
      {
        title: 'Step 4: Verify',
        content: `
          <p>Once configured, <strong>test</strong> the setup:</p>
          <div class="zone-health-popup-fix">
            <ol>
              <li>Leave your home zone completely and wait a minute</li>
              <li>Check that the person's state changes to <strong>"away"</strong> or <strong>"not_home"</strong></li>
              <li>Return toward home and verify the state becomes <strong>"nearby"</strong> when approaching</li>
              <li>Enter home and verify the state becomes <strong>"home"</strong></li>
            </ol>
          </div>
          <p style="margin-top: 12px; color: var(--secondary-text-color); font-size: 12px;">
            After all three states are reported, the zone health alert will clear automatically (within ${windowLabel}).
          </p>
        `,
      },
    ];

    const overlay = document.createElement('div');
    overlay.className = 'zone-health-popup-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');

    const renderStep = () => {
      const step = steps[currentStep];
      const isFirst = currentStep === 0;
      const isLast = currentStep === steps.length - 1;
      overlay.innerHTML = `
        <div class="zone-health-popup">
          <div class="zone-health-popup-header">
            <svg viewBox="0 0 24 24" style="width: 24px; height: 24px; fill: #ff9800; flex-shrink: 0;">
              <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
            </svg>
            <h3>${step.title}</h3>
          </div>
          <div class="zone-health-popup-body">
            ${step.content}
          </div>
          <div class="zone-health-popup-actions" style="justify-content: space-between;">
            <div style="display: flex; gap: 8px;">
              ${!isFirst ? '<button class="btn btn-secondary zone-health-back">Back</button>' : ''}
            </div>
            <div style="display: flex; gap: 8px;">
              ${!isLast ? '<button class="btn btn-primary zone-health-next">Next</button>' : ''}
              <button class="btn ${isLast ? 'btn-primary' : 'btn-secondary'} zone-health-close">${isLast ? 'Done' : 'Close'}</button>
            </div>
          </div>
          <div style="padding: 0 20px 12px; text-align: center;">
            <span style="font-size: 11px; color: var(--secondary-text-color);">Step ${currentStep + 1} of ${steps.length}</span>
          </div>
        </div>
      `;

      overlay.querySelector('.zone-health-close')?.addEventListener('click', cleanup);
      overlay.querySelector('.zone-health-back')?.addEventListener('click', () => {
        if (currentStep > 0) {
          currentStep--;
          renderStep();
        }
      });
      overlay.querySelector('.zone-health-next')?.addEventListener('click', () => {
        if (currentStep < steps.length - 1) {
          currentStep++;
          renderStep();
        }
      });
    };

    const cleanup = () => {
      overlay.remove();
    };

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) cleanup();
    });

    renderStep();
    this.shadowRoot.appendChild(overlay);
  }

  async _sendTestNotification() {
    const personSelect = this.shadowRoot.querySelector('#notify-test-person');
    const typeSelect = this.shadowRoot.querySelector('#notify-test-type');
    const targetPerson = personSelect?.value || '';
    const notificationType = typeSelect?.value || 'budget_hit';

    if (!targetPerson) {
      showToast(this.shadowRoot, 'Please select a target person', 'error');
      return;
    }

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/send_test_notification',
        target_person: targetPerson,
        notification_type: notificationType,
      });
      showToast(this.shadowRoot, 'Test notification sent!', 'success');
    } catch (err) {
      showToast(this.shadowRoot, `Failed to send notification: ${err.message || err}`, 'error');
    }
  }

  async _sendEfficiencyDigestTest() {
    const personSelect = this.shadowRoot.querySelector('#eff-digest-test-person');
    const roomSelect = this.shadowRoot.querySelector('#eff-digest-test-room');
    const targetPerson = personSelect?.value || '';
    const roomId = (roomSelect?.value || '').trim();

    if (!targetPerson) {
      showToast(this.shadowRoot, 'Please select a target person', 'error');
      return;
    }

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/send_efficiency_digest_test',
        target_person: targetPerson,
        room_id: roomId || undefined,
      });
      showToast(this.shadowRoot, 'Efficiency digest test sent!', 'success');
    } catch (err) {
      showToast(this.shadowRoot, `Digest test failed: ${err.message || err}`, 'error');
    }
  }

  async _loadZoneHealthStatus(updateUiContent = true) {
    const contentEl = this.shadowRoot.querySelector('#zone-health-content');
    if (updateUiContent && contentEl) {
      contentEl.innerHTML = '<p style="color: var(--secondary-text-color); font-size: 12px;">Loading...</p>';
    }
    try {
      const data = await this._hass.callWS({ type: 'smart_dashboards/get_zone_health_status' });
      this._zoneHealthData = data;
      if (updateUiContent && contentEl) {
        this._renderZoneHealthStatus(data);
      }
      this._updateRoomCardZoneHealthIndicators();
    } catch (err) {
      if (updateUiContent && contentEl) {
        contentEl.innerHTML = `<p style="color: var(--error-color, #f44336);">Error loading zone health: ${err.message || err}</p>`;
      }
    }
  }

  async _forceRefreshZoneHealth() {
    const contentEl = this.shadowRoot.querySelector('#zone-health-content');
    const btn = this.shadowRoot.querySelector('#zone-health-refresh');
    if (contentEl) {
      contentEl.innerHTML = '<p style="color: var(--secondary-text-color); font-size: 12px;">Refreshing from recorder (linked device_tracker entities)…</p>';
    }
    if (btn) btn.disabled = true;
    try {
      const data = await this._hass.callWS({ type: 'smart_dashboards/refresh_zone_health' });
      this._zoneHealthData = data;
      if (contentEl) {
        this._renderZoneHealthStatus(data);
      }
      this._updateRoomCardZoneHealthIndicators();
    } catch (err) {
      if (contentEl) {
        contentEl.innerHTML = `<p style="color: var(--error-color, #f44336);">Refresh failed: ${err.message || err}</p>`;
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  _startZoneHealthRefresh() {
    if (this._zoneHealthRefreshInterval) return;
    this._loadZoneHealthStatus(false);
    this._zoneHealthRefreshInterval = setInterval(() => {
      this._loadZoneHealthStatus(false);
    }, 60000);
  }

  _stopZoneHealthRefresh() {
    if (this._zoneHealthRefreshInterval) {
      clearInterval(this._zoneHealthRefreshInterval);
      this._zoneHealthRefreshInterval = null;
    }
  }

  _updateRoomCardZoneHealthIndicators() {
    if (!this._zoneHealthData?.persons) return;
    const unhealthyPersons = new Set(
      this._zoneHealthData.persons.filter(p => !p.is_healthy).map(p => p.entity_id)
    );
    this.shadowRoot.querySelectorAll('.room-icon[data-zone-health-person]').forEach(el => {
      const personEnt = el.dataset.zoneHealthPerson;
      if (unhealthyPersons.has(personEnt)) {
        el.classList.add('zone-health-issue');
      } else {
        el.classList.remove('zone-health-issue');
      }
    });
  }

  _renderZoneHealthStatus(data) {
    const contentEl = this.shadowRoot.querySelector('#zone-health-content');
    if (!contentEl) return;
    const {
      persons = [],
      event_log = [],
      history_days = 3,
      recorder_refreshed_at = null,
      required_zones: requiredZonesSnake = {},
      requiredZones: requiredZonesCamel = {},
    } = data;
    const requiredZones = {
      ...requiredZonesCamel,
      ...requiredZonesSnake,
    };
    if (persons.length === 0) {
      contentEl.innerHTML = `
        <p style="color: var(--secondary-text-color); font-size: 12px;">
          No persons are configured for presence tracking. Assign a <strong>Presence person</strong> to rooms to enable zone health monitoring.
        </p>`;
      return;
    }
    const formatTime = (iso) => {
      if (!iso) return '—';
      const d = new Date(iso);
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    };
    const windowLabel = history_days === 1 ? '1 day' : `${history_days} days`;
    const refreshedLine = recorder_refreshed_at
      ? `<p style="font-size: 10px; color: var(--secondary-text-color); margin: 0 0 8px 0;">Last recorder pull: ${new Date(recorder_refreshed_at).toLocaleString()}</p>`
      : '';
    const checkIcon = '<span style="color: var(--success-color, #4caf50);">&#10003;</span>';
    const xIcon = '<span style="color: var(--error-color, #f44336);">&#10007;</span>';
    const zh = {
      entity_id: 'zone.home',
      exists: false,
      setup_hint:
        'Add or restore the default Home zone: Settings → Areas & zones → Zones. The entity should be zone.home.',
      ...(requiredZones.zone_home || requiredZones.zoneHome || {}),
    };
    const zn = {
      entity_id: 'zone.nearby',
      exists: false,
      setup_hint:
        'Create a zone named Nearby so the entity id is zone.nearby: Settings → Areas & zones → Zones → Add zone. See https://www.home-assistant.io/integrations/zone/',
      ...(requiredZones.zone_nearby || requiredZones.zoneNearby || {}),
    };
    const zoneHomeRow = `
      <tr>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">
          <code style="font-size: 11px;">${String(zh.entity_id || 'zone.home').replace(/</g, '&lt;')}</code>
        </td>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); text-align: center; font-size: 14px;">${zh.exists ? checkIcon : xIcon}</td>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">
          ${zh.exists ? 'Present' : (zh.setup_hint || 'Create or restore this zone in Home Assistant.')}
        </td>
      </tr>`;
    const zoneNearbyRow = `
      <tr>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">
          <code style="font-size: 11px;">${String(zn.entity_id || 'zone.nearby').replace(/</g, '&lt;')}</code>
        </td>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); text-align: center; font-size: 14px;">${zn.exists ? checkIcon : xIcon}</td>
        <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; color: var(--secondary-text-color);">
          ${zn.exists ? 'Present' : (zn.setup_hint || 'Create this zone in Home Assistant.')}
        </td>
      </tr>`;
    const requiredZonesBlock = `
      <div style="margin-bottom: 16px;">
        <h3 style="margin: 0 0 8px 0; font-size: 14px;">Required zones</h3>
        <p style="font-size: 11px; color: var(--secondary-text-color); margin: 0 0 8px 0;">
          Companion zone reporting expects <code>zone.home</code> and a dedicated <code>zone.nearby</code>. Green = entity exists in Home Assistant.
        </p>
        <div style="overflow-x: auto;">
          <table style="width: 100%; max-width: 640px; border-collapse: collapse; font-size: 12px;">
            <thead>
              <tr style="text-align: left;">
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Entity</th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2)); text-align: center; width: 56px;">OK</th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Note</th>
              </tr>
            </thead>
            <tbody>${zoneHomeRow}${zoneNearbyRow}</tbody>
          </table>
        </div>
      </div>`;
    const personsHtml = persons
      .map(p => {
        const warmingUp = p.warming_up === true;
        const etaRaw = p.warmup_complete_at;
        const etaLine =
          warmingUp && etaRaw
            ? `<div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Alerts start after: ${formatTime(etaRaw)}</div>`
            : warmingUp
              ? '<div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Collecting history — alerts disabled during warm-up.</div>'
              : '';
        const statusColor = warmingUp
          ? 'var(--warning-color, #ff9800)'
          : p.is_healthy
            ? 'var(--success-color, #4caf50)'
            : 'var(--error-color, #f44336)';
        const statusText = warmingUp
          ? 'Warming up'
          : p.is_healthy
            ? 'Healthy'
            : 'Unhealthy';
        const alertBadge = p.is_alerted
          ? '<span style="background: var(--warning-color, #ff9800); color: #000; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 8px;">ALERTED</span>'
          : '';
        const trackers = Array.isArray(p.device_trackers) ? p.device_trackers : [];
        const trackersLine = trackers.length
          ? `<div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Trackers: ${trackers.map(t => `<code style="font-size: 9px;">${String(t).replace(/</g, '&lt;')}</code>`).join(', ')}</div>`
          : '<div style="font-size: 10px; color: var(--warning-color, #ff9800); margin-top: 4px;">No linked device_tracker on person — link the Companion device under People.</div>';
        const homeCheck = p.seen_home ? checkIcon : xIcon;
        const nearbyCheck = p.seen_nearby ? checkIcon : xIcon;
        const awayCheck = p.seen_away ? checkIcon : xIcon;
        return `
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">
            <strong>${p.friendly_name}</strong>
            <div style="font-size: 10px; color: var(--secondary-text-color);">${p.entity_id}</div>
            ${trackersLine}
          </td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); text-transform: capitalize;">${p.current_state}
            <div style="font-size: 9px; color: var(--secondary-text-color); margin-top: 2px;">person entity</div>
          </td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">
            <span style="color: ${statusColor}; font-weight: 500;">${statusText}</span>${alertBadge}${etaLine}
          </td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; text-align: center;">${homeCheck}<div style="font-size: 10px; color: var(--secondary-text-color);">${formatTime(p.last_home)}</div></td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; text-align: center;">${nearbyCheck}<div style="font-size: 10px; color: var(--secondary-text-color);">${formatTime(p.last_nearby)}</div></td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; text-align: center;">${awayCheck}<div style="font-size: 10px; color: var(--secondary-text-color);">${formatTime(p.last_not_home)}</div></td>
          <td style="padding: 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px;">${formatTime(p.last_alert_time)}</td>
        </tr>`;
      })
      .join('');
    const eventsHtml = event_log.length === 0
      ? '<p style="color: var(--secondary-text-color); font-size: 12px;">No zone health events recorded yet.</p>'
      : `<table style="width: 100%; border-collapse: collapse; font-size: 12px;">
          <thead>
            <tr style="text-align: left;">
              <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Time</th>
              <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Person</th>
              <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Event</th>
              <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Message</th>
            </tr>
          </thead>
          <tbody>
            ${event_log.slice().reverse().slice(0, 50).map(e => {
              const eventLabel = {
                push_sent: 'Push Sent',
                tts_sent: 'TTS Sent',
                tts_failed: 'TTS Failed',
                tts_skipped: 'TTS Skipped',
                recovered: 'Recovered',
              }[e.event] || e.event;
              const eventColor = e.event === 'recovered' ? 'var(--success-color, #4caf50)'
                : e.event.includes('failed') || e.event.includes('skipped') ? 'var(--error-color, #f44336)'
                : 'var(--primary-text-color)';
              return `
                <tr>
                  <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${formatTime(e.ts)}</td>
                  <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1));">${e.person_name || e.person_entity || '?'}</td>
                  <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); color: ${eventColor};">${eventLabel}</td>
                  <td style="padding: 6px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.1)); font-size: 11px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${e.message || ''}</td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>`;
    contentEl.innerHTML = `
      ${requiredZonesBlock}
      <div style="margin-bottom: 16px;">
        <h3 style="margin: 0 0 8px 0; font-size: 14px;">Person Status</h3>
        ${refreshedLine}
        <p style="font-size: 11px; color: var(--secondary-text-color); margin-bottom: 8px;">
          History window: <strong>${windowLabel}</strong>. <strong>Home / Nearby / Away</strong> columns = latest HA <strong>recorder</strong> pull on linked <code>device_tracker.*</code> (reference). After warm-up, the <strong>Health</strong> column follows the <strong>JSON snapshot</strong> file, not these cells alone.
        </p>
        <div style="overflow-x: auto;">
          <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
            <thead>
              <tr style="text-align: left;">
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Person</th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Current</th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Health</th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2)); text-align: center;">Home<br><span style="font-weight: normal; font-size: 9px; color: var(--secondary-text-color);">recorder</span></th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2)); text-align: center;">Nearby<br><span style="font-weight: normal; font-size: 9px; color: var(--secondary-text-color);">recorder</span></th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2)); text-align: center;">Away<br><span style="font-weight: normal; font-size: 9px; color: var(--secondary-text-color);">recorder</span></th>
                <th style="padding: 8px; border-bottom: 2px solid var(--divider-color, rgba(255,255,255,0.2));">Last Alert</th>
              </tr>
            </thead>
            <tbody>${personsHtml}</tbody>
          </table>
        </div>
      </div>
      <details class="settings-fold">
        <summary class="settings-fold-summary">Event Log (${event_log.length} events)</summary>
        <div class="settings-fold-body" style="padding-top: 12px;">
          ${eventsHtml}
        </div>
      </details>`;
  }

  _renderRoomSettings(room, index, mediaPlayers, powerSensors) {
    const iconStored = this._roomIconStoredValue(room);
    const iconEffective = this._effectiveRoomIcon(room);
    const personEnt = (room.presence_person_entity || '').trim();
    const personEsc = personEnt.replace(/"/g, '&quot;');
    const presLive =
      personEnt.startsWith('person.')
        ? `<div class="room-settings-presence-live room-settings-presence-live--header" data-presence-person="${personEsc}">
        <span class="room-settings-presence-live-text">Loading…</span>
      </div>`
        : '';
    return `
      <div class="room-settings-card" data-room-index="${index}" draggable="false">
        <div class="room-settings-header">
          <div class="room-settings-header-start">
            <div class="room-drag-handle" title="Drag to reorder rooms">
              <svg viewBox="0 0 24 24">${icons.menu}</svg>
            </div>
            <input type="hidden" class="room-icon-mdi" value="${iconStored.replace(/"/g, '&quot;')}">
            <button type="button" class="room-icon-picker-trigger" data-room-index="${index}" aria-label="Choose room icon" title="Room icon">
              <ha-icon icon="${iconEffective.replace(/"/g, '&quot;')}"></ha-icon>
            </button>
            <input type="text" class="form-input room-name-input" value="${room.name}" placeholder="Room name">
          </div>
          <div class="room-settings-header-presence">${presLive}</div>
          <div class="room-settings-header-actions">
            <button class="btn btn-secondary toggle-room-btn" data-index="${index}">Edit</button>
            <button class="btn btn-primary room-save-btn" data-index="${index}" title="Save this room">
              <svg class="btn-icon" viewBox="0 0 24 24" style="width: 14px; height: 14px;">${icons.check}</svg>
              Save
            </button>
            <button class="icon-btn danger remove-room-btn" data-index="${index}">
              <svg viewBox="0 0 24 24">${icons.delete}</svg>
            </button>
          </div>
        </div>

        <div class="room-settings-body" id="room-body-${index}" style="display: none;">
          ${this._renderResponsiveLightWarnings(room, index)}
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">Media Player</label>
              <select class="form-select room-media-player">
                <option value="">None</option>
                ${mediaPlayers.map(mp => `
                  <option value="${mp.entity_id}" ${room.media_player === mp.entity_id ? 'selected' : ''}>
                    ${mp.friendly_name}
                  </option>
                `).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Room Threshold (W)</label>
              <input type="number" class="form-input room-threshold" value="${room.threshold || ''}" placeholder="0" min="0">
            </div>
            <div class="form-group">
              <label class="form-label">Daily kWh Budget (freebie)</label>
              <input type="number" class="form-input room-kwh-budget" value="${room.kwh_budget ?? 5}" placeholder="5" min="0" step="0.5">
              <div class="tts-msg-desc" style="margin-top: 4px;">No warnings or shutoffs until room uses this much today. 0 = always enforce.</div>
              <label class="form-checkbox-row" style="margin-top: 10px; display: flex; align-items: flex-start; gap: 8px; cursor: pointer;">
                <input type="checkbox" class="room-kwh-budget-use-boost" ${room.kwh_budget_use_boost !== false ? 'checked' : ''} style="margin-top: 2px;">
                <span class="tts-msg-desc" style="margin: 0;">Apply global budget boost on boost days (Enforcement → schedule)</span>
              </label>
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">TTS Volume</label>
            <div class="volume-control">
              <input type="range" class="volume-slider room-volume" min="0" max="1" step="0.05" value="${room.volume || 0.7}">
              <span class="volume-value room-volume-display">${Math.round((room.volume || 0.7) * 100)}%</span>
            </div>
          </div>

          ${this._renderRoomPresenceSection(room, index)}

          <div class="divider"></div>

          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <h4 style="margin: 0; font-size: 11px; color: var(--secondary-text-color);">Devices</h4>
            <div class="add-device-dropdown" data-room-index="${index}">
              <button class="btn btn-secondary add-device-trigger">
                <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
                Add
              </button>
              <div class="add-device-menu" style="display: none;">
                <button class="add-device-option" data-type="outlet">Outlet</button>
                <button class="add-device-option" data-type="single_outlet">Single Outlet</button>
                <button class="add-device-option" data-type="stove">Stove</button>
                <button class="add-device-option" data-type="microwave">Microwave</button>
                <button class="add-device-option" data-type="minisplit">Mini-Split (Heater/AC)</button>
                <button class="add-device-option" data-type="fridge">Fridge</button>
                <button class="add-device-option" data-type="vent">Vent</button>
                <button class="add-device-option" data-type="wall_heater">Wall heater</button>
                <button class="add-device-option" data-type="light">Light</button>
              </div>
            </div>
          </div>

          <div class="outlets-settings-list" id="outlets-list-${index}">
            ${(room.outlets || []).map((outlet, oi) => this._renderDeviceSettings(outlet, oi, powerSensors, index, room.outlets || [])).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderDeviceSettings(device, deviceIndex, powerSensors, roomIndex, roomOutlets = [], isCollapsed = true) {
    const type = device.type || 'outlet';
    if (type === 'stove' || type === 'microwave') {
      return this._renderApplianceSettings(device, deviceIndex, powerSensors, roomIndex, type, roomOutlets, isCollapsed);
    }
    if (type === 'minisplit') {
      return this._renderMinisplitSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed);
    }
    if (type === 'fridge') {
      return this._renderFridgeSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed);
    }
    if (isVentLikeType(type)) {
      const kind = type === 'wall_heater' ? 'wall_heater' : 'vent';
      return this._renderVentLikeSettings(device, deviceIndex, powerSensors, roomIndex, kind, isCollapsed);
    }
    if (type === 'light') {
      return this._renderLightSettings(device, deviceIndex, roomIndex, isCollapsed);
    }
    return this._renderOutletSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed);
  }

  /** One mapped light.* row card for light device settings (save uses .light-entity-row, .light-entity-select, etc.). */
  _htmlLightMappedRow(zeroBasedIdx, row, roomIndex) {
    const n = zeroBasedIdx + 1;
    const ac = this._renderEntityAutocomplete(
      row.entity_id || '',
      'light',
      roomIndex,
      'light-entity-select',
      'light.bathroom_light',
    );
    const w = Math.max(0, parseInt(row.watts, 10) || 0);
    const wrgb = row.wrgb ? 'checked' : '';
    return `
      <div class="light-entity-row light-entity-card" data-row-index="${zeroBasedIdx}">
        <div class="light-entity-card-header">
          <span class="light-entity-card-title">Light ${n}</span>
          <button type="button" class="icon-btn danger light-entity-remove-btn" title="Remove light"><svg viewBox="0 0 24 24">${icons.delete}</svg></button>
        </div>
        <div class="form-group">
          <label class="form-label">Light entity</label>
          ${ac}
          <div class="tts-msg-desc" style="margin-top: 4px;">A light.* bulb or group. Used for room totals and WRGB warnings.</div>
        </div>
        <div class="light-entity-power-wrgb">
          <div class="form-group">
            <label class="form-label">Max power (W)</label>
            <input type="number" class="form-input light-entity-watts" value="${w}" min="0" max="500" step="1" placeholder="0" title="Running power when on">
            <div class="tts-msg-desc" style="margin-top: 4px;">Used when measuring power from configured wattage (not sensor mode).</div>
          </div>
          <div class="form-group light-entity-wrgb-block">
            <label class="toggle-row" style="margin-bottom: 0;">
              <input type="checkbox" class="form-checkbox light-entity-wrgb-toggle" ${wrgb} title="WRGB-capable light">
              <span class="toggle-label">WRGB light</span>
            </label>
            <div class="tts-msg-desc" style="margin-top: 6px;">Enable for responsive color warnings on white/RGB-capable lights.</div>
          </div>
        </div>
      </div>
    `;
  }

  _renderLightSettings(device, deviceIndex, roomIndex, isCollapsed = true) {
    const displayName = device.name || 'Unnamed Light';
    const lightPowerSource = device.power_source === 'sensor' ? 'sensor' : 'configured';
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    // light_entities: list of { entity_id, watts, wrgb } (legacy: list of strings -> [{ entity_id, watts: 0, wrgb: false }])
    let lightEntityRows = [];
    const raw = device.light_entities;
    if (Array.isArray(raw)) {
      lightEntityRows = raw.map(e => typeof e === 'object' && e?.entity_id
        ? { entity_id: e.entity_id, watts: Math.max(0, parseInt(e.watts, 10) || 0), wrgb: !!e.wrgb }
        : typeof e === 'string' && e.startsWith('light.') ? { entity_id: e, watts: 0, wrgb: false } : null
      ).filter(Boolean);
    } else if (typeof raw === 'string' && raw.trim()) {
      lightEntityRows = raw.split(',').map(e => e.trim()).filter(e => e.startsWith('light.')).map(e => ({ entity_id: e, watts: 0, wrgb: false }));
    }
    if (lightEntityRows.length === 0) lightEntityRows = [{ entity_id: '', watts: 0, wrgb: false }];

    const lightRowsHtml = lightEntityRows
      .map((row, idx) => this._htmlLightMappedRow(idx, row, roomIndex))
      .join('');

    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${deviceIndex}" data-room-index="${roomIndex}" data-device-type="light" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0-4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${device.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${deviceIndex}" title="Delete">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">Light Name</label>
              <input type="text" class="form-input outlet-name" value="${device.name || ''}" placeholder="Light name...">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Switch & Lights</div>
              <p class="tts-msg-desc" style="margin: 0 0 10px 0;">The relay (<code style="font-size: 9px;">switch.*</code>) controls room power on/off. Mapped lights (<code style="font-size: 9px;">light.*</code>) below define wattage for totals and WRGB behavior.</p>
              <div class="form-group">
                <label class="form-label">Room relay (switch)</label>
                ${this._renderEntityAutocomplete(device.switch_entity || '', 'switch', roomIndex, 'light-switch-entity', 'switch.hallway_switch')}
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">switch.* only. Type to search.</div>
              </div>
              <div class="form-group">
                <label class="form-label">How to measure power</label>
                <select class="form-input light-power-source">
                  <option value="configured" ${lightPowerSource === 'configured' ? 'selected' : ''}>Configured wattage (per light below)</option>
                  <option value="sensor" ${lightPowerSource === 'sensor' ? 'selected' : ''}>Power sensor</option>
                </select>
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Sensor mode uses one entity for live watts (like outlets). Mapped lights below stay available for WRGB responsive warnings.</div>
              </div>
              <div class="light-power-sensor-block" style="display: ${lightPowerSource === 'sensor' ? 'block' : 'none'};">
                <div class="form-group">
                  <label class="form-label">Power sensor or smart switch</label>
                  ${this._renderEntityAutocomplete(device.power_sensor_entity || '', 'power_watts', roomIndex, 'light-power-sensor-entity', 'sensor.bathroom_lights_power')}
                  <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">sensor.* or switch.* with power (e.g. smart plug reporting watts).</div>
                </div>
              </div>
              <div class="form-group">
                <label class="form-label">Mapped lights</label>
                <div class="light-entity-rows">
                  ${lightRowsHtml}
                </div>
                <button type="button" class="btn btn-secondary light-entity-add-btn" style="margin-top: 8px;">+ Add light</button>
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Each row is one light.* entity and its max watts when on.</div>
              </div>
              <button type="button" class="btn btn-secondary light-test-switch-btn" data-switch="${(device.switch_entity || '').replace(/"/g, '&quot;')}" title="Pulse the room relay on/off">
                <svg viewBox="0 0 24 24">${icons.power}</svg>
                <span>Test switch</span>
              </button>
              ${this._renderPresenceAutoOffRow(
                'presence-auto-off-appliance',
                !!device.presence_auto_off,
                'Uses room Presence & zones. Targets the switch entity above.',
              )}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderMinisplitSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed = true) {
    const displayName = device.name || 'Unnamed Mini-Split';
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${deviceIndex}" data-room-index="${roomIndex}" data-device-type="minisplit" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0 4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${device.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${deviceIndex}" title="Delete">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">Mini-Split Name</label>
              <input type="text" class="form-input outlet-name" value="${device.name || ''}" placeholder="Mini-Split name...">
            </div>
            <div class="form-group">
              <label class="form-label">Warn Limit</label>
              <input type="number" class="form-input outlet-threshold" value="${device.threshold || ''}" placeholder="W" min="0" style="width: 70px;">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Power Sensor</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                ${this._renderEntityAutocomplete(device.plug1_entity || '', 'sensor', roomIndex, 'outlet-plug1', 'sensor.kitchen_power')}
              </div>
              <div class="form-group">
                <label class="form-label">Switch</label>
                ${this._renderEntityAutocomplete(device.plug1_switch || '', 'switch', roomIndex, 'outlet-plug1-switch', 'switch.kitchen_outlet')}
              </div>
              <div class="shutoff-row">
                <div class="form-group">
                  <label class="form-label">Shutoff (W)</label>
                  <input type="number" class="form-input outlet-plug1-shutoff" value="${device.plug1_shutoff || ''}" placeholder="Off" min="0">
                </div>
                <button class="test-switch-btn" data-switch="${device.plug1_switch || ''}" title="Test switch">
                  <svg viewBox="0 0 24 24">${icons.power}</svg>
                </button>
              </div>
              <div class="form-group" style="margin-top: 12px;">
                <label class="form-label">Enforcement minimum off (seconds)</label>
                <input type="number" class="form-input minisplit-enforcement-off-seconds" value="${device.minisplit_enforcement_off_seconds ?? 60}" min="30" max="600" style="width: 90px;">
                <div class="tts-var-help" style="margin-top: 4px;">Compressor safety: stays off at least this long before other steps. Power restores only when room total is under the room threshold.</div>
              </div>
              <div class="form-group">
                <label class="form-label">Min watts to count as HVAC load (0 = off)</label>
                <input type="number" class="form-input minisplit-enforcement-min-watts" value="${device.minisplit_enforcement_min_watts ?? 0}" min="0" max="2000" style="width: 90px;">
                <div class="tts-var-help" style="margin-top: 4px;">If set, reported plug power must be at least this high to qualify for mini-split-first enforcement (ignores low fan-only draw when math alone would qualify).</div>
              </div>
              ${this._renderPresenceAutoOffRow(
                'presence-auto-off-appliance',
                !!device.presence_auto_off,
                'Uses room Presence & zones. Turns plug switch off when away and can turn it back on when returning if this feature turned it off. Opt-in: use with care for HVAC.',
              )}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderFridgeSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed = true) {
    const displayName = device.name || 'Unnamed Fridge';
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${deviceIndex}" data-room-index="${roomIndex}" data-device-type="fridge" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0 4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${device.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${deviceIndex}" title="Delete">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">Fridge Name</label>
              <input type="text" class="form-input outlet-name" value="${device.name || ''}" placeholder="Fridge name...">
            </div>
            <div class="form-group">
              <label class="form-label">Warn Limit</label>
              <input type="number" class="form-input outlet-threshold" value="${device.threshold || ''}" placeholder="W" min="0" style="width: 70px;">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Power Sensor</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                ${this._renderEntityAutocomplete(device.plug1_entity || '', 'sensor', roomIndex, 'outlet-plug1', 'sensor.fridge_power')}
              </div>
              ${this._renderPresenceAutoOffRow(
                'presence-auto-off-appliance',
                !!device.presence_auto_off,
                'Fridges usually have no switch; this is saved but has no effect until a switch is configured for this device.',
              )}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderVentLikeSettings(device, deviceIndex, powerSensors, roomIndex, applianceKind, isCollapsed = true) {
    const isWallHeater = applianceKind === 'wall_heater';
    const displayName = device.name || (isWallHeater ? 'Unnamed wall heater' : 'Unnamed vent');
    const ventPowerSource = device.power_source === 'sensor' ? 'sensor' : 'configured';
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    const nameLabel = isWallHeater ? 'Wall heater name' : 'Vent name';
    const ventTitle = isWallHeater ? 'Wall heater' : 'Vent';
    const ventAutomationSection = !isWallHeater ? `
      <div class="divider" style="margin: 16px 0;"></div>
      <div class="plug-settings-title">Vent automation</div>
      <p class="tts-msg-desc" style="margin-bottom: 12px;">Optional: turn the switch on when the presence sensor is active (after debounce), and off after no presence for the duration below. Auto-off only applies when this automation turned the switch on.</p>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="toggle-row">
          <input type="checkbox" class="form-checkbox vent-automation-enabled" ${device.vent_automation_enabled ? 'checked' : ''}>
          <span class="toggle-label">Enable presence-based vent control</span>
        </label>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Presence sensor</label>
        ${this._renderEntityAutocomplete(device.vent_presence_entity || '', 'binary_sensor', roomIndex, 'vent-presence-entity', 'binary_sensor.bathroom_motion')}
        <div class="tts-msg-desc" style="margin-top: 4px;">binary_sensor.* (motion, occupancy, etc.)</div>
      </div>
      <div class="grid-2" style="margin-bottom: 12px;">
        <div class="form-group">
          <label class="form-label">On debounce (seconds)</label>
          <input type="number" class="form-input vent-on-debounce-seconds" value="${device.vent_on_debounce_seconds ?? 30}" min="0" max="600" step="1">
          <div class="tts-msg-desc" style="margin-top: 4px;">Presence must stay active this long before turning on</div>
        </div>
        <div class="form-group">
          <label class="form-label">Off after no presence (seconds)</label>
          <input type="number" class="form-input vent-off-after-no-presence-seconds" value="${device.vent_off_after_no_presence_seconds ?? 300}" min="10" max="86400" step="1">
          <div class="tts-msg-desc" style="margin-top: 4px;">Turn off after presence clears for this long</div>
        </div>
      </div>
    ` : '';
    const heaterComfortVal = device.heater_comfort_temperature != null && device.heater_comfort_temperature !== ''
      ? device.heater_comfort_temperature
      : '';
    const heaterAutomationSection = isWallHeater ? `
      <div class="divider" style="margin: 16px 0;"></div>
      <div class="plug-settings-title">Heater automation</div>
      <p class="tts-msg-desc" style="margin-bottom: 12px;"><strong>Smart mode:</strong> Automation uses comfort temperature as the target (with hysteresis). The "turn on below" threshold only guards manual turn-on from the dashboard. Manual turns also stop early if comfort is reached. Decimals are ignored for threshold checks (66.9° triggers "66 or below"). Advanced settings enable weather-aware pre-heating, duty cycling, and power-aware pausing.</p>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="toggle-row">
          <input type="checkbox" class="form-checkbox heater-automation-enabled" ${device.heater_automation_enabled ? 'checked' : ''}>
          <span class="toggle-label">Enable heater automation</span>
        </label>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Temperature sensor</label>
        ${this._renderEntityAutocomplete(device.heater_temperature_entity || '', 'sensor', roomIndex, 'heater-temperature-entity', 'sensor.room_temperature')}
      </div>
      <div class="grid-2" style="margin-bottom: 12px;">
        <div class="form-group">
          <label class="form-label">Turn on at or below (°)</label>
          <input type="number" class="form-input heater-on-below-temperature" value="${device.heater_on_below_temperature ?? 65}" min="-60" max="160" step="0.1">
          <div class="tts-msg-desc" style="margin-top: 4px;">Matches your sensor unit (°F or °C)</div>
        </div>
        <div class="form-group">
          <label class="form-label">Stay on (minutes)</label>
          <input type="number" class="form-input heater-stay-on-minutes" value="${device.heater_stay_on_minutes ?? 5}" min="1" max="240" step="1">
        </div>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Comfort temperature (°)</label>
        <input type="number" class="form-input heater-comfort-temperature" value="${heaterComfortVal}" placeholder="default: turn-on + 2" min="-60" max="160" step="0.1">
        <div class="tts-msg-desc" style="margin-top: 4px;">After each stay period, if temp is at or above this, the heater turns off. Leave empty to use turn-on threshold + 2°.</div>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="toggle-row">
          <input type="checkbox" class="form-checkbox heater-presence-optional-enabled" ${device.heater_presence_optional_enabled ? 'checked' : ''}>
          <span class="toggle-label">Require presence to turn on</span>
        </label>
        <div class="tts-msg-desc" style="margin-top: 4px;">When off, heater turns on whenever temperature is low enough. When on, a presence sensor must also be active.</div>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="toggle-row">
          <input type="checkbox" class="form-checkbox heater-presence-turn-on-enabled" ${device.heater_presence_turn_on_enabled ? 'checked' : ''}>
          <span class="toggle-label">Turn on when presence activates</span>
        </label>
        <div class="tts-msg-desc" style="margin-top: 4px;">On a rising edge of the presence sensor, if temperature is at or below the turn-on threshold, start the same heat cycle (comfort re-check rules apply). Uses the presence sensor and cooldown below when "require presence" is on.</div>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Presence sensor</label>
        ${this._renderEntityAutocomplete(device.heater_presence_entity || '', 'binary_sensor', roomIndex, 'heater-presence-entity', 'binary_sensor.room_motion')}
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Presence cooldown (seconds)</label>
        <input type="number" class="form-input heater-presence-cooldown-seconds" value="${device.heater_presence_cooldown_seconds ?? 60}" min="0" max="7200" step="1">
        <div class="tts-msg-desc" style="margin-top: 4px;">After an automation turn-on, ignore a new presence trigger within this window (only when require presence is on)</div>
      </div>
      <div class="plug-settings-title" style="margin-top: 12px;">Door and window</div>
      <p class="tts-msg-desc" style="margin-bottom: 10px;">Optional: block heater on (manual and automation) while either sensor reports open.</p>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Door sensor (optional)</label>
        ${this._renderEntityAutocomplete(device.heater_door_sensor_entity || '', 'binary_sensor', roomIndex, 'heater-door-sensor-entity', 'binary_sensor.bathroom_door')}
        <div class="tts-msg-desc" style="margin-top: 4px;">Heater will not turn on if door is open</div>
      </div>
      <div class="form-group" style="margin-bottom: 12px;">
        <label class="form-label">Window sensor (optional)</label>
        ${this._renderEntityAutocomplete(device.heater_window_sensor_entity || '', 'binary_sensor', roomIndex, 'heater-window-sensor-entity', 'binary_sensor.bathroom_window')}
        <div class="tts-msg-desc" style="margin-top: 4px;">Heater will not turn on if window is open</div>
      </div>
      <details style="margin-top: 16px;">
        <summary style="cursor: pointer; font-weight: 500; color: var(--primary-text-color); margin-bottom: 8px;">Advanced Optimization</summary>
        <div style="padding-left: 12px; border-left: 2px solid var(--divider-color); margin-top: 8px;">
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Weather / Outdoor Temp Entity</label>
            ${this._renderEntityAutocomplete(device.heater_weather_entity || '', 'weather', roomIndex, 'heater-weather-entity', 'weather.home')}
            <div class="tts-msg-desc" style="margin-top: 4px;">weather.* for forecast-based pre-heating, or sensor.* for outdoor temp</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row">
              <input type="checkbox" class="form-checkbox heater-optimization-enabled" ${device.heater_optimization_enabled !== false ? 'checked' : ''}>
              <span class="toggle-label">Enable smart optimization</span>
            </label>
            <div class="tts-msg-desc" style="margin-top: 4px;">Uses comfort temp for automation (threshold only guards manual), adds hysteresis and other optimizations</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Hysteresis band (°)</label>
            <input type="number" class="form-input heater-hysteresis-band" value="${device.heater_hysteresis_band ?? 2}" min="0" max="10" step="0.5">
            <div class="tts-msg-desc" style="margin-top: 4px;">Turn on at comfort minus this value, turn off at comfort</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row">
              <input type="checkbox" class="form-checkbox heater-duty-cycle-enabled" ${device.heater_duty_cycle_enabled ? 'checked' : ''}>
              <span class="toggle-label">Enable duty cycling</span>
            </label>
            <div class="tts-msg-desc" style="margin-top: 4px;">Run heater in bursts to save energy while maintaining comfort</div>
          </div>
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">On time (minutes)</label>
              <input type="number" class="form-input heater-duty-on-minutes" value="${device.heater_duty_on_minutes ?? 5}" min="1" max="30" step="1">
            </div>
            <div class="form-group">
              <label class="form-label">Pause time (minutes)</label>
              <input type="number" class="form-input heater-duty-off-minutes" value="${device.heater_duty_off_minutes ?? 2}" min="1" max="15" step="1">
            </div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Comfort margin (°)</label>
            <input type="number" class="form-input heater-duty-comfort-margin" value="${device.heater_duty_comfort_margin ?? 1.0}" min="0" max="10" step="0.5">
            <div class="tts-msg-desc" style="margin-top: 4px;">Only use duty cycling within this margin of comfort temp; run continuously when colder</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row">
              <input type="checkbox" class="form-checkbox heater-power-aware-enabled" ${device.heater_power_aware_enabled ? 'checked' : ''}>
              <span class="toggle-label">Power-aware heating</span>
            </label>
            <div class="tts-msg-desc" style="margin-top: 4px;">Pause heating when whole-home power draw is high</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Pause heating above (watts)</label>
            <input type="number" class="form-input heater-power-threshold-watts" value="${device.heater_power_threshold_watts ?? 500}" min="100" max="5000" step="50">
            <div class="tts-msg-desc" style="margin-top: 4px;">Whole-home power threshold (excluding this heater) that triggers pause</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row">
              <input type="checkbox" class="form-checkbox heater-learning-enabled" ${device.heater_learning_enabled !== false ? 'checked' : ''}>
              <span class="toggle-label">Learn room thermal characteristics</span>
            </label>
            <div class="tts-msg-desc" style="margin-top: 4px;">Track heating/cooling rates to optimize performance over time</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Pre-heat ahead of forecast (minutes)</label>
            <input type="number" class="form-input heater-preheat-minutes" value="${device.heater_preheat_minutes ?? 30}" min="0" max="120" step="5">
            <div class="tts-msg-desc" style="margin-top: 4px;">Start heating this far ahead of a forecasted cold spell (requires weather entity)</div>
          </div>
        </div>
      </details>
    ` : '';
    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${deviceIndex}" data-room-index="${roomIndex}" data-device-type="${applianceKind}" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0 4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${device.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${deviceIndex}" title="Delete">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">${nameLabel}</label>
              <input type="text" class="form-input outlet-name" value="${device.name || ''}" placeholder="${ventTitle} name...">
            </div>
            <div class="form-group">
              <label class="form-label">Warn Limit</label>
              <input type="number" class="form-input outlet-threshold" value="${device.threshold || ''}" placeholder="W" min="0" style="width: 70px;">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Switch & Power</div>
              <div class="form-group">
                <label class="form-label">Switch entity</label>
                ${this._renderEntityAutocomplete(device.switch_entity || '', 'switch', roomIndex, 'ceiling-vent-switch', 'switch.bathroom_vent')}
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">On/off state for this ${ventTitle.toLowerCase()}</div>
              </div>
              <div class="form-group">
                <label class="form-label">How to measure power</label>
                <select class="form-input ceiling-vent-power-source">
                  <option value="configured" ${ventPowerSource === 'configured' ? 'selected' : ''}>Fixed watts when on</option>
                  <option value="sensor" ${ventPowerSource === 'sensor' ? 'selected' : ''}>Power sensor</option>
                </select>
              </div>
              <div class="ceiling-vent-power-sensor-block" style="display: ${ventPowerSource === 'sensor' ? 'block' : 'none'};">
                <div class="form-group">
                  <label class="form-label">Power sensor or smart switch</label>
                  ${this._renderEntityAutocomplete(device.power_sensor_entity || '', 'power_watts', roomIndex, 'ceiling-vent-power-sensor-entity', 'sensor.bathroom_vent_power')}
                  <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">sensor.* or switch.* with power reading.</div>
                </div>
              </div>
              <div class="ceiling-vent-watts-block" style="display: ${ventPowerSource === 'configured' ? 'block' : 'none'};">
                <div class="form-group">
                  <label class="form-label">Power when on (W)</label>
                  <input type="number" class="form-input ceiling-vent-watts" value="${device.watts_when_on || ''}" placeholder="e.g. 25" min="0" max="500">
                  <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Predefined draw when switch is on</div>
                </div>
              </div>
              <button type="button" class="btn btn-secondary light-test-switch-btn" data-switch="${(device.switch_entity || '').replace(/"/g, '&quot;')}" title="Pulse the switch on/off">
                <svg viewBox="0 0 24 24">${icons.power}</svg>
                <span>Test switch</span>
              </button>
              ${this._renderPresenceAutoOffRow(
                'presence-auto-off-appliance',
                !!device.presence_auto_off,
                'Uses room Presence & zones. Targets the switch above.',
              )}
              ${ventAutomationSection}
              ${heaterAutomationSection}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderApplianceSettings(device, deviceIndex, powerSensors, roomIndex, deviceType, roomOutlets = [], isCollapsed = true) {
    const displayName = device.name || (deviceType === 'stove' ? 'Unnamed Stove' : 'Unnamed Microwave');
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    const hasStoveInRoom = roomOutlets.some(o => (o.type || '') === 'stove');
    const stoveInRoom = roomOutlets.find(o => (o.type || '') === 'stove');
    const hasStoveSafetyEnabled = stoveInRoom ? (stoveInRoom.stove_safety_enabled !== false) : false;

    const stoveSafetyFields = deviceType === 'stove' ? `
          <div class="divider" style="margin: 16px 0;"></div>
          <div class="plug-settings-title" style="margin-bottom: 12px;">Stove Safety</div>
          <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">Configure unattended cooking monitoring. Uses TTS messages from TTS Settings.</p>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row">
              <input type="checkbox" class="form-checkbox stove-safety-enabled" ${device.stove_safety_enabled !== false ? 'checked' : ''}>
              <span class="toggle-label">Enable stove safety shutoff</span>
            </label>
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">When ON: timer runs, TTS plays, and stove auto-shuts off after final warning. When OFF: TTS only, no shutoff.</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Stove Plug Switch</label>
            ${this._renderEntityAutocomplete(device.plug1_switch || '', 'switch', roomIndex, 'outlet-plug1-switch', 'switch.kitchen_outlet')}
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Switch to turn off when unattended</div>
          </div>
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">Power Threshold (W)</label>
              <input type="number" class="form-input stove-power-threshold" value="${device.stove_power_threshold ?? 100}" min="0" step="10" placeholder="100">
              <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Stove "on" when power exceeds this</div>
            </div>
            <div class="form-group">
              <label class="form-label">Cooking Time (min)</label>
              <input type="number" class="form-input stove-cooking-time" value="${device.cooking_time_minutes ?? 15}" min="1" max="120" placeholder="15">
            </div>
          </div>
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">On Debounce (sec)</label>
              <input type="number" class="form-input stove-on-debounce" value="${device.stove_on_debounce_seconds ?? 0}" min="0" max="60" placeholder="0">
              <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Seconds above threshold before "on" (0=immediate)</div>
            </div>
            <div class="form-group">
              <label class="form-label">Off Debounce (sec)</label>
              <input type="number" class="form-input stove-off-debounce" value="${device.stove_off_debounce_seconds ?? 10}" min="0" max="60" placeholder="10">
              <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Seconds below threshold before "off" (reduces on/off flicker)</div>
            </div>
          </div>
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">Final Warning (sec)</label>
              <input type="number" class="form-input stove-final-warning" value="${device.final_warning_seconds ?? 30}" min="5" max="300" placeholder="30">
            </div>
            <div class="form-group">
              <label class="form-label">Timer Start Window (sec)</label>
              <input type="number" class="form-input stove-timer-window" value="${device.timer_start_window_seconds ?? 10}" min="1" max="120" placeholder="10">
              <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Wait before starting timer after leaving kitchen (brief absences ignored)</div>
            </div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Timer progress TTS interval (sec)</label>
            <input type="number" class="form-input stove-timer-tts-interval" value="${device.stove_timer_tts_interval_seconds ?? 0}" min="0" max="3600" placeholder="0">
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">0 = auto (cooking duration ÷ 4, min 60s). Spoken during the long unattended phase.</div>
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Presence Sensor</label>
            ${this._renderEntityAutocomplete(device.presence_sensor || '', 'binary_sensor', roomIndex, 'stove-presence-sensor', 'binary_sensor.kitchen_presence')}
          </div>
        ` : '';

    const microwaveSafetyFields = deviceType === 'microwave' && hasStoveInRoom ? `
          <div class="divider" style="margin: 16px 0;"></div>
          <div class="plug-settings-title" style="margin-bottom: 12px; color: var(--panel-warning);">Microwave Safety (shared breaker)</div>
          <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">For older homes where microwave and stove share the same breaker. When microwave is on, stove power is cut until microwave turns off. <strong style="color: var(--panel-warning);">Can damage stove LED panel—use at your discretion.</strong> Requires stove safety to be enabled.</p>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="toggle-row ${!hasStoveSafetyEnabled ? 'toggle-disabled' : ''}">
              <input type="checkbox" class="form-checkbox microwave-safety-enabled" ${device.microwave_safety_enabled !== false ? 'checked' : ''} ${!hasStoveSafetyEnabled ? 'disabled' : ''}>
              <span class="toggle-label">Enable microwave safety (cut stove when microwave on)</span>
            </label>
            ${!hasStoveSafetyEnabled ? '<div style="font-size: 10px; color: var(--panel-warning); margin-top: 4px;">Enable stove safety shutoff in the Stove card first.</div>' : ''}
          </div>
          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">Microwave On Threshold (W)</label>
            <input type="number" class="form-input microwave-power-threshold" value="${device.microwave_power_threshold ?? 50}" min="0" step="10" placeholder="50">
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Microwave power sensor is above. Microwave "on" when power exceeds this.</div>
          </div>
        ` : deviceType === 'microwave' && !hasStoveInRoom ? `
          <div class="divider" style="margin: 16px 0;"></div>
          <p style="color: var(--secondary-text-color); font-size: 11px; padding: 10px; background: rgba(255,152,0,0.1); border-radius: 8px; border: 1px solid rgba(255,152,0,0.3);">
            Add a Stove device to this room to enable Microwave Safety (shared breaker) — links microwave and stove to cut stove power when microwave is on.
          </p>
        ` : '';

    const presenceApplianceHelp =
      deviceType === 'stove'
        ? 'Uses room Presence & zones. Turns stove plug off when away and can restore when returning if this turned it off. Opt-in: use with care.'
        : 'Uses room Presence & zones when a switch exists. Microwaves usually have no switch; saved for compatibility.';
    const presenceApplianceBlock =
      deviceType === 'stove' || deviceType === 'microwave'
        ? this._renderPresenceAutoOffRow(
            'presence-auto-off-appliance',
            !!device.presence_auto_off,
            presenceApplianceHelp,
          )
        : '';

    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${deviceIndex}" data-room-index="${roomIndex}" data-device-type="${deviceType}" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0 4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${device.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${deviceIndex}" title="Delete">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">${deviceType === 'stove' ? 'Stove' : 'Microwave'} Name</label>
              <input type="text" class="form-input outlet-name" value="${device.name || ''}" placeholder="${deviceType === 'stove' ? 'Stove name...' : 'Microwave name...'}">
            </div>
            <div class="form-group">
              <label class="form-label">Warn Limit</label>
              <input type="number" class="form-input outlet-threshold threshold-disabled" value="" placeholder="∞ W" min="0" style="width: 70px;" disabled title="Stove and microwave use infinite threshold">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Power Sensor</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                ${this._renderEntityAutocomplete(device.plug1_entity || '', 'sensor', roomIndex, 'outlet-plug1', 'sensor.kitchen_power')}
              </div>
              ${stoveSafetyFields}
              ${microwaveSafetyFields}
              ${presenceApplianceBlock}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletSettings(outlet, outletIndex, powerSensors, roomIndex, isCollapsed = true) {
    const isSingleOutlet = (outlet.type || 'outlet') === 'single_outlet';
    const displayName = outlet.name || 'Unnamed Outlet';
    const collapsedClass = isCollapsed ? 'collapsed' : '';
    const presencePlug1Class = isSingleOutlet ? 'presence-auto-off-appliance' : 'presence-auto-off-plug1';
    const presencePlug1Checked = isSingleOutlet ? !!outlet.presence_auto_off : !!outlet.presence_auto_off_plug1;

    return `
      <div class="outlet-settings-item ${collapsedClass}" data-outlet-index="${outletIndex}" data-room-index="${roomIndex}" draggable="true">
        <div class="outlet-settings-bar">
          <div class="outlet-drag-handle" title="Drag to reorder">
            <svg viewBox="0 0 24 24"><path d="M9 20h6v-2H9v2zm0-18v2h6V2H9zm0 8h6V8H9v2zm0 4h6v-2H9v2zM3 8h2v2H3V8zm0 4h2v2H3v-2zm0-8h2v2H3V4zm0 12h2v2H3v-2zm16-4h2v2h-2v-2zm0-4h2v2h-2V8zm0 8h2v2h-2v-2zm0-12h2v2h-2V4z"/></svg>
          </div>
          <span class="outlet-name-display ${outlet.name ? '' : 'empty'}">${displayName}</span>
          <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${outletIndex}" title="Delete outlet">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
          <div class="outlet-expand-icon">
            <svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
          </div>
        </div>
        
        <div class="outlet-settings-body">
          <div class="outlet-settings-header">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">Outlet Name</label>
              <input type="text" class="form-input outlet-name" value="${outlet.name || ''}" placeholder="Outlet name...">
            </div>
            <div class="form-group">
              <label class="form-label">Warn Limit</label>
              <input type="number" class="form-input outlet-threshold" value="${outlet.threshold || ''}" placeholder="W" min="0" style="width: 70px;">
            </div>
          </div>
          
          <div class="plugs-settings-grid ${isSingleOutlet ? 'single-plug' : ''}">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">${isSingleOutlet ? 'Plug' : 'Plug 1'}</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                ${this._renderEntityAutocomplete(outlet.plug1_entity || '', 'sensor', roomIndex, 'outlet-plug1', 'sensor.kitchen_power')}
              </div>
              <div class="form-group">
                <label class="form-label">Switch</label>
                ${this._renderEntityAutocomplete(outlet.plug1_switch || '', 'switch', roomIndex, 'outlet-plug1-switch', 'switch.kitchen_outlet')}
              </div>
              <div class="shutoff-row">
                <div class="form-group">
                  <label class="form-label">Shutoff (W)</label>
                  <input type="number" class="form-input outlet-plug1-shutoff" value="${outlet.plug1_shutoff || ''}" placeholder="Off" min="0">
                </div>
                <button class="test-switch-btn" data-switch="${outlet.plug1_switch || ''}" title="Test switch">
                  <svg viewBox="0 0 24 24">${icons.power}</svg>
                </button>
              </div>
              ${this._renderPresenceAutoOffRow(
                presencePlug1Class,
                presencePlug1Checked,
                isSingleOutlet
                  ? 'Uses room Presence & zones. Targets this plug switch.'
                  : 'Uses room Presence & zones. Targets plug 1 switch.',
              )}
            </div>
            ${isSingleOutlet ? '' : `
            <div class="plug-settings-card" data-plug="2">
              <div class="plug-settings-title">Plug 2</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                ${this._renderEntityAutocomplete(outlet.plug2_entity || '', 'sensor', roomIndex, 'outlet-plug2', 'sensor.kitchen_power')}
              </div>
              <div class="form-group">
                <label class="form-label">Switch</label>
                ${this._renderEntityAutocomplete(outlet.plug2_switch || '', 'switch', roomIndex, 'outlet-plug2-switch', 'switch.kitchen_outlet')}
              </div>
              <div class="shutoff-row">
                <div class="form-group">
                  <label class="form-label">Shutoff (W)</label>
                  <input type="number" class="form-input outlet-plug2-shutoff" value="${outlet.plug2_shutoff || ''}" placeholder="Off" min="0">
                </div>
                <button class="test-switch-btn" data-switch="${outlet.plug2_switch || ''}" title="Test switch">
                  <svg viewBox="0 0 24 24">${icons.power}</svg>
                </button>
              </div>
              ${this._renderPresenceAutoOffRow(
                'presence-auto-off-plug2',
                !!outlet.presence_auto_off_plug2,
                'Uses room Presence & zones. Targets plug 2 switch.',
              )}
            </div>
            `}
          </div>
        </div>
      </div>
    `;
  }

  _attachEventListeners() {
    // Menu button to toggle HA sidebar
    this._attachMenuButton();

    if (!this._roomZoneClickDelegation) {
      this._roomZoneClickDelegation = true;
      this.shadowRoot.addEventListener('click', (e) => this._handleRoomZoneClick(e));
    }

    if (!this._applianceToggleDelegation) {
      this._applianceToggleDelegation = true;
      this.shadowRoot.addEventListener('click', (e) => this._handleApplianceToggleClick(e));
    }

    if (!this._zoneHealthIconClickDelegation) {
      this._zoneHealthIconClickDelegation = true;
      this.shadowRoot.addEventListener('click', (e) => this._handleZoneHealthIconClick(e));
    }

    if (!this._roomRatingModalDelegation) {
      this._roomRatingModalDelegation = true;
      this.shadowRoot.addEventListener('click', (e) => this._handleRoomRatingClick(e));
    }

    if (!this._statPieBillingDelegation) {
      this._statPieBillingDelegation = true;
      this.shadowRoot.addEventListener('click', (e) => {
        const t = e.target;
        if (!t || !t.closest) return;
        const btn = t.closest('.stat-room-billing-chart');
        if (!btn || !this.shadowRoot.contains(btn)) return;
        const pieSel = this.shadowRoot.getElementById('stat-pie-selection');
        if (!pieSel || !pieSel.contains(btn)) return;
        e.preventDefault();
        e.stopPropagation();
        const rid = btn.dataset.roomId;
        const rname = btn.dataset.roomName || '';
        if (rid) {
          this._openGraph('stat_room_wh', rid, rname, this._statisticsGraphDateRange());
        }
      });
    }

    this.shadowRoot.querySelectorAll('.view-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const view = tab.dataset.view;
        if (view && (view === 'rooms' || view === 'statistics')) {
          this._dashboardView = view;
          this._render();
          if (view === 'statistics') {
            this._loadStatistics();
          }
        }
      });
    });

    this.shadowRoot.querySelectorAll('.graph-clickable').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const type = el.dataset.graphType;
        const roomId = el.dataset.roomId || null;
        const nameFromData = el.dataset.roomName || null;
        const room = roomId ? this._getRoomConfig(roomId) : null;
        let billingRange = null;
        if (type && type.startsWith('stat_')) {
          billingRange = this._statisticsGraphDateRange();
        }
        this._openGraph(type, roomId, nameFromData || room?.name || null, billingRange);
      });
    });

    const statHomeChart = this.shadowRoot.querySelector('#stat-chart-billing-home');
    if (statHomeChart) {
      statHomeChart.addEventListener('click', (e) => {
        e.stopPropagation();
        this._openGraph('stat_total_wh', null, null, this._statisticsGraphDateRange());
      });
    }
    const statRefreshBtn = this.shadowRoot.querySelector('#stat-refresh-cache');
    if (statRefreshBtn) {
      statRefreshBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        statRefreshBtn.disabled = true;
        statRefreshBtn.textContent = 'Refreshing...';
        try {
          await this._hass.callWS({ type: 'smart_dashboards/clear_statistics_cache' });
          await this._loadStatistics();
          this._showToast('Statistics cache cleared and refreshed');
        } catch (err) {
          console.error('Failed to refresh statistics:', err);
          this._showToast('Failed to refresh statistics');
        } finally {
          statRefreshBtn.disabled = false;
          statRefreshBtn.textContent = 'Refresh Statistics';
        }
      });
    }
    this.shadowRoot.querySelectorAll('[data-stat-rooms-view]').forEach((seg) => {
      seg.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const mode = seg.dataset.statRoomsView;
        if (mode !== 'table' && mode !== 'pie') return;
        this._statsRoomsView = mode;
        const pie = mode === 'pie';
        this.shadowRoot.querySelectorAll('[data-stat-rooms-view]').forEach((b) => {
          const on = b.dataset.statRoomsView === mode;
          b.classList.toggle('active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        const panelTable = this.shadowRoot.getElementById('stat-rooms-panel-table');
        const panelPie = this.shadowRoot.getElementById('stat-rooms-panel-pie');
        if (panelTable) panelTable.style.display = pie ? 'none' : 'block';
        if (panelPie) panelPie.style.display = pie ? 'block' : 'none';
        const pieMount = this.shadowRoot.getElementById('stat-rooms-pie-chart');
        if (pieMount) pieMount.setAttribute('aria-hidden', pie ? 'false' : 'true');
        if (pie) void this._syncStatsRoomsPie();
        else {
          this._destroyStatsRoomsPie();
          this._resetStatPieSelectionPanel();
        }
      });
    });

    const settingsBtn = this.shadowRoot.querySelector('#settings-btn');
    const emptySettingsBtn = this.shadowRoot.querySelector('#empty-settings-btn');

    if (settingsBtn) {
      settingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._graphOpen = null;
          this._graphData = null;
          this._graphLoading = false;
          this._graphLoadError = null;
          this._showSettings = true;
          this._stopRefresh();
          await this._loadConfig();
          this._render();
        }
      });
    }

    if (emptySettingsBtn) {
      emptySettingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._graphOpen = null;
          this._graphData = null;
          this._graphLoading = false;
          this._graphLoadError = null;
          this._showSettings = true;
          this._stopRefresh();
          await this._loadConfig();
          this._render();
        }
      });
    }

    this._attachSummaryStatsResize();
    this._scheduleSummaryStatFit();
    this._attachRoomContentWheelScroll();
  }

  _attachMenuButton() {
    const menuBtn = this.shadowRoot.querySelector('#menu-btn');
    if (menuBtn) {
      menuBtn.addEventListener('click', () => {
        this._toggleSidebar();
      });
    }
  }

  _toggleSidebar() {
    // Fire event to toggle HA sidebar
    const event = new Event('hass-toggle-menu', { bubbles: true, composed: true });
    this.dispatchEvent(event);
  }

  _attachSettingsEventListeners() {
    // Menu button
    this._attachMenuButton();

    const backBtn = this.shadowRoot.querySelector('#back-btn');
    const saveBtn = this.shadowRoot.querySelector('#save-btn');
    const addRoomBtn = this.shadowRoot.querySelector('#add-room-btn');

    if (backBtn) {
      backBtn.addEventListener('click', () => {
        this._showSettings = false;
        this._settingsTab = 'rooms';
        this._render();
        this._startRefresh();
        if (this._dashboardView === 'statistics') {
          void this._loadStatistics();
        }
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', () => this._saveSettings());
    }

    const saveEnforcementBtn = this.shadowRoot.querySelector('#save-enforcement-btn');
    if (saveEnforcementBtn) {
      saveEnforcementBtn.addEventListener('click', () => this._saveEnforcementSettings());
    }

    if (addRoomBtn) {
      addRoomBtn.addEventListener('click', () => this._addRoom());
    }

    // Tab switching
    this.shadowRoot.querySelectorAll('.settings-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        this._settingsTab = tabId;
        
        // Update tab active states
        this.shadowRoot.querySelectorAll('.settings-tab').forEach(t => {
          t.classList.toggle('active', t.dataset.tab === tabId);
        });
        
        // Update content visibility
        this.shadowRoot.querySelectorAll('.settings-tab-content').forEach(content => {
          content.classList.toggle('active', content.id === `tab-${tabId}`);
        });

        // Load zone health data when that tab becomes active
        if (tabId === 'zone-health') {
          this._loadZoneHealthStatus();
        }
      });
    });

    // Test notification button
    const notifyTestBtn = this.shadowRoot.querySelector('#notify-send-test');
    if (notifyTestBtn) {
      notifyTestBtn.addEventListener('click', () => this._sendTestNotification());
    }

    const effDigestTestBtn = this.shadowRoot.querySelector('#eff-digest-send-test');
    if (effDigestTestBtn) {
      effDigestTestBtn.addEventListener('click', () => this._sendEfficiencyDigestTest());
    }

    // Zone health refresh button
    const zoneHealthRefreshBtn = this.shadowRoot.querySelector('#zone-health-refresh');
    if (zoneHealthRefreshBtn) {
      zoneHealthRefreshBtn.addEventListener('click', () => this._forceRefreshZoneHealth());
    }
    // Auto-load zone health when tab is visible
    if (this._settingsTab === 'zone-health') {
      this._loadZoneHealthStatus();
    }

    // Integration automation sub-toggles visibility
    const integrationAutoToggle = this.shadowRoot.querySelector('#tts-notify-integration-auto');
    const integrationSubToggles = this.shadowRoot.querySelector('#integration-sub-toggles');
    if (integrationAutoToggle && integrationSubToggles) {
      integrationAutoToggle.addEventListener('change', () => {
        integrationSubToggles.style.display = integrationAutoToggle.checked ? '' : 'none';
      });
    }

    // Toggle room details
    this.shadowRoot.querySelectorAll('.toggle-room-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = btn.dataset.index;
        const body = this.shadowRoot.querySelector(`#room-body-${index}`);
        if (body) {
          const isVisible = body.style.display !== 'none';
          body.style.display = isVisible ? 'none' : 'block';
          btn.textContent = isVisible ? 'Edit' : 'Collapse';
        }
      });
    });

    // Remove room buttons
    this.shadowRoot.querySelectorAll('.remove-room-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const card = btn.closest('.room-settings-card');
        if (card) card.remove();
      });
    });

    // Room save buttons
    this.shadowRoot.querySelectorAll('.room-save-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const roomIndex = parseInt(btn.dataset.index);
        await this._saveSingleRoom(roomIndex);
      });
    });

    this.shadowRoot.querySelectorAll('.room-presence-person').forEach((sel) => {
      sel.addEventListener('change', () => {
        const card = sel.closest('.room-settings-card');
        this._syncRoomPresenceLiveStrip(card);
      });
    });

    // Room card drag-and-drop for reordering
    this._attachRoomDragListeners();

    // Add device dropdown (Outlet / Single Outlet)
    this.shadowRoot.querySelectorAll('.add-device-dropdown').forEach(dropdown => {
      const trigger = dropdown.querySelector('.add-device-trigger');
      const menu = dropdown.querySelector('.add-device-menu');
      const roomIndex = dropdown.dataset.roomIndex;
      if (!trigger || !menu) return;
      trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = menu.style.display === 'block';
        this.shadowRoot.querySelectorAll('.add-device-menu').forEach(m => { m.style.display = 'none'; });
        menu.style.display = isOpen ? 'none' : 'block';
      });
      menu.querySelectorAll('.add-device-option').forEach(opt => {
        opt.addEventListener('click', (e) => {
          e.stopPropagation();
          menu.style.display = 'none';
          this._addOutlet(roomIndex, opt.dataset.type || 'outlet');
        });
      });
    });
    this.shadowRoot.addEventListener('click', (e) => {
      if (!e.target.closest('.add-device-dropdown')) {
        this.shadowRoot.querySelectorAll('.add-device-menu').forEach(m => { m.style.display = 'none'; });
      }
    });

    // Area selectors - filter outlets when area changes

    // Responsive light warnings toggle
    this.shadowRoot.querySelectorAll('.responsive-light-warnings-toggle').forEach(toggle => {
      toggle.addEventListener('change', (e) => {
        const section = e.target.closest('.responsive-light-section');
        const pickers = section?.querySelector('.responsive-light-pickers');
        if (pickers) pickers.style.display = e.target.checked ? 'flex' : 'none';
      });
    });

    // Room volume sliders
    this.shadowRoot.querySelectorAll('.room-volume').forEach(slider => {
      slider.addEventListener('input', (e) => {
        const display = e.target.closest('.form-group').querySelector('.room-volume-display');
        if (display) {
          display.textContent = Math.round(parseFloat(e.target.value) * 100) + '%';
        }
      });
    });

    // Attach event listeners to all existing outlets
    this.shadowRoot.querySelectorAll('.outlet-settings-item').forEach(outletItem => {
      const roomIndex = outletItem.dataset.roomIndex;
      this._attachOutletEventListeners(outletItem, roomIndex);
    });
    this._initEntityAutocompletes(this.shadowRoot);

    // Test switch buttons (compact icon on outlets; full-width .light-test-switch-btn on light/vent)
    this.shadowRoot.querySelectorAll('.test-switch-btn, .light-test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });

    this._bindTtsLineEnableToggles();
  }

  async _testToggleSwitch(btn) {
    // Get switch entity from data attribute or from the adjacent select
    let switchEntity = btn.dataset.switch;
    
    // If no switch in data attribute, try to get from the select in the same plug card
    if (!switchEntity) {
      const plugCard = btn.closest('.plug-settings-card');
      const switchSelect = plugCard?.querySelector('.light-switch-entity') || plugCard?.querySelector(`.outlet-plug${plugCard?.dataset?.plug || 1}-switch`);
      switchEntity = switchSelect?.value;
    }

    if (!switchEntity) {
      showToast(this.shadowRoot, 'No switch selected for this plug', 'error');
      return;
    }

    btn.disabled = true;
    
    try {
      const result = await this._hass.callWS({
        type: 'smart_dashboards/toggle_switch',
        entity_id: switchEntity,
      });
      
      // Update button visual state
      btn.classList.toggle('on', result.state === 'on');
      showToast(this.shadowRoot, `Switch ${result.state === 'on' ? 'ON' : 'OFF'}`, 'success');
    } catch (e) {
      console.error('Failed to toggle switch:', e);
      showToast(this.shadowRoot, 'Failed to toggle switch', 'error');
    } finally {
      btn.disabled = false;
    }
  }

  _getFilteredSensors(roomIndex) {
    return this._entities?.power_sensors || [];
  }

  _getFilteredSwitches(roomIndex) {
    return this._entities?.switches || [];
  }

  _getEntitiesForAutocomplete(roomIndex, entityType) {
    const prefix = entityType === 'sensor' ? 'sensor.' : entityType === 'switch' ? 'switch.' : entityType === 'light' ? 'light.' : entityType === 'binary_sensor' ? 'binary_sensor.' : '';
    if (entityType === 'cost_helper') {
      const sensors = (this._entities?.sensors || this._entities?.power_sensors || []).map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      const inputTexts = (this._entities?.input_text || []).map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      const inputNumbers = (this._entities?.input_number || []).map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      return [...sensors, ...inputTexts, ...inputNumbers];
    }
    if (entityType === 'sensor') {
      const list = (roomIndex === 'stats' || roomIndex === 'statistics')
        ? (this._entities?.sensors || this._entities?.power_sensors || [])
        : (this._getFilteredSensors(roomIndex) || []);
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'switch') {
      const list = (this._getFilteredSwitches(roomIndex) || []).filter(s => (s.entity_id || '').startsWith('switch.'));
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'light') {
      const list = (this._entities?.lights || []).filter(l => (l.entity_id || '').startsWith('light.'));
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'binary_sensor') {
      const list = (this._entities?.binary_sensors || []).filter(b => (b.entity_id || '').startsWith('binary_sensor.'));
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'zone') {
      const list = (this._entities?.zones || []).filter(z => (z.entity_id || '').startsWith('zone.'));
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'person') {
      const list = (this._entities?.persons || []).filter(p => (p.entity_id || '').startsWith('person.'));
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'media_player') {
      const list = this._entities?.media_players || [];
      return list.map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
    }
    if (entityType === 'power_watts') {
      const sensors = (this._getFilteredSensors(roomIndex) || []).map(e => ({
        entity_id: e.entity_id,
        friendly_name: e.friendly_name || e.entity_id,
      }));
      const switches = (this._getFilteredSwitches(roomIndex) || [])
        .filter(s => (s.entity_id || '').startsWith('switch.'))
        .map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      return [...sensors, ...switches];
    }
    if (entityType === 'weather') {
      const weathers = (this._entities?.weather || [])
        .filter(w => (w.entity_id || '').startsWith('weather.'))
        .map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      const sensors = (this._entities?.sensors || this._entities?.power_sensors || [])
        .filter(s => {
          const eid = (s.entity_id || '').toLowerCase();
          return eid.includes('outdoor') || eid.includes('outside') || eid.includes('external') || eid.includes('temp');
        })
        .map(e => ({ entity_id: e.entity_id, friendly_name: e.friendly_name || e.entity_id }));
      return [...weathers, ...sensors];
    }
    return [];
  }

  _filterEntityMatches(entities, query) {
    if (!query || !query.trim()) return entities.slice(0, 15);
    const q = query.toLowerCase().trim();
    const scored = entities.map(e => {
      const id = (e.entity_id || '').toLowerCase();
      const name = (e.friendly_name || '').toLowerCase();
      let score = 0;
      if (id.includes(q) || id.startsWith(q)) score += 10;
      if (name.includes(q) || name.startsWith(q)) score += 5;
      if (id === q || name === q) score += 20;
      return { ...e, _score: score };
    }).filter(e => e._score > 0).sort((a, b) => b._score - a._score);
    return scored.slice(0, 15).map(({ _score, ...e }) => e);
  }

  _renderEntityAutocomplete(value, entityType, roomIndex, inputClass, placeholder) {
    this._entityDatalistId = (this._entityDatalistId || 0) + 1;
    const dlId = `entity-dl-${this._entityDatalistId}`;
    const val = (value || '').trim();
    const safeVal = val.replace(/"/g, '&quot;');
    return `
      <input type="text" class="form-input entity-datalist-input ${inputClass || ''}" value="${safeVal}" placeholder="${(placeholder || 'Type to search...').replace(/"/g, '&quot;')}" list="${dlId}" data-entity-type="${entityType}" data-room-index="${roomIndex}" autocomplete="off">
      <datalist id="${dlId}" data-entity-type="${entityType}" data-room-index="${roomIndex}"></datalist>
    `;
  }

  _initEntityAutocompletes(container) {
    if (!container) return;
    container.querySelectorAll('.entity-datalist-input').forEach(input => {
      const dlId = input.getAttribute('list');
      const datalist = dlId ? container.querySelector(`#${dlId}`) : null;
      const roomIndex = input.dataset.roomIndex;
      const entityType = input.dataset.entityType;
      if (!datalist || roomIndex == null || !entityType) return;
      if (input._entityDatalistInit) return;
      input._entityDatalistInit = true;

      const update = () => {
        const entities = this._getEntitiesForAutocomplete(roomIndex, entityType);
        const matches = this._filterEntityMatches(entities, input.value);
        datalist.innerHTML = matches.map(e => {
          const id = (e.entity_id || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
          const label = (e.friendly_name || e.entity_id || '').replace(/</g, '&lt;');
          return `<option value="${id}">${label}</option>`;
        }).join('');
      };

      input.addEventListener('focus', () => update());
      input.addEventListener('input', () => update());
    });
  }

  _addRoom() {
    const mediaPlayers = this._entities?.media_players || [];
    const powerSensors = this._entities?.power_sensors || [];
    
    const list = this.shadowRoot.querySelector('#rooms-list');
    const noItems = list.querySelector('p');
    if (noItems) noItems.remove();

    const index = list.querySelectorAll('.room-settings-card').length;
    const newRoom = {
      id: `room_${Date.now()}`,
      name: `Room ${index + 1}`,
      media_player: '',
      threshold: 0,
      kwh_budget: 5,
      kwh_budget_use_boost: true,
      volume: 0.7,
      presence_person_entity: null,
      presence_zone_entities: [],
      room_icon: null,
      outlets: [],
    };
    
    const html = this._renderRoomSettings(newRoom, index, mediaPlayers, powerSensors);
    list.insertAdjacentHTML('beforeend', html);

    // Attach event listeners for the new room
    const newCard = list.querySelector(`.room-settings-card[data-room-index="${index}"]`);
    this._initEntityAutocompletes(newCard);
    this._attachRoomDragListeners(newCard);
    this._attachRoomIconPickerListeners(newCard);

    const toggleBtn = newCard.querySelector('.toggle-room-btn');
    toggleBtn.addEventListener('click', () => {
      const body = newCard.querySelector(`#room-body-${index}`);
      if (body) {
        const isVisible = body.style.display !== 'none';
        body.style.display = isVisible ? 'none' : 'block';
        toggleBtn.textContent = isVisible ? 'Edit' : 'Collapse';
      }
    });

    const removeBtn = newCard.querySelector('.remove-room-btn');
    removeBtn.addEventListener('click', () => newCard.remove());

    const addDeviceDropdown = newCard.querySelector('.add-device-dropdown');
    if (addDeviceDropdown) {
      const trigger = addDeviceDropdown.querySelector('.add-device-trigger');
      const menu = addDeviceDropdown.querySelector('.add-device-menu');
      if (trigger && menu) {
        trigger.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = menu.style.display === 'block';
          this.shadowRoot.querySelectorAll('.add-device-menu').forEach(m => { m.style.display = 'none'; });
          menu.style.display = isOpen ? 'none' : 'block';
        });
        menu.querySelectorAll('.add-device-option').forEach(opt => {
          opt.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.style.display = 'none';
            this._addOutlet(index, opt.dataset.type || 'outlet');
          });
        });
      }
    }

    const volumeSlider = newCard.querySelector('.room-volume');
    if (volumeSlider) {
      volumeSlider.addEventListener('input', (e) => {
        const display = e.target.closest('.form-group').querySelector('.room-volume-display');
        if (display) {
          display.textContent = Math.round(parseFloat(e.target.value) * 100) + '%';
        }
      });
    }

    // Auto-expand
    toggleBtn.click();
  }

  _addOutlet(roomIndex, deviceType = 'outlet') {
    const sensors = this._getFilteredSensors(roomIndex);
    const list = this.shadowRoot.querySelector(`#outlets-list-${roomIndex}`);
    const roomCard = list.closest('.room-settings-card');
    
    // Collapse all existing outlets first
    list.querySelectorAll('.outlet-settings-item').forEach(item => {
      item.classList.add('collapsed');
    });
    
    // Build roomOutlets for appliance settings (stove/microwave linking)
    const existingTypes = Array.from(list.querySelectorAll('.outlet-settings-item')).map(item => ({ type: item.dataset.deviceType || 'outlet' }));
    const roomOutlets = [{ type: deviceType }, ...existingTypes];
    
    // Generate new device based on type
    const isAppliance = deviceType === 'stove' || deviceType === 'microwave';
    const isLight = deviceType === 'light';
    const isVentLike = isVentLikeType(deviceType);
    const newOutlet = {
      name: '',
      type: deviceType,
      plug1_entity: isLight || isVentLike ? null : '',
      plug2_entity: deviceType === 'outlet' ? '' : null,
      plug1_switch: isAppliance || isLight || isVentLike ? null : '',
      plug2_switch: deviceType === 'outlet' ? '' : null,
      threshold: 0,
      plug1_shutoff: isAppliance || isLight || isVentLike ? 0 : 0,
      plug2_shutoff: deviceType === 'outlet' ? 0 : null,
    };
    if (isLight) {
      newOutlet.switch_entity = '';
      newOutlet.light_entities = [];
      newOutlet.power_source = 'configured';
      newOutlet.power_sensor_entity = '';
    }
    if (isVentLike) {
      newOutlet.switch_entity = '';
      newOutlet.watts_when_on = 25;
      newOutlet.power_source = 'configured';
      newOutlet.power_sensor_entity = '';
      if (deviceType === 'wall_heater') {
        newOutlet.heater_on_below_temperature = 65;
        newOutlet.heater_stay_on_minutes = 5;
        newOutlet.heater_presence_cooldown_seconds = 60;
        newOutlet.heater_comfort_temperature = null;
        newOutlet.heater_presence_turn_on_enabled = false;
      }
    }
    if (deviceType === 'minisplit') {
      newOutlet.minisplit_enforcement_off_seconds = 60;
      newOutlet.minisplit_enforcement_min_watts = 0;
    }

    // Render as expanded (not collapsed)
    const html = this._renderDeviceSettings(newOutlet, 0, sensors, roomIndex, roomOutlets, false);
    
    // Insert at TOP of list
    list.insertAdjacentHTML('afterbegin', html);
    
    // Re-index all outlets
    list.querySelectorAll('.outlet-settings-item').forEach((item, idx) => {
      item.dataset.outletIndex = idx;
    });

    const newItem = list.querySelector('.outlet-settings-item:first-child');
    
    // Attach event listeners to new item
    this._attachOutletEventListeners(newItem, roomIndex);
    this._initEntityAutocompletes(newItem);
    
    // Focus on name input
    const nameInput = newItem.querySelector('.outlet-name');
    if (nameInput) {
      setTimeout(() => nameInput.focus(), 100);
    }
  }

  _attachRoomDragListeners(singleCard = null) {
    const list = this.shadowRoot.querySelector('#rooms-list');
    if (!list) return;
    const cards = singleCard ? [singleCard] : Array.from(list.querySelectorAll('.room-settings-card'));
    cards.forEach(card => {
      const handle = card.querySelector('.room-drag-handle');
      if (handle) {
        handle.addEventListener('mousedown', () => {
          card.setAttribute('draggable', 'true');
        });
      }
      card.addEventListener('dragstart', (e) => {
        this._draggedRoomCard = card;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', card.dataset.roomIndex);
      });
      card.addEventListener('dragend', () => {
        card.classList.remove('dragging');
        card.setAttribute('draggable', 'false');
        list.querySelectorAll('.room-settings-card').forEach(c => c.classList.remove('drag-over'));
        this._draggedRoomCard = null;
      });
      card.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (this._draggedRoomCard && this._draggedRoomCard !== card) {
          card.classList.add('drag-over');
        }
      });
      card.addEventListener('dragleave', () => {
        card.classList.remove('drag-over');
      });
      card.addEventListener('drop', (e) => {
        e.preventDefault();
        card.classList.remove('drag-over');
        if (this._draggedRoomCard && this._draggedRoomCard !== card) {
          const cardsArr = Array.from(list.querySelectorAll('.room-settings-card'));
          const draggedIdx = cardsArr.indexOf(this._draggedRoomCard);
          const targetIdx = cardsArr.indexOf(card);
          if (draggedIdx < targetIdx) {
            card.after(this._draggedRoomCard);
          } else {
            card.before(this._draggedRoomCard);
          }
        }
      });
    });
  }

  _attachOutletEventListeners(outletItem, roomIndex) {
    // Remove button
    const removeBtn = outletItem.querySelector('.remove-outlet-btn');
    if (removeBtn) {
      removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        outletItem.remove();
      });
    }

    // Light entity rows: add/remove
    const lightEntityRows = outletItem.querySelector('.light-entity-rows');
    const lightEntityAddBtn = outletItem.querySelector('.light-entity-add-btn');
    if (lightEntityRows && lightEntityAddBtn) {
      const addRow = () => {
        const idx = lightEntityRows.querySelectorAll('.light-entity-row').length;
        const html = this._htmlLightMappedRow(idx, { entity_id: '', watts: 0, wrgb: false }, roomIndex);
        lightEntityRows.insertAdjacentHTML('beforeend', html);
        const row = lightEntityRows.lastElementChild;
        row.querySelector('.light-entity-remove-btn').addEventListener('click', () => row.remove());
        this._initEntityAutocompletes(row);
      };
      lightEntityAddBtn.addEventListener('click', addRow);
      lightEntityRows.querySelectorAll('.light-entity-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => btn.closest('.light-entity-row')?.remove());
      });
    }

    const lightPowerSourceSel = outletItem.querySelector('.light-power-source');
    if (lightPowerSourceSel) {
      const syncLightPowerUi = () => {
        const sensor = lightPowerSourceSel.value === 'sensor';
        const block = outletItem.querySelector('.light-power-sensor-block');
        if (block) block.style.display = sensor ? 'block' : 'none';
      };
      lightPowerSourceSel.addEventListener('change', syncLightPowerUi);
      syncLightPowerUi();
    }

    const ventPowerSourceSel = outletItem.querySelector('.ceiling-vent-power-source');
    if (ventPowerSourceSel) {
      const syncVentPowerUi = () => {
        const sensor = ventPowerSourceSel.value === 'sensor';
        const sb = outletItem.querySelector('.ceiling-vent-power-sensor-block');
        const wb = outletItem.querySelector('.ceiling-vent-watts-block');
        if (sb) sb.style.display = sensor ? 'block' : 'none';
        if (wb) wb.style.display = sensor ? 'none' : 'block';
      };
      ventPowerSourceSel.addEventListener('change', syncVentPowerUi);
      syncVentPowerUi();
    }

    // Collapse/expand (accordion)
    const bar = outletItem.querySelector('.outlet-settings-bar');
    if (bar) {
      bar.addEventListener('click', (e) => {
        if (e.target.closest('.remove-outlet-btn') || e.target.closest('.outlet-drag-handle')) return;
        
        const roomCard = outletItem.closest('.room-settings-card');
        
        if (outletItem.classList.contains('collapsed')) {
          // Collapse all others, expand this one
          roomCard.querySelectorAll('.outlet-settings-item').forEach(item => {
            item.classList.add('collapsed');
          });
          outletItem.classList.remove('collapsed');
        } else {
          outletItem.classList.add('collapsed');
        }
      });
    }

    // Update display name on input
    const nameInput = outletItem.querySelector('.outlet-name');
    if (nameInput) {
      nameInput.addEventListener('input', (e) => {
        const displaySpan = outletItem.querySelector('.outlet-name-display');
        if (displaySpan) {
          displaySpan.textContent = e.target.value || 'Unnamed Outlet';
          displaySpan.classList.toggle('empty', !e.target.value);
        }
      });
    }

    // Drag and drop
    const dragHandle = outletItem.querySelector('.outlet-drag-handle');
    if (dragHandle) {
      dragHandle.addEventListener('mousedown', () => {
        if (outletItem.classList.contains('collapsed')) {
          outletItem.setAttribute('draggable', 'true');
        }
      });
    }

    outletItem.addEventListener('dragstart', (e) => {
      if (!outletItem.classList.contains('collapsed')) {
        e.preventDefault();
        return;
      }
      outletItem.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      this._draggedOutlet = outletItem;
    });

    outletItem.addEventListener('dragend', () => {
      outletItem.classList.remove('dragging');
      outletItem.setAttribute('draggable', 'false');
      this._draggedOutlet = null;
    });

    outletItem.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (this._draggedOutlet && this._draggedOutlet !== outletItem) {
        outletItem.classList.add('drag-over');
      }
    });

    outletItem.addEventListener('dragleave', () => {
      outletItem.classList.remove('drag-over');
    });

    outletItem.addEventListener('drop', (e) => {
      e.preventDefault();
      outletItem.classList.remove('drag-over');
      
      if (this._draggedOutlet && this._draggedOutlet !== outletItem) {
        const list = outletItem.parentElement;
        const items = Array.from(list.querySelectorAll('.outlet-settings-item'));
        const draggedIdx = items.indexOf(this._draggedOutlet);
        const targetIdx = items.indexOf(outletItem);
        
        if (draggedIdx < targetIdx) {
          outletItem.after(this._draggedOutlet);
        } else {
          outletItem.before(this._draggedOutlet);
        }
      }
    });

    // Test switch buttons
    outletItem.querySelectorAll('.test-switch-btn, .light-test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });
  }

  async _saveEnforcementSettings() {
    const rkwhStr =
      (this.shadowRoot.querySelector('#pe-room-kwh-intervals')?.value || '5, 10, 15, 20').trim();
    const rkwhParsed = this._parseRoomKwhIntervals(rkwhStr);
    if (!rkwhParsed.valid) {
      showToast(
        this.shadowRoot,
        'Room kWh intervals must be exactly four comma-separated increasing positive numbers (e.g. 5, 10, 15, 20).',
        'error',
      );
      return;
    }
    const pe = {
      enabled: this.shadowRoot.querySelector('#pe-enabled')?.checked || false,
      phase1_enabled: this.shadowRoot.querySelector('#pe-phase1-enabled')?.checked !== false,
      phase2_enabled: this.shadowRoot.querySelector('#pe-phase2-enabled')?.checked !== false,
      phase1_warning_count: parseInt(this.shadowRoot.querySelector('#pe-phase1-count')?.value) || 20,
      phase1_time_window_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase1-window')?.value) || 60,
      phase1_volume_increment: parseInt(this.shadowRoot.querySelector('#pe-phase1-vol-inc')?.value) || 2,
      phase1_reset_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase1-reset')?.value) || 60,
      phase2_warning_count: parseInt(this.shadowRoot.querySelector('#pe-phase2-count')?.value) || 10,
      phase2_time_window_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase2-window')?.value) || 10,
      phase2_cycle_delay_seconds: parseInt(this.shadowRoot.querySelector('#pe-phase2-delay')?.value) || 5,
      phase2_reset_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase2-reset')?.value) || 30,
      phase2_max_volume: Math.max(0, Math.min(100, parseInt(this.shadowRoot.querySelector('#pe-phase2-max-volume')?.value) || 100)),
      room_kwh_intervals: rkwhParsed.intervals,
      home_kwh_limit: parseInt(this.shadowRoot.querySelector('#pe-home-kwh-limit')?.value) || 22,
      rooms_enabled: [],
    };
    this.shadowRoot.querySelectorAll('.pe-room-checkbox:checked').forEach(cb => {
      pe.rooms_enabled.push(cb.dataset.roomId);
    });
    const ttsMerged = {
      ...(this._config?.tts_settings || {}),
      ...this._collectBudgetBoostFromDom(),
    };
    try {
      const energyConfig = {
        ...this._config,
        power_enforcement: pe,
        tts_settings: ttsMerged,
      };
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: energyConfig,
      });
      this._config.power_enforcement = pe;
      this._config.tts_settings = ttsMerged;
      showToast(this.shadowRoot, 'Power enforcement settings saved!', 'success');
      await this._loadPowerData({ force: true });
    } catch (e) {
      console.error('Failed to save enforcement settings:', e);
      const msg = (e && (e.message || e.error_message || e)) ? String(e.message || e.error_message || e) : 'Unknown error';
      showToast(this.shadowRoot, `Failed to save settings: ${msg}`, 'error');
    }
  }

  async _saveSettings() {
    const roomCards = this.shadowRoot.querySelectorAll('.room-settings-card');
    const rooms = [];

    roomCards.forEach((card) => {
      const roomIndex = parseInt(card.dataset.roomIndex);
      const originalRoom = this._config?.rooms?.[roomIndex];
      const nameInput = card.querySelector('.room-name-input');
      const mediaPlayerSelect = card.querySelector('.room-media-player');
      const thresholdInput = card.querySelector('.room-threshold');
      const kwhBudgetInput = card.querySelector('.room-kwh-budget');
      const kwhBoostCheck = card.querySelector('.room-kwh-budget-use-boost');
      const volumeSlider = card.querySelector('.room-volume');
      const outletItems = card.querySelectorAll('.outlet-settings-item');

      const outlets = [];
      outletItems.forEach(item => {
        const outletName = item.querySelector('.outlet-name')?.value;
        const plug1 = item.querySelector('.outlet-plug1')?.value;
        const plug2Select = item.querySelector('.outlet-plug2');
        const plug2 = plug2Select?.value;
        const plug1Switch = item.querySelector('.outlet-plug1-switch')?.value;
        const plug2SwitchSelect = item.querySelector('.outlet-plug2-switch');
        const plug2Switch = plug2SwitchSelect?.value;
        const outletThreshold = parseInt(item.querySelector('.outlet-threshold')?.value) || 0;
        const plug1ShutoffInput = item.querySelector('.outlet-plug1-shutoff');
        const plug1Shutoff = plug1ShutoffInput ? (parseInt(plug1ShutoffInput.value) || 0) : 0;
        const plug2ShutoffInput = item.querySelector('.outlet-plug2-shutoff');
        const plug2Shutoff = plug2ShutoffInput ? (parseInt(plug2ShutoffInput.value) || 0) : 0;
        const isSingleOutlet = !plug2Select;
        const deviceTypeFromItem = item.dataset.deviceType;
        const isStove = deviceTypeFromItem === 'stove';
        const isMicrowave = deviceTypeFromItem === 'microwave';
        const isLight = deviceTypeFromItem === 'light';
        const isAppliance = isStove || isMicrowave;

        if (outletName) {
          const device = {
            name: outletName,
            plug1_entity: plug1 || null,
            threshold: outletThreshold,
          };
          if (isStove) {
            device.type = 'stove';
            device.plug2_entity = null;
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
            device.stove_safety_enabled = item.querySelector('.stove-safety-enabled')?.checked !== false;
            device.stove_power_threshold = parseInt(item.querySelector('.stove-power-threshold')?.value) || 100;
            device.stove_on_debounce_seconds = parseInt(item.querySelector('.stove-on-debounce')?.value) || 0;
            device.stove_off_debounce_seconds = parseInt(item.querySelector('.stove-off-debounce')?.value) || 10;
            device.cooking_time_minutes = parseInt(item.querySelector('.stove-cooking-time')?.value) || 15;
            device.final_warning_seconds = parseInt(item.querySelector('.stove-final-warning')?.value) || 30;
            device.timer_start_window_seconds = parseInt(item.querySelector('.stove-timer-window')?.value) || 10;
            device.presence_sensor = item.querySelector('.stove-presence-sensor')?.value || null;
            const stiEl = item.querySelector('.stove-timer-tts-interval');
            device.stove_timer_tts_interval_seconds = stiEl
              ? Math.max(0, Math.min(3600, parseInt(stiEl.value, 10) || 0))
              : 0;
          } else if (isMicrowave) {
            device.type = 'microwave';
            device.plug2_entity = null;
            device.plug1_switch = null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
            const mwSafetyCheck = item.querySelector('.microwave-safety-enabled');
            device.microwave_safety_enabled = mwSafetyCheck && !mwSafetyCheck.disabled && mwSafetyCheck.checked;
            device.microwave_power_threshold = parseInt(item.querySelector('.microwave-power-threshold')?.value) || 50;
          } else if (isLight) {
            device.type = 'light';
            device.plug1_entity = null;
            device.plug2_entity = null;
            device.plug1_switch = null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
            const switchVal = item.querySelector('.light-switch-entity')?.value || null;
            device.switch_entity = (switchVal && switchVal.startsWith('switch.')) ? switchVal : null;
            const lightRows = item.querySelectorAll('.light-entity-row');
            const lightEntities = [];
            lightRows.forEach(row => {
              const input = row.querySelector('.entity-datalist-input.light-entity-select') || row.querySelector('input.light-entity-select');
              const entityId = input?.value?.trim?.() || '';
              const watts = parseInt(row.querySelector('.light-entity-watts')?.value, 10) || 0;
              const wrgb = row.querySelector('.light-entity-wrgb-toggle')?.checked || false;
              if (entityId && entityId.startsWith('light.')) {
                lightEntities.push({ entity_id: entityId, watts: Math.max(0, watts), wrgb });
              }
            });
            device.light_entities = lightEntities;
            const lps = item.querySelector('.light-power-source')?.value;
            device.power_source = lps === 'sensor' ? 'sensor' : 'configured';
            const lpseIn =
              item.querySelector('.entity-datalist-input.light-power-sensor-entity')
              || item.querySelector('input.light-power-sensor-entity');
            const lpse = (lpseIn?.value || '').trim();
            device.power_sensor_entity =
              device.power_source === 'sensor'
              && (lpse.startsWith('sensor.') || lpse.startsWith('switch.'))
                ? lpse
                : null;
          } else if (deviceTypeFromItem === 'minisplit') {
            device.type = 'minisplit';
            device.plug2_entity = null;
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = null;
            device.plug1_shutoff = plug1Shutoff;
            device.plug2_shutoff = 0;
            const offEl = item.querySelector('.minisplit-enforcement-off-seconds');
            const minWEl = item.querySelector('.minisplit-enforcement-min-watts');
            device.minisplit_enforcement_off_seconds = offEl
              ? Math.max(30, Math.min(600, parseInt(offEl.value, 10) || 60))
              : 60;
            device.minisplit_enforcement_min_watts = minWEl
              ? Math.max(0, Math.min(2000, parseInt(minWEl.value, 10) || 0))
              : 0;
          } else if (deviceTypeFromItem === 'fridge') {
            device.type = 'fridge';
            device.plug2_entity = null;
            device.plug1_switch = null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
          } else if (deviceTypeFromItem === 'vent' || deviceTypeFromItem === 'wall_heater') {
            device.type = deviceTypeFromItem;
            device.plug1_entity = null;
            device.plug2_entity = null;
            device.plug1_switch = null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
            this._applyVentLikePowerFromItem(item, device);
            if (device.type === 'vent') {
              device.vent_automation_enabled = item.querySelector('.vent-automation-enabled')?.checked === true;
              const vpe = (item.querySelector('.entity-datalist-input.vent-presence-entity') || item.querySelector('input.vent-presence-entity'))?.value?.trim() || '';
              device.vent_presence_entity = vpe.startsWith('binary_sensor.') ? vpe : null;
              device.vent_on_debounce_seconds = Math.max(0, Math.min(600, parseInt(item.querySelector('.vent-on-debounce-seconds')?.value, 10) || 30));
              device.vent_off_after_no_presence_seconds = Math.max(10, Math.min(86400, parseInt(item.querySelector('.vent-off-after-no-presence-seconds')?.value, 10) || 300));
            } else {
              device.heater_automation_enabled = item.querySelector('.heater-automation-enabled')?.checked === true;
              const hte = (item.querySelector('.entity-datalist-input.heater-temperature-entity') || item.querySelector('input.heater-temperature-entity'))?.value?.trim() || '';
              device.heater_temperature_entity = hte.startsWith('sensor.') ? hte : null;
              device.heater_on_below_temperature = Math.max(-60, Math.min(160, parseFloat(item.querySelector('.heater-on-below-temperature')?.value) || 65));
              device.heater_stay_on_minutes = Math.max(1, Math.min(240, parseInt(item.querySelector('.heater-stay-on-minutes')?.value, 10) || 5));
              const hctRaw = (item.querySelector('.heater-comfort-temperature')?.value ?? '').trim();
              if (hctRaw === '') {
                device.heater_comfort_temperature = null;
              } else {
                const hv = parseFloat(hctRaw);
                device.heater_comfort_temperature = Number.isFinite(hv)
                  ? Math.max(-60, Math.min(160, hv))
                  : null;
              }
              device.heater_presence_optional_enabled = item.querySelector('.heater-presence-optional-enabled')?.checked === true;
              device.heater_presence_turn_on_enabled = item.querySelector('.heater-presence-turn-on-enabled')?.checked === true;
              const hpe = (item.querySelector('.entity-datalist-input.heater-presence-entity') || item.querySelector('input.heater-presence-entity'))?.value?.trim() || '';
              device.heater_presence_entity = hpe.startsWith('binary_sensor.') ? hpe : null;
              device.heater_presence_cooldown_seconds = Math.max(0, Math.min(7200, parseInt(item.querySelector('.heater-presence-cooldown-seconds')?.value, 10) || 60));
              // Smart heater optimization fields
              const hwe = (item.querySelector('.entity-datalist-input.heater-weather-entity') || item.querySelector('input.heater-weather-entity'))?.value?.trim() || '';
              device.heater_weather_entity = (hwe.startsWith('weather.') || hwe.startsWith('sensor.')) ? hwe : '';
              device.heater_optimization_enabled = item.querySelector('.heater-optimization-enabled')?.checked !== false;
              device.heater_hysteresis_band = Math.max(0, Math.min(10, parseFloat(item.querySelector('.heater-hysteresis-band')?.value) || 2));
              device.heater_duty_cycle_enabled = item.querySelector('.heater-duty-cycle-enabled')?.checked === true;
              device.heater_duty_on_minutes = Math.max(1, Math.min(30, parseInt(item.querySelector('.heater-duty-on-minutes')?.value, 10) || 5));
              device.heater_duty_off_minutes = Math.max(1, Math.min(15, parseInt(item.querySelector('.heater-duty-off-minutes')?.value, 10) || 2));
              device.heater_duty_comfort_margin = Math.max(0, Math.min(10, parseFloat(item.querySelector('.heater-duty-comfort-margin')?.value) || 1.0));
              device.heater_power_aware_enabled = item.querySelector('.heater-power-aware-enabled')?.checked === true;
              device.heater_power_threshold_watts = Math.max(100, Math.min(5000, parseInt(item.querySelector('.heater-power-threshold-watts')?.value, 10) || 500));
              device.heater_learning_enabled = item.querySelector('.heater-learning-enabled')?.checked !== false;
              device.heater_preheat_minutes = Math.max(0, Math.min(120, parseInt(item.querySelector('.heater-preheat-minutes')?.value, 10) || 30));
              device.heater_door_sensor_entity = (item.querySelector('.entity-datalist-input.heater-door-sensor-entity') || item.querySelector('input.heater-door-sensor-entity'))?.value?.trim() || null;
              device.heater_window_sensor_entity = (item.querySelector('.entity-datalist-input.heater-window-sensor-entity') || item.querySelector('input.heater-window-sensor-entity'))?.value?.trim() || null;
            }
          } else {
            device.type = isSingleOutlet ? 'single_outlet' : 'outlet';
            device.plug2_entity = isSingleOutlet ? null : (plug2 || null);
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = isSingleOutlet ? null : (plug2Switch || null);
            device.plug1_shutoff = plug1Shutoff;
            device.plug2_shutoff = isSingleOutlet ? 0 : plug2Shutoff;
          }
          this._applyPresenceAutoOffFromItemToDevice(item, device);
          outlets.push(device);
        }
      });

      const roomName = nameInput?.value?.trim();
      if (roomName) {
        const responsiveToggle = card.querySelector('.responsive-light-warnings-toggle');
        const responsiveColor = card.querySelector('.responsive-light-color-picker');
        const responsiveTemp = card.querySelector('.responsive-light-temp-picker');
        const responsiveInterval = card.querySelector('.responsive-light-interval-picker');
        let rgb = [245, 0, 0];
        if (responsiveColor?.value) {
          const hex = responsiveColor.value;
          rgb = [
            parseInt(hex.slice(1, 3), 16),
            parseInt(hex.slice(3, 5), 16),
            parseInt(hex.slice(5, 7), 16),
          ];
        }
        const tempK = parseInt(responsiveTemp?.value, 10) || 6500;
        const interval = parseFloat(responsiveInterval?.value) || 1.5;
        // Preserve existing values if not explicitly set
        const mediaPlayerValue = mediaPlayerSelect?.value;
        const mediaPlayer = mediaPlayerValue !== undefined && mediaPlayerValue !== '' 
          ? mediaPlayerValue 
          : (originalRoom?.media_player || null);
        
        rooms.push({
          id: roomName.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
          name: roomName,
          media_player: mediaPlayer,
          threshold: parseInt(thresholdInput?.value) || 0,
          kwh_budget: parseFloat(kwhBudgetInput?.value) ?? 5,
          kwh_budget_use_boost: kwhBoostCheck ? kwhBoostCheck.checked : true,
          volume: parseFloat(volumeSlider?.value) || 0.7,
          responsive_light_warnings: responsiveToggle?.checked === true && !responsiveToggle.disabled,
          responsive_light_color: rgb,
          responsive_light_temp: tempK,
          responsive_light_interval: interval,
          presence_person_entity: this._collectPresencePersonFromCard(card),
          presence_zone_entities: this._collectPresenceZonesFromCard(card),
          room_icon: this._collectRoomIconFromCard(card),
          outlets: outlets,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';
    const ttsPrefix = this.shadowRoot.querySelector('#tts-prefix')?.value || 'Message from Home Energy.';
    const ttsRoomWarn = this.shadowRoot.querySelector('#tts-room-warn')?.value || '';
    const ttsOutletWarn = this.shadowRoot.querySelector('#tts-outlet-warn')?.value || '';
    const ttsBudgetExceeded = this.shadowRoot.querySelector('#tts-budget-exceeded')?.value || '';
    const ttsShutoff = this.shadowRoot.querySelector('#tts-shutoff')?.value || '{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload';
    const ttsStoveOn = this.shadowRoot.querySelector('#tts-stove-on')?.value || '{prefix} Stove has been turned on';
    const ttsStoveOff = this.shadowRoot.querySelector('#tts-stove-off')?.value || '{prefix} Stove has been turned off';
    const ttsStoveTimerStarted = this.shadowRoot.querySelector('#tts-stove-timer-started')?.value || '{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.';
    const ttsStoveTimerProgress = this.shadowRoot.querySelector('#tts-stove-timer-progress')?.value ?? '';
    const ttsStove15Min = this.shadowRoot.querySelector('#tts-stove-15min')?.value || '{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns';
    const ttsStove30Sec = this.shadowRoot.querySelector('#tts-stove-30sec')?.value || '{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen';
    const ttsStoveAutoOff = this.shadowRoot.querySelector('#tts-stove-auto-off')?.value || '{prefix} Stove has been automatically turned off for safety';
    const ttsPhase1Warn = this.shadowRoot.querySelector('#tts-phase1-warn')?.value || '';
    const ttsPhase2Warn = this.shadowRoot.querySelector('#tts-phase2-warn')?.value || '';
    const ttsPhase2After = this.shadowRoot.querySelector('#tts-phase2-after')?.value || '';
    const ttsMinisplitPhase2Warn = this.shadowRoot.querySelector('#tts-minisplit-phase2-warn')?.value ?? '';
    const ttsMinisplitPhase2After = this.shadowRoot.querySelector('#tts-minisplit-phase2-after')?.value ?? '';
    const ttsMinisplitPhase2Restore = this.shadowRoot.querySelector('#tts-minisplit-phase2-restore')?.value ?? '';
    const ttsPhaseReset = this.shadowRoot.querySelector('#tts-phase-reset')?.value || '';
    const ttsRoomKwhWarn = this.shadowRoot.querySelector('#tts-room-kwh-warn')?.value || '';
    const ttsHomeKwhWarn = this.shadowRoot.querySelector('#tts-home-kwh-warn')?.value || '';
    const budgetBoostSchedule = this._collectBudgetBoostFromDom();
    const ttsBudgetBoostScheduled = this.shadowRoot.querySelector('#tts-budget-boost-scheduled')?.value ?? '';
    const ttsPhase1BoostDay = this.shadowRoot.querySelector('#tts-phase1-boost-day')?.value ?? '';
    const ttsDefaultMediaPlayer = (
      this.shadowRoot.querySelector('.entity-datalist-input.tts-default-mp')?.value || ''
    ).trim();

    const ttsLineOn = (id) => this.shadowRoot.querySelector(`#${id}`)?.checked !== false;

    const tabStats = this.shadowRoot.querySelector('#tab-statistics');
    const _si = (cls) => (tabStats?.querySelector(`input.${cls}`)?.value ?? '').trim();
    const statsRefreshEl = tabStats?.querySelector('#stats-refresh-seconds');
    const statsRefreshParsed = parseInt(statsRefreshEl?.value, 10);
    const statistics_refresh_seconds = Number.isFinite(statsRefreshParsed)
      ? Math.max(15, Math.min(600, statsRefreshParsed))
      : 60;
    const statistics_settings = {
      billing_start_sensor: _si('stats-billing-start'),
      billing_end_sensor: _si('stats-billing-end'),
      current_usage_sensor: _si('stats-current-usage'),
      projected_usage_sensor: _si('stats-projected-usage'),
      kwh_cost_sensor: _si('stats-kwh-cost'),
      statistics_refresh_seconds,
    };

    const tabEff = this.shadowRoot.querySelector('#tab-efficiency');
    const _efFloat = (id, def, min, max) => {
      const el = tabEff?.querySelector(`#${id}`);
      let v = parseFloat(el?.value);
      if (!Number.isFinite(v)) v = def;
      return Math.max(min, Math.min(max, v));
    };
    const _efInt = (id, def, min, max) => {
      const el = tabEff?.querySelector(`#${id}`);
      let v = parseInt(el?.value, 10);
      if (!Number.isFinite(v)) v = def;
      return Math.max(min, Math.min(max, v));
    };
    const digestTimeRaw = tabEff?.querySelector('#eff-digest-time')?.value || '08:00';
    const digestTimeM = /^(\d{1,2}):(\d{2})$/.exec(String(digestTimeRaw).trim());
    let digestH = 8;
    let digestMi = 0;
    if (digestTimeM) {
      digestH = Math.max(0, Math.min(23, parseInt(digestTimeM[1], 10)));
      digestMi = Math.max(0, Math.min(59, parseInt(digestTimeM[2], 10)));
    }
    const efficiency_digest_time = `${String(digestH).padStart(2, '0')}:${String(digestMi).padStart(2, '0')}`;
    const efficiency_settings = {
      history_window_days: _efInt('eff-history-window-days', 14, 1, 90),
      engagement_lookback_days: _efInt('eff-engagement-lookback', 7, 1, 30),
      compliance_tolerance: _efFloat('eff-compliance-tol', 1.0, 1.0, 1.5),
      warning_points_per_event: _efFloat('eff-warning-points', 5.5, 0.25, 25),
      consumption_peer_multiplier: _efFloat('eff-peer-mult', 1.25, 0.5, 5),
      load_high_watts: _efFloat('eff-load-high-w', 100, 1, 5000),
      load_penalty_per_high_hour: _efFloat('eff-load-penalty', 11, 0, 50),
      engagement_distinct_hours_target: _efInt('eff-eng-distinct-hours', 14, 1, 24),
      engagement_hours_weight: _efFloat('eff-eng-hours-weight', 70, 0, 100),
      engagement_visits_weight: _efFloat('eff-eng-visits-weight', 30, 0, 100),
      engagement_visits_daily_norm: _efFloat('eff-eng-daily-norm', 3, 1, 48),
      engagement_max_visits_per_hour: _efInt('eff-eng-max-hour', 2, 1, 10),
      efficiency_digest_enabled: tabEff?.querySelector('#eff-digest-enabled')?.checked === true,
      efficiency_digest_time,
      efficiency_digest_title: tabEff?.querySelector('#eff-digest-title')?.value ?? '',
      efficiency_digest_message: tabEff?.querySelector('#eff-digest-message')?.value ?? '',
    };

    const tabEnf = this.shadowRoot.querySelector('#tab-enforcement');
    const _pei = (id) => {
      const el = tabEnf?.querySelector(`#${id}`);
      if (!el) return null;
      if (el.type === 'checkbox') return el.checked;
      const v = el.value;
      return v !== undefined && v !== null ? String(v).trim() : null;
    };
    const roomsEnabled = [];
    tabEnf?.querySelectorAll('.pe-room-checkbox:checked').forEach(cb => roomsEnabled.push(cb.dataset.roomId || ''));
    const rkwhRaw = _pei('pe-room-kwh-intervals');
    const rkwhStr =
      rkwhRaw != null && rkwhRaw !== false ? String(rkwhRaw).trim() : '5, 10, 15, 20';
    const rkwhParsed = this._parseRoomKwhIntervals(rkwhStr);
    if (!rkwhParsed.valid) {
      showToast(
        this.shadowRoot,
        'Room kWh intervals must be exactly four comma-separated increasing positive numbers (e.g. 5, 10, 15, 20).',
        'error',
      );
      return;
    }
    const power_enforcement = {
      enabled: _pei('pe-enabled') === true,
      phase1_enabled: _pei('pe-phase1-enabled') !== false,
      phase2_enabled: _pei('pe-phase2-enabled') !== false,
      phase1_warning_count: parseInt(_pei('pe-phase1-count')) || 20,
      phase1_time_window_minutes: parseInt(_pei('pe-phase1-window')) || 60,
      phase1_volume_increment: parseInt(_pei('pe-phase1-vol-inc')) || 2,
      phase1_reset_minutes: parseInt(_pei('pe-phase1-reset')) || 60,
      phase2_warning_count: parseInt(_pei('pe-phase2-count')) || 10,
      phase2_time_window_minutes: parseInt(_pei('pe-phase2-window')) || 10,
      phase2_cycle_delay_seconds: parseInt(_pei('pe-phase2-delay')) || 5,
      phase2_reset_minutes: parseInt(_pei('pe-phase2-reset')) || 30,
      phase2_max_volume: Math.max(0, Math.min(100, parseInt(_pei('pe-phase2-max-volume')) || 100)),
      room_kwh_intervals: rkwhParsed.intervals,
      home_kwh_limit: parseInt(_pei('pe-home-kwh-limit')) || 22,
      rooms_enabled: roomsEnabled,
    };

    const config = {
      rooms: rooms,
      breaker_lines: this._config?.breaker_lines || [],
      breaker_panel_size: this._config?.breaker_panel_size ?? 20,
      statistics_settings,
      efficiency_settings,
      tts_settings: {
        language: ttsLanguage,
        speed: this._config?.tts_settings?.speed ?? 1.0,
        volume: this._config?.tts_settings?.volume ?? 0.7,
        min_interval_seconds: Math.max(1, Math.min(60, parseInt(this.shadowRoot.querySelector('#tts-min-interval')?.value) || 3)),
        tts_default_media_player: ttsDefaultMediaPlayer,
        prefix: ttsPrefix,
        room_warn_tts_enabled: ttsLineOn('tts-enable-room-warn'),
        outlet_warn_tts_enabled: ttsLineOn('tts-enable-outlet-warn'),
        budget_exceeded_tts_enabled: ttsLineOn('tts-enable-budget-exceeded'),
        budget_boost_scheduled_tts_enabled: ttsLineOn('tts-enable-budget-boost-scheduled'),
        phase1_warn_boost_day_tts_enabled: ttsLineOn('tts-enable-phase1-warn-boost-day'),
        shutoff_tts_enabled: ttsLineOn('tts-enable-shutoff'),
        stove_on_tts_enabled: ttsLineOn('tts-enable-stove-on'),
        stove_off_tts_enabled: ttsLineOn('tts-enable-stove-off'),
        stove_timer_started_tts_enabled: ttsLineOn('tts-enable-stove-timer-started'),
        stove_timer_progress_tts_enabled: ttsLineOn('tts-enable-stove-timer-progress'),
        stove_15min_warn_tts_enabled: ttsLineOn('tts-enable-stove-15min-warn'),
        stove_30sec_warn_tts_enabled: ttsLineOn('tts-enable-stove-30sec-warn'),
        stove_auto_off_tts_enabled: ttsLineOn('tts-enable-stove-auto-off'),
        phase1_warn_tts_enabled: ttsLineOn('tts-enable-phase1-warn'),
        phase2_warn_tts_enabled: ttsLineOn('tts-enable-phase2-warn'),
        phase2_after_tts_enabled: ttsLineOn('tts-enable-phase2-after'),
        minisplit_phase2_warn_tts_enabled: ttsLineOn('tts-enable-minisplit-phase2-warn'),
        minisplit_phase2_after_tts_enabled: ttsLineOn('tts-enable-minisplit-phase2-after'),
        minisplit_phase2_restore_tts_enabled: ttsLineOn('tts-enable-minisplit-phase2-restore'),
        phase_reset_tts_enabled: ttsLineOn('tts-enable-phase-reset'),
        room_kwh_warn_tts_enabled: ttsLineOn('tts-enable-room-kwh-warn'),
        home_kwh_warn_tts_enabled: ttsLineOn('tts-enable-home-kwh-warn'),
        room_warn_msg: ttsRoomWarn,
        outlet_warn_msg: ttsOutletWarn,
        budget_exceeded_msg: ttsBudgetExceeded,
        shutoff_msg: ttsShutoff,
        stove_on_msg: ttsStoveOn,
        stove_off_msg: ttsStoveOff,
        stove_timer_started_msg: ttsStoveTimerStarted,
        stove_timer_progress_msg: ttsStoveTimerProgress,
        stove_15min_warn_msg: ttsStove15Min,
        stove_30sec_warn_msg: ttsStove30Sec,
        stove_auto_off_msg: ttsStoveAutoOff,
        vent_automation_tts_enabled: this.shadowRoot.querySelector('#tts-vent-automation-enabled')?.checked === true,
        heater_automation_tts_enabled: this.shadowRoot.querySelector('#tts-heater-automation-enabled')?.checked === true,
        vent_automation_on_msg: this.shadowRoot.querySelector('#tts-vent-automation-msg')?.value ?? '',
        heater_automation_on_msg: this.shadowRoot.querySelector('#tts-heater-automation-msg')?.value ?? '',
        notifications_enabled: this.shadowRoot.querySelector('#tts-notifications-enabled')?.checked === true,
        notification_title: this.shadowRoot.querySelector('#notify-notification-title')?.value ?? '',
        notify_room_budget_hit: this.shadowRoot.querySelector('#tts-notify-room-budget-hit')?.checked !== false,
        notify_enforcement_phase_change: this.shadowRoot.querySelector('#tts-notify-enforcement-phase-change')?.checked !== false,
        notify_ac_auto_off: this.shadowRoot.querySelector('#tts-notify-ac-auto-off')?.checked !== false,
        notify_ac_auto_on: this.shadowRoot.querySelector('#tts-notify-ac-auto-on')?.checked !== false,
        notify_person_toggle: this.shadowRoot.querySelector('#tts-notify-person-toggle')?.checked !== false,
        notify_integration_auto: this.shadowRoot.querySelector('#tts-notify-integration-auto')?.checked !== false,
        notify_heater_auto: this.shadowRoot.querySelector('#tts-notify-heater-auto')?.checked !== false,
        notify_vent_auto: this.shadowRoot.querySelector('#tts-notify-vent-auto')?.checked !== false,
        notify_external_auto: this.shadowRoot.querySelector('#tts-notify-external-auto')?.checked !== false,
        zone_health_check_enabled: this.shadowRoot.querySelector('#tts-zone-health-check')?.checked !== false,
        zone_health_history_days: (() => {
          const d = parseInt(this.shadowRoot.querySelector('#zone-health-history-days')?.value, 10);
          return [1, 2, 3].includes(d) ? d : 3;
        })(),
        zone_health_reminder_hours: Math.max(1, Math.min(24, parseInt(this.shadowRoot.querySelector('#zone-health-reminder-hours')?.value, 10) || 1)),
        zone_health_notification_msg: this.shadowRoot.querySelector('#zone-health-notification-msg')?.value ?? '',
        zone_health_reminder_tts_msg: this.shadowRoot.querySelector('#zone-health-reminder-tts-msg')?.value ?? '',
        notify_budget_hit_title: this.shadowRoot.querySelector('#notify-budget-hit-title')?.value ?? '',
        notify_budget_hit_msg: this.shadowRoot.querySelector('#notify-budget-hit-msg')?.value ?? '',
        notify_enforcement_phase1_title: this.shadowRoot.querySelector('#notify-enforcement-phase1-title')?.value ?? '',
        notify_enforcement_phase1_msg: this.shadowRoot.querySelector('#notify-enforcement-phase1-msg')?.value ?? '',
        notify_enforcement_phase2_title: this.shadowRoot.querySelector('#notify-enforcement-phase2-title')?.value ?? '',
        notify_enforcement_phase2_msg: this.shadowRoot.querySelector('#notify-enforcement-phase2-msg')?.value ?? '',
        notify_ac_auto_off_title: this.shadowRoot.querySelector('#notify-ac-auto-off-title')?.value ?? '',
        notify_ac_auto_off_msg: this.shadowRoot.querySelector('#notify-ac-auto-off-msg')?.value ?? '',
        notify_ac_auto_on_title: this.shadowRoot.querySelector('#notify-ac-auto-on-title')?.value ?? '',
        notify_ac_auto_on_msg: this.shadowRoot.querySelector('#notify-ac-auto-on-msg')?.value ?? '',
        notify_toggle_title: this.shadowRoot.querySelector('#notify-toggle-title')?.value ?? '',
        notify_toggle_msg: this.shadowRoot.querySelector('#notify-toggle-msg')?.value ?? '',
        notify_heater_auto_on_title: this.shadowRoot.querySelector('#notify-heater-auto-on-title')?.value ?? '',
        notify_heater_auto_on_msg: this.shadowRoot.querySelector('#notify-heater-auto-on-msg')?.value ?? '',
        notify_heater_auto_off_title: this.shadowRoot.querySelector('#notify-heater-auto-off-title')?.value ?? '',
        notify_heater_auto_off_msg: this.shadowRoot.querySelector('#notify-heater-auto-off-msg')?.value ?? '',
        notify_vent_auto_on_title: this.shadowRoot.querySelector('#notify-vent-auto-on-title')?.value ?? '',
        notify_vent_auto_on_msg: this.shadowRoot.querySelector('#notify-vent-auto-on-msg')?.value ?? '',
        notify_vent_auto_off_title: this.shadowRoot.querySelector('#notify-vent-auto-off-title')?.value ?? '',
        notify_vent_auto_off_msg: this.shadowRoot.querySelector('#notify-vent-auto-off-msg')?.value ?? '',
        phase1_warn_msg: ttsPhase1Warn,
        phase2_warn_msg: ttsPhase2Warn,
        phase2_after_msg: ttsPhase2After,
        minisplit_phase2_warn_msg: ttsMinisplitPhase2Warn,
        minisplit_phase2_after_msg: ttsMinisplitPhase2After,
        minisplit_phase2_restore_msg: ttsMinisplitPhase2Restore,
        phase_reset_msg: ttsPhaseReset,
        room_kwh_warn_msg: ttsRoomKwhWarn,
        home_kwh_warn_msg: ttsHomeKwhWarn,
        ...budgetBoostSchedule,
        budget_boost_scheduled_msg: ttsBudgetBoostScheduled,
        phase1_warn_msg_boost_day: ttsPhase1BoostDay,
      },
      power_enforcement,
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: config,
      });

      this._config = config;
      showToast(this.shadowRoot, 'Settings saved!', 'success');

      try {
        localStorage.removeItem('smart_dashboards_stats_v1');
      } catch (_e) {
        /* ignore */
      }
      this._statsData = null;
      this._statsFetchedAt = null;

      setTimeout(async () => {
        await this._loadPowerData({ force: true });
        this._render();
        this._startRefresh();
        if (!this._showSettings) {
          void this._loadStatistics();
        }
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      const msg = (e && (e.message || e.error_message || e)) ? String(e.message || e.error_message || e) : 'Unknown error';
      showToast(this.shadowRoot, `Failed to save settings: ${msg}`, 'error');
    }
  }

  async _saveSingleRoom(roomIndex) {
    const roomCards = this.shadowRoot.querySelectorAll('.room-settings-card');
    const card = Array.from(roomCards).find(c => parseInt(c.dataset.roomIndex) === roomIndex);
    if (!card) return;

    const originalRoom = this._config?.rooms?.[roomIndex];
    const nameInput = card.querySelector('.room-name-input');
    const mediaPlayerSelect = card.querySelector('.room-media-player');
    const thresholdInput = card.querySelector('.room-threshold');
    const kwhBudgetInputSingle = card.querySelector('.room-kwh-budget');
    const kwhBoostCheckSingle = card.querySelector('.room-kwh-budget-use-boost');
    const volumeSlider = card.querySelector('.room-volume');
    const outletItems = card.querySelectorAll('.outlet-settings-item');

    const outlets = [];
    outletItems.forEach(item => {
      const outletName = item.querySelector('.outlet-name')?.value;
      const plug1 = item.querySelector('.outlet-plug1')?.value;
      const plug2Select = item.querySelector('.outlet-plug2');
      const plug2 = plug2Select?.value;
      const plug1Switch = item.querySelector('.outlet-plug1-switch')?.value;
      const plug2SwitchSelect = item.querySelector('.outlet-plug2-switch');
      const plug2Switch = plug2SwitchSelect?.value;
      const outletThreshold = parseInt(item.querySelector('.outlet-threshold')?.value) || 0;
      const plug1ShutoffInput = item.querySelector('.outlet-plug1-shutoff');
      const plug1Shutoff = plug1ShutoffInput ? (parseInt(plug1ShutoffInput.value) || 0) : 0;
      const plug2ShutoffInput = item.querySelector('.outlet-plug2-shutoff');
      const plug2Shutoff = plug2ShutoffInput ? (parseInt(plug2ShutoffInput.value) || 0) : 0;
      const isSingleOutlet = !plug2Select;
      const deviceTypeFromItem = item.dataset.deviceType;
      const isStove = deviceTypeFromItem === 'stove';
      const isMicrowave = deviceTypeFromItem === 'microwave';
      const isLight = deviceTypeFromItem === 'light';

      if (outletName) {
        const device = {
          name: outletName,
          plug1_entity: plug1 || null,
          threshold: outletThreshold,
        };
        if (isStove) {
          device.type = 'stove';
          device.plug2_entity = null;
          device.plug1_switch = plug1Switch || null;
          device.plug2_switch = null;
          device.plug1_shutoff = 0;
          device.plug2_shutoff = 0;
          device.stove_safety_enabled = item.querySelector('.stove-safety-enabled')?.checked !== false;
          device.stove_power_threshold = parseInt(item.querySelector('.stove-power-threshold')?.value) || 100;
          device.stove_on_debounce_seconds = parseInt(item.querySelector('.stove-on-debounce')?.value) || 0;
          device.stove_off_debounce_seconds = parseInt(item.querySelector('.stove-off-debounce')?.value) || 10;
          device.cooking_time_minutes = parseInt(item.querySelector('.stove-cooking-time')?.value) || 15;
          device.final_warning_seconds = parseInt(item.querySelector('.stove-final-warning')?.value) || 30;
          device.timer_start_window_seconds = parseInt(item.querySelector('.stove-timer-window')?.value) || 10;
          device.presence_sensor = item.querySelector('.stove-presence-sensor')?.value || null;
          const stiEl2 = item.querySelector('.stove-timer-tts-interval');
          device.stove_timer_tts_interval_seconds = stiEl2
            ? Math.max(0, Math.min(3600, parseInt(stiEl2.value, 10) || 0))
            : 0;
        } else if (isMicrowave) {
          device.type = 'microwave';
          device.plug2_entity = null;
          device.plug1_switch = null;
          device.plug2_switch = null;
          device.plug1_shutoff = 0;
          device.plug2_shutoff = 0;
          const mwSafetyCheck = item.querySelector('.microwave-safety-enabled');
          device.microwave_safety_enabled = mwSafetyCheck && !mwSafetyCheck.disabled && mwSafetyCheck.checked;
          device.microwave_power_threshold = parseInt(item.querySelector('.microwave-power-threshold')?.value) || 50;
        } else if (isLight) {
          device.type = 'light';
          device.plug1_entity = null;
          device.plug2_entity = null;
          device.plug1_switch = null;
          device.plug2_switch = null;
          device.plug1_shutoff = 0;
          device.plug2_shutoff = 0;
          const switchVal = item.querySelector('.light-switch-entity')?.value || null;
          device.switch_entity = (switchVal && switchVal.startsWith('switch.')) ? switchVal : null;
          const lightRows = item.querySelectorAll('.light-entity-row');
          const lightEntities = [];
          lightRows.forEach(row => {
            const input = row.querySelector('.entity-datalist-input.light-entity-select') || row.querySelector('input.light-entity-select');
            const entityId = input?.value?.trim?.() || '';
            const watts = parseInt(row.querySelector('.light-entity-watts')?.value, 10) || 0;
            const wrgb = row.querySelector('.light-entity-wrgb-toggle')?.checked || false;
            if (entityId && entityId.startsWith('light.')) {
              lightEntities.push({ entity_id: entityId, watts: Math.max(0, watts), wrgb });
            }
            });
            device.light_entities = lightEntities;
            const lps2 = item.querySelector('.light-power-source')?.value;
            device.power_source = lps2 === 'sensor' ? 'sensor' : 'configured';
            const lpseIn2 =
              item.querySelector('.entity-datalist-input.light-power-sensor-entity')
              || item.querySelector('input.light-power-sensor-entity');
            const lpse2 = (lpseIn2?.value || '').trim();
            device.power_sensor_entity =
              device.power_source === 'sensor'
              && (lpse2.startsWith('sensor.') || lpse2.startsWith('switch.'))
                ? lpse2
                : null;
          } else if (deviceTypeFromItem === 'minisplit') {
            device.type = 'minisplit';
            device.plug2_entity = null;
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = null;
            device.plug1_shutoff = plug1Shutoff;
            device.plug2_shutoff = 0;
            const offEl2 = item.querySelector('.minisplit-enforcement-off-seconds');
          const minWEl2 = item.querySelector('.minisplit-enforcement-min-watts');
          device.minisplit_enforcement_off_seconds = offEl2
            ? Math.max(30, Math.min(600, parseInt(offEl2.value, 10) || 60))
            : 60;
          device.minisplit_enforcement_min_watts = minWEl2
            ? Math.max(0, Math.min(2000, parseInt(minWEl2.value, 10) || 0))
            : 0;
        } else if (deviceTypeFromItem === 'fridge') {
          device.type = 'fridge';
          device.plug2_entity = null;
          device.plug1_switch = null;
          device.plug2_switch = null;
          device.plug1_shutoff = 0;
          device.plug2_shutoff = 0;
        } else if (deviceTypeFromItem === 'vent' || deviceTypeFromItem === 'wall_heater') {
          device.type = deviceTypeFromItem;
          device.plug1_entity = null;
          device.plug2_entity = null;
          device.plug1_switch = null;
          device.plug2_switch = null;
          device.plug1_shutoff = 0;
          device.plug2_shutoff = 0;
          this._applyVentLikePowerFromItem(item, device);
          if (device.type === 'vent') {
            device.vent_automation_enabled = item.querySelector('.vent-automation-enabled')?.checked === true;
            const vpe = (item.querySelector('.entity-datalist-input.vent-presence-entity') || item.querySelector('input.vent-presence-entity'))?.value?.trim() || '';
            device.vent_presence_entity = vpe.startsWith('binary_sensor.') ? vpe : null;
            device.vent_on_debounce_seconds = Math.max(0, Math.min(600, parseInt(item.querySelector('.vent-on-debounce-seconds')?.value, 10) || 30));
            device.vent_off_after_no_presence_seconds = Math.max(10, Math.min(86400, parseInt(item.querySelector('.vent-off-after-no-presence-seconds')?.value, 10) || 300));
          } else {
            device.heater_automation_enabled = item.querySelector('.heater-automation-enabled')?.checked === true;
            const hte = (item.querySelector('.entity-datalist-input.heater-temperature-entity') || item.querySelector('input.heater-temperature-entity'))?.value?.trim() || '';
            device.heater_temperature_entity = hte.startsWith('sensor.') ? hte : null;
            device.heater_on_below_temperature = Math.max(-60, Math.min(160, parseFloat(item.querySelector('.heater-on-below-temperature')?.value) || 65));
            device.heater_stay_on_minutes = Math.max(1, Math.min(240, parseInt(item.querySelector('.heater-stay-on-minutes')?.value, 10) || 5));
            const hctRaw2 = (item.querySelector('.heater-comfort-temperature')?.value ?? '').trim();
            if (hctRaw2 === '') {
              device.heater_comfort_temperature = null;
            } else {
              const hv2 = parseFloat(hctRaw2);
              device.heater_comfort_temperature = Number.isFinite(hv2)
                ? Math.max(-60, Math.min(160, hv2))
                : null;
            }
            device.heater_presence_optional_enabled = item.querySelector('.heater-presence-optional-enabled')?.checked === true;
            device.heater_presence_turn_on_enabled = item.querySelector('.heater-presence-turn-on-enabled')?.checked === true;
            const hpe = (item.querySelector('.entity-datalist-input.heater-presence-entity') || item.querySelector('input.heater-presence-entity'))?.value?.trim() || '';
            device.heater_presence_entity = hpe.startsWith('binary_sensor.') ? hpe : null;
            device.heater_presence_cooldown_seconds = Math.max(0, Math.min(7200, parseInt(item.querySelector('.heater-presence-cooldown-seconds')?.value, 10) || 60));
            // Smart heater optimization fields
            const hwe2 = (item.querySelector('.entity-datalist-input.heater-weather-entity') || item.querySelector('input.heater-weather-entity'))?.value?.trim() || '';
            device.heater_weather_entity = (hwe2.startsWith('weather.') || hwe2.startsWith('sensor.')) ? hwe2 : '';
            device.heater_optimization_enabled = item.querySelector('.heater-optimization-enabled')?.checked !== false;
            device.heater_hysteresis_band = Math.max(0, Math.min(10, parseFloat(item.querySelector('.heater-hysteresis-band')?.value) || 2));
            device.heater_duty_cycle_enabled = item.querySelector('.heater-duty-cycle-enabled')?.checked === true;
            device.heater_duty_on_minutes = Math.max(1, Math.min(30, parseInt(item.querySelector('.heater-duty-on-minutes')?.value, 10) || 5));
            device.heater_duty_off_minutes = Math.max(1, Math.min(15, parseInt(item.querySelector('.heater-duty-off-minutes')?.value, 10) || 2));
            device.heater_duty_comfort_margin = Math.max(0, Math.min(10, parseFloat(item.querySelector('.heater-duty-comfort-margin')?.value) || 1.0));
            device.heater_power_aware_enabled = item.querySelector('.heater-power-aware-enabled')?.checked === true;
            device.heater_power_threshold_watts = Math.max(100, Math.min(5000, parseInt(item.querySelector('.heater-power-threshold-watts')?.value, 10) || 500));
            device.heater_learning_enabled = item.querySelector('.heater-learning-enabled')?.checked !== false;
            device.heater_preheat_minutes = Math.max(0, Math.min(120, parseInt(item.querySelector('.heater-preheat-minutes')?.value, 10) || 30));
            device.heater_door_sensor_entity = (item.querySelector('.entity-datalist-input.heater-door-sensor-entity') || item.querySelector('input.heater-door-sensor-entity'))?.value?.trim() || null;
            device.heater_window_sensor_entity = (item.querySelector('.entity-datalist-input.heater-window-sensor-entity') || item.querySelector('input.heater-window-sensor-entity'))?.value?.trim() || null;
          }
        } else {
          device.type = isSingleOutlet ? 'single_outlet' : 'outlet';
          device.plug2_entity = isSingleOutlet ? null : (plug2 || null);
          device.plug1_switch = plug1Switch || null;
          device.plug2_switch = isSingleOutlet ? null : (plug2Switch || null);
          device.plug1_shutoff = plug1Shutoff;
          device.plug2_shutoff = isSingleOutlet ? 0 : plug2Shutoff;
        }
        this._applyPresenceAutoOffFromItemToDevice(item, device);
        outlets.push(device);
      }
    });

    const roomName = nameInput?.value?.trim();
    if (!roomName) {
      showToast(this.shadowRoot, 'Room name is required', 'error');
      return;
    }

    const responsiveToggle = card.querySelector('.responsive-light-warnings-toggle');
    const responsiveColor = card.querySelector('.responsive-light-color-picker');
    const responsiveTemp = card.querySelector('.responsive-light-temp-picker');
    const responsiveInterval = card.querySelector('.responsive-light-interval-picker');
    let rgb = [245, 0, 0];
    if (responsiveColor?.value) {
      const hex = responsiveColor.value;
      rgb = [
        parseInt(hex.slice(1, 3), 16),
        parseInt(hex.slice(3, 5), 16),
        parseInt(hex.slice(5, 7), 16),
      ];
    }
    const tempK = parseInt(responsiveTemp?.value, 10) || 6500;
    const interval = parseFloat(responsiveInterval?.value) || 1.5;

    // Preserve existing values if not explicitly set
    const mediaPlayerValue = mediaPlayerSelect?.value;
    const mediaPlayer = mediaPlayerValue !== undefined && mediaPlayerValue !== '' 
      ? mediaPlayerValue 
      : (originalRoom?.media_player || null);

    const kbRaw = kwhBudgetInputSingle?.value;
    const kbParsed = kbRaw !== undefined && kbRaw !== '' ? parseFloat(kbRaw) : NaN;
    const kwhBudgetVal = Number.isFinite(kbParsed)
      ? kbParsed
      : (originalRoom?.kwh_budget ?? 5);

    const updatedRoom = {
      id: roomName.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
      name: roomName,
      media_player: mediaPlayer,
      threshold: parseInt(thresholdInput?.value) || 0,
      kwh_budget: kwhBudgetVal,
      kwh_budget_use_boost: kwhBoostCheckSingle ? kwhBoostCheckSingle.checked : (originalRoom?.kwh_budget_use_boost !== false),
      volume: parseFloat(volumeSlider?.value) || 0.7,
      responsive_light_warnings: responsiveToggle?.checked === true && !responsiveToggle.disabled,
      responsive_light_color: rgb,
      responsive_light_temp: tempK,
      responsive_light_interval: interval,
      presence_person_entity: this._collectPresencePersonFromCard(card),
      presence_zone_entities: this._collectPresenceZonesFromCard(card),
      room_icon: this._collectRoomIconFromCard(card),
      outlets: outlets,
    };

    // Get all rooms - use existing config and update just this one
    const allRooms = [...(this._config?.rooms || [])];
    
    // Update the room at the specified index
    if (allRooms.length > roomIndex) {
      allRooms[roomIndex] = updatedRoom;
    } else {
      // If room doesn't exist yet, pad with nulls and add it
      while (allRooms.length < roomIndex) {
        allRooms.push(null);
      }
      allRooms[roomIndex] = updatedRoom;
    }
    
    // Filter out null entries
    const filteredRooms = allRooms.filter(r => r !== null);

    // Get TTS settings from current config
    const ttsSettings = this._config?.tts_settings || {};

    const config = {
      ...this._config,
      rooms: filteredRooms,
      tts_settings: ttsSettings,
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: config,
      });

      this._config = { ...this._config, ...config };
      showToast(this.shadowRoot, 'Room saved!', 'success');

      setTimeout(async () => {
        await this._loadPowerData({ force: true });
        this._render();
        this._startRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save room:', e);
      const msg = (e && (e.message || e.error_message || e)) ? String(e.message || e.error_message || e) : 'Unknown error';
      showToast(this.shadowRoot, `Failed to save room: ${msg}`, 'error');
    }
  }
}

customElements.define('energy-panel', EnergyPanel);
