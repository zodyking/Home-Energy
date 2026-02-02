/**
 * Energy Panel for Smart Dashboards
 * Room-based power monitoring with automatic TTS threshold alerts
 */

import { sharedStyles, icons, showToast, passcodeModalStyles, showPasscodeModal, renderCustomSelect, initCustomSelects } from './shared-utils.js';

class EnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._powerData = null;
    this._showSettings = false;
    this._settingsTab = 'rooms'; // 'rooms', 'tts', 'breakers', or 'stove'
    this._dashboardView = 'outlets'; // 'outlets' or 'breakers'
    this._breakerData = null;
    this._stoveData = null;
    this._refreshInterval = null;
    this._loading = true;
    this._error = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) {
      this._loadConfig();
    }
  }

  set panel(panel) {
    this._panelConfig = panel.config;
  }

  connectedCallback() {
    this._render();
    this._loadConfig();
  }

  disconnectedCallback() {
    this._stopRefresh();
  }

  _startRefresh() {
    this._stopRefresh();
    this._refreshInterval = setInterval(() => {
      this._loadPowerData();
      this._loadBreakerData();
    }, 1000);
  }

  _stopRefresh() {
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
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
      this._entities = entities;
      this._entities.switches = switchesResult.switches || [];
      this._entities.binary_sensors = entities.binary_sensors || [];
      this._areas = areasResult.areas || [];
      this._areaSensors = {};
      this._areaSwitches = {};
      await Promise.all([
        this._loadPowerData(),
        this._loadBreakerData(),
      ]);
      this._loading = false;
      this._render();
      this._startRefresh();
    } catch (e) {
      console.error('Failed to load energy config:', e);
      this._loading = false;
      this._error = e.message || 'Failed to load configuration';
      this._render();
    }
  }

  async _loadAreaSensors(areaId) {
    if (!areaId || this._areaSensors[areaId]) return this._areaSensors[areaId];

    try {
      const [sensorsResult, switchesResult] = await Promise.all([
        this._hass.callWS({
          type: 'smart_dashboards/get_entities_by_area',
          area_id: areaId,
        }),
        this._hass.callWS({
          type: 'smart_dashboards/get_switches',
          area_id: areaId,
        }),
      ]);
      this._areaSensors[areaId] = sensorsResult.outlets || [];
      this._areaSwitches[areaId] = switchesResult.switches || [];
      return this._areaSensors[areaId];
    } catch (e) {
      console.error('Failed to load area sensors:', e);
      return [];
    }
  }

  async _loadPowerData() {
    if (!this._hass || this._showSettings) return;

    try {
      this._powerData = await this._hass.callWS({ type: 'smart_dashboards/get_power_data' });
      if (this._dashboardView === 'outlets') {
        this._updatePowerDisplay();
      }
    } catch (e) {
      console.error('Failed to load power data:', e);
    }
  }

  async _loadBreakerData() {
    if (!this._hass || this._showSettings) return;

    try {
      this._breakerData = await this._hass.callWS({ type: 'smart_dashboards/get_breaker_data' });
      if (this._dashboardView === 'breakers') {
        this._updateBreakerDisplay();
      }
    } catch (e) {
      console.error('Failed to load breaker data:', e);
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
    
    if (totalWattsEl) totalWattsEl.textContent = `${totalWatts.toFixed(1)} W`;
    if (totalDayEl) totalDayEl.textContent = `${(totalDayWh / 1000).toFixed(2)} kWh`;
    if (totalWarningsEl) totalWarningsEl.textContent = `${this._powerData.total_warnings || 0}`;
    if (totalShutoffsEl) totalShutoffsEl.textContent = `${this._powerData.total_shutoffs || 0}`;
    
    rooms.forEach(room => {
      const roomCard = this.shadowRoot.querySelector(`.room-card[data-room-id="${room.id}"]`);
      if (!roomCard) return;

      const roomConfig = this._getRoomConfig(room.id);
      const threshold = roomConfig?.threshold || 0;

      // Update room totals
      const totalWattsSpan = roomCard.querySelector('.room-total-watts');
      const totalDaySpan = roomCard.querySelector('.room-total-day');
      
      if (totalWattsSpan) {
        totalWattsSpan.textContent = `${room.total_watts.toFixed(1)} W`;
        totalWattsSpan.classList.toggle('over-threshold', threshold > 0 && room.total_watts > threshold);
      }
      if (totalDaySpan) {
        totalDaySpan.textContent = `${(room.total_day_wh / 1000).toFixed(2)} kWh today`;
      }

      // Update per-room event counts
      const eventCounts = roomCard.querySelectorAll('.event-count');
      if (eventCounts.length >= 2) {
        const warnings = room.warnings || 0;
        const shutoffs = room.shutoffs || 0;
        eventCounts[0].textContent = `⚠ ${warnings}`;
        eventCounts[1].textContent = `⚡ ${shutoffs}`;
      }

      // Update individual devices
      room.outlets.forEach((outlet, i) => {
        const deviceCard = roomCard.querySelector(`[data-outlet-index="${i}"]`);
        if (!deviceCard) return;

        const deviceConfig = roomConfig?.outlets?.[i];
        const deviceThreshold = deviceConfig?.threshold || 0;
        const deviceType = deviceConfig?.type || 'outlet';
        const isSingleOutlet = deviceType === 'single_outlet';
        const isAppliance = deviceType === 'stove' || deviceType === 'microwave';
        const outletTotal = isAppliance || isSingleOutlet
          ? outlet.plug1.watts
          : outlet.plug1.watts + outlet.plug2.watts;

        const plug1Watts = deviceCard.querySelector('.plug1-watts');
        const plug2Watts = deviceCard.querySelector('.plug2-watts');
        const outletTotalEl = deviceCard.querySelector('.outlet-total');
        const mwLcdWatts = deviceCard.querySelector('.mw-lcd-watts');

        if (plug1Watts) plug1Watts.textContent = `${outlet.plug1.watts.toFixed(1)}W`;
        if (plug2Watts) plug2Watts.textContent = `${outlet.plug2.watts.toFixed(1)}W`;
        if (mwLcdWatts) {
          mwLcdWatts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
          mwLcdWatts.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        if (outletTotalEl) {
          outletTotalEl.textContent = `${outletTotal.toFixed(1)} W`;
          outletTotalEl.classList.toggle('over-threshold', deviceThreshold > 0 && outletTotal > deviceThreshold);
        }
        if (isAppliance) {
          const mwBody = deviceCard.querySelector('.mw-body');
          if (mwBody) mwBody.classList.toggle('mw-on', outlet.plug1.watts > 0.1);
          if (deviceType === 'stove') {
            const active = outlet.plug1.watts > 0.1;
            const ovenDoor = deviceCard.querySelector('.stove-oven-door');
            const firstBurner = deviceCard.querySelector('.stove-burner');
            const firstKnob = deviceCard.querySelector('.stove-knob');
            if (ovenDoor) ovenDoor.classList.toggle('active', active);
            if (firstBurner) firstBurner.classList.toggle('active', active);
            if (firstKnob) firstKnob.classList.toggle('active', active);
          }
        }
      });
    });
  }

  _getRoomConfig(roomId) {
    const rooms = this._config?.rooms || [];
    return rooms.find(r => r.id === roomId);
  }

  _render() {
    const styles = `
      ${sharedStyles}
      ${passcodeModalStyles}
      
      .summary-stats {
        display: flex;
        gap: 10px;
        margin-bottom: 12px;
      }

      .stat-card {
        flex: 1;
        background: var(--card-bg);
        border-radius: 8px;
        border: 1px solid var(--card-border);
        padding: 10px 14px;
        text-align: center;
      }

      .stat-value {
        font-size: 18px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
      }

      .stat-label {
        font-size: 9px;
        color: var(--secondary-text-color);
        margin-top: 2px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .view-tabs {
        display: flex;
        gap: 8px;
        margin-bottom: 12px;
        border-bottom: 1px solid var(--card-border);
      }

      .view-tab {
        padding: 8px 16px;
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: var(--secondary-text-color);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
      }

      .view-tab:hover {
        color: var(--primary-text-color);
      }

      .view-tab.active {
        color: var(--panel-accent);
        border-bottom-color: var(--panel-accent);
      }

      .rooms-grid {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .room-card {
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        overflow: hidden;
        height: fit-content;
        width: 100%;
      }

      .room-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        background: linear-gradient(135deg, rgba(3, 169, 244, 0.06) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
      }

      .room-info {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .room-icon {
        width: 28px;
        height: 28px;
        border-radius: 6px;
        background: var(--panel-accent-dim);
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .room-icon svg {
        width: 16px;
        height: 16px;
        fill: var(--panel-accent);
      }

      .room-name {
        font-size: 13px;
        font-weight: 500;
        margin: 0 0 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .room-meta {
        font-size: 10px;
        color: var(--secondary-text-color);
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .room-meta svg {
        width: 10px;
        height: 10px;
        fill: currentColor;
        margin-right: 2px;
      }

      .event-count {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        font-size: 9px;
        color: var(--secondary-text-color);
        padding: 2px 4px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 3px;
        white-space: nowrap;
      }

      .breakers-grid {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .breaker-card {
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        overflow: hidden;
        width: 100%;
      }

      .breaker-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        background: linear-gradient(135deg, rgba(3, 169, 244, 0.06) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
      }

      .breaker-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .breaker-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--primary-text-color);
        margin: 0;
      }

      .breaker-meta {
        font-size: 10px;
        color: var(--secondary-text-color);
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .breaker-stats {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 2px;
      }

      .breaker-total-watts {
        font-size: 16px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
      }

      .breaker-total-watts.over-threshold {
        color: var(--panel-danger);
        animation: pulse-danger 1s infinite;
      }

      .breaker-total-day {
        font-size: 10px;
        color: var(--secondary-text-color);
        font-variant-numeric: tabular-nums;
      }

      .breaker-content {
        padding: 12px 16px;
      }

      .breaker-progress-info {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        font-size: 11px;
        color: var(--secondary-text-color);
      }

      .progress-label {
        font-variant-numeric: tabular-nums;
      }

      .progress-percentage {
        font-weight: 600;
        color: var(--primary-text-color);
        font-variant-numeric: tabular-nums;
      }

      .breaker-progress-bar {
        width: 100%;
        height: 20px;
        background: rgba(0, 0, 0, 0.3);
        border-radius: 10px;
        overflow: hidden;
        position: relative;
        border: 1px solid rgba(255, 255, 255, 0.1);
      }

      .breaker-progress-fill {
        height: 100%;
        background: var(--panel-accent);
        border-radius: 10px;
        transition: width 0.3s ease;
      }

      .breaker-threshold-indicator {
        position: absolute;
        top: 0;
        bottom: 0;
        width: 2px;
        background: var(--panel-warning);
        transform: translateX(-50%);
      }

      .threshold-label {
        position: absolute;
        top: -18px;
        left: 50%;
        transform: translateX(-50%);
        font-size: 9px;
        color: var(--panel-warning);
        white-space: nowrap;
      }

      .breaker-outlets-list {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid var(--card-border);
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .breaker-outlet-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 4px 6px;
        background: rgba(0, 0, 0, 0.2);
        border-radius: 4px;
        font-size: 10px;
      }

      .breaker-outlet-name {
        flex: 1;
        color: var(--primary-text-color);
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .breaker-outlet-percentage {
        color: var(--panel-accent);
        font-weight: 600;
        margin: 0 8px;
        min-width: 40px;
        text-align: right;
        font-variant-numeric: tabular-nums;
      }

      .breaker-outlet-watts {
        color: var(--secondary-text-color);
        font-variant-numeric: tabular-nums;
        min-width: 50px;
        text-align: right;
      }

      .room-stats {
        text-align: right;
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

      .room-total-watts {
        font-size: 16px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
      }

      .room-total-watts.over-threshold {
        color: var(--panel-danger);
        animation: pulse-danger 1s infinite;
      }

      @keyframes pulse-danger {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
      }

      .room-total-day {
        font-size: 9px;
        color: var(--secondary-text-color);
        margin-top: 2px;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
      }

      .room-content {
        padding: 10px 12px;
      }

      .outlets-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        justify-content: flex-start;
        align-items: flex-start;
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
      }

      .outlet-card.outlet-face.single-outlet .single-receptacle {
        flex: 0 0 auto;
        margin: auto 0;
      }

      .outlet-card.outlet-face.single-outlet .plate-screw:first-of-type {
        margin: 4px auto 16px;
      }

      .outlet-card.outlet-face.single-outlet .plate-screw:last-of-type {
        margin: 16px auto 4px;
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
      .device-card.microwave-card .outlet-name-top {
        font-size: 12px;
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

      .device-card.stove-card {
        width: 243px;
        min-width: 243px;
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-faceplate {
        background: linear-gradient(#f7f7f7, #e9e9e9);
        border: 1px solid rgba(0, 0, 0, 0.18);
        border-radius: 9px;
        padding: 6px 6px 5px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.8);
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
        background: linear-gradient(180deg, #e8e8e8, #d0d0d0);
        border: 2px solid rgba(0, 0, 0, 0.2);
        border-radius: 6px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), 0 1px 3px rgba(0,0,0,0.12);
        overflow: hidden;
      }

      .device-card.stove-card .stove-cooktop {
        height: 14px;
        background: linear-gradient(180deg, #2a2a2a, #1a1a1a);
        border-bottom: 1px solid rgba(0,0,0,0.3);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 2px 8px;
        gap: 4px;
      }

      .device-card.stove-card .stove-burner {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: linear-gradient(180deg, #606060, #404040);
        border: 1px solid rgba(0, 0, 0, 0.5);
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.4);
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-burner.active {
        background: radial-gradient(circle at 30% 30%, #ff6b6b, #c0392b);
        box-shadow: 0 0 4px rgba(255,82,82,0.6), inset 0 1px 0 rgba(255,255,255,0.2);
      }

      .device-card.stove-card .stove-control-panel {
        height: 18px;
        background: linear-gradient(180deg, #1e1e1e, #151515);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 3px 10px;
        gap: 6px;
        border-bottom: 1px solid rgba(0,0,0,0.2);
      }

      .device-card.stove-card .stove-knob {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: linear-gradient(135deg, #d4a84b, #b8860b);
        border: 1px solid rgba(0, 0, 0, 0.4);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.4), 0 1px 2px rgba(0,0,0,0.3);
        flex-shrink: 0;
      }

      .device-card.stove-card .stove-knob.active {
        box-shadow: 0 0 0 2px rgba(3, 169, 244, 0.7), inset 0 1px 0 rgba(255,255,255,0.4);
      }

      .device-card.stove-card .stove-oven-door {
        flex: 1;
        min-height: 36px;
        display: flex;
        flex-direction: column;
        align-items: center;
        background: linear-gradient(180deg, #f0f0f0, #e0e0e0);
        border-bottom: 1px solid rgba(0,0,0,0.1);
      }

      .device-card.stove-card .stove-oven-door.active {
        box-shadow: inset 0 0 0 2px rgba(3, 169, 244, 0.4);
      }

      .device-card.stove-card .stove-handle {
        width: 60%;
        height: 4px;
        margin: 4px 0 2px;
        background: linear-gradient(180deg, #c0c0c0, #909090);
        border-radius: 2px;
        border: 1px solid rgba(0,0,0,0.15);
        box-shadow: 0 1px 0 rgba(255,255,255,0.5);
      }

      .device-card.stove-card .stove-oven-window {
        flex: 1;
        width: 75%;
        min-height: 24px;
        margin: 0 0 4px;
        border-radius: 4px;
        background: linear-gradient(180deg, rgba(20,20,20,0.95), rgba(35,35,35,0.95));
        border: 1px solid rgba(0, 0, 0, 0.5);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
      }

      .device-card.stove-card .stove-base {
        height: 8px;
        background: linear-gradient(180deg, #1a1a1a, #0d0d0d);
        border-radius: 0 0 4px 4px;
      }

      .device-card.microwave-card {
        width: 243px;
        min-width: 243px;
        flex-shrink: 0;
      }

      .device-card.microwave-card .mw-faceplate {
        background: linear-gradient(#f5f5f5, #e0e0e0);
        border: 1px solid rgba(0, 0, 0, 0.18);
        border-radius: 9px;
        padding: 6px 6px 5px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.8);
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
        gap: 4px;
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

      .device-card.microwave-card .mw-handle {
        width: 6px;
        border-radius: 4px;
        background: linear-gradient(180deg, rgba(160,160,160,0.95), rgba(120,120,120,0.95));
        border: 1px solid rgba(0, 0, 0, 0.2);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.4);
      }

      @media (max-width: 500px) {
        .device-card.stove-card,
        .device-card.microwave-card {
          width: 216px;
          min-width: 216px;
        }
      }

      /* Settings Styles */
      .room-settings-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        margin-bottom: 16px;
        overflow: hidden;
      }

      .room-settings-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        background: linear-gradient(135deg, rgba(3, 169, 244, 0.05) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
      }

      .room-settings-header input {
        font-size: 13px;
        font-weight: 500;
        max-width: 160px;
        padding: 8px 10px;
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

      .test-trip-breaker-btn.on {
        background: var(--panel-accent-dim);
        border-color: var(--panel-accent);
        color: var(--panel-accent);
      }

      .breaker-settings-card {
        background: var(--card-bg);
        border-radius: 8px;
        border: 1px solid var(--card-border);
        padding: 12px;
        margin-bottom: 12px;
      }

      .breaker-settings-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--card-border);
      }

      .breaker-settings-name-color {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .breaker-color-input {
        width: 40px;
        height: 32px;
        border: 1px solid var(--card-border);
        border-radius: 6px;
        cursor: pointer;
        background: transparent;
      }

      .breaker-settings-body {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .breaker-outlets-section {
        margin-top: 8px;
      }

      .breaker-drop-label {
        font-size: 10px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .btn-small {
        padding: 6px 12px;
        font-size: 11px;
      }

      .breaker-assigned-outlets-list {
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
    `;

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
          ${rooms.length > 0 ? `
            <div class="summary-stats">
              <div class="stat-card">
                <div class="stat-value" id="summary-total-watts">${totalWatts.toFixed(1)} W</div>
                <div class="stat-label">Current Power</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="summary-total-day">${(totalDayWh / 1000).toFixed(2)} kWh</div>
                <div class="stat-label">Today's Usage</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="summary-warnings">${totalWarnings}</div>
                <div class="stat-label">Threshold Warnings</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="summary-shutoffs">${totalShutoffs}</div>
                <div class="stat-label">Safety Shutoffs</div>
              </div>
            </div>
          ` : ''}

          ${rooms.length === 0 && this._dashboardView === 'outlets' ? this._renderEmptyState() : ''}
          
          <div class="view-tabs">
            <button class="view-tab ${this._dashboardView === 'outlets' ? 'active' : ''}" data-view="outlets">
              Rooms
            </button>
            <button class="view-tab ${this._dashboardView === 'breakers' ? 'active' : ''}" data-view="breakers">
              Breakers
            </button>
          </div>

          ${this._dashboardView === 'outlets' ? `
            <div class="rooms-grid">
              ${rooms.map((room) => this._renderRoomCard(room)).join('')}
            </div>
          ` : this._renderBreakerPanel()}
        </div>
      </div>
    `;

    this._attachEventListeners();
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

  _renderRoomCard(room) {
    const roomData = this._powerData?.rooms?.find(r => r.id === room.id) || {
      total_watts: 0,
      total_day_wh: 0,
      warnings: 0,
      shutoffs: 0,
      outlets: [],
    };

    const isOverThreshold = room.threshold > 0 && roomData.total_watts > room.threshold;
    const warnings = roomData.warnings || 0;
    const shutoffs = roomData.shutoffs || 0;

    return `
      <div class="room-card" data-room-id="${room.id}">
        <div class="room-header">
          <div class="room-info">
            <div class="room-icon">
              <svg viewBox="0 0 24 24">${icons.room}</svg>
            </div>
            <div>
              <h3 class="room-name">${room.name}</h3>
              <div class="room-meta">
                <span>${room.outlets?.length || 0} devices</span>
                ${room.threshold > 0 ? `
                  <span class="threshold-badge">
                    <svg viewBox="0 0 24 24">${icons.warning}</svg>
                    ${room.threshold}W limit
                  </span>
                ` : ''}
                <span class="event-count" title="Threshold Warnings">⚠ ${warnings}</span>
                <span class="event-count" title="Safety Shutoffs">⚡ ${shutoffs}</span>
              </div>
            </div>
          </div>
          <div class="room-stats">
            <div class="room-total-watts ${isOverThreshold ? 'over-threshold' : ''}">${roomData.total_watts.toFixed(1)} W</div>
            <div class="room-total-day">${(roomData.total_day_wh / 1000).toFixed(2)} kWh today</div>
          </div>
        </div>

        <div class="room-content">
          <div class="outlets-grid">
            ${(room.outlets || []).map((device, oi) => this._renderDeviceCard(device, oi, roomData.outlets[oi])).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderDeviceCard(device, index, deviceData) {
    const type = device.type || 'outlet';
    if (type === 'stove') return this._renderStoveCard(device, index, deviceData);
    if (type === 'microwave') return this._renderMicrowaveCard(device, index, deviceData);
    return this._renderOutletCard(device, index, deviceData);
  }

  _renderStoveCard(device, index, deviceData) {
    const data = deviceData || { plug1: { watts: 0 } };
    const watts = data.plug1?.watts || 0;
    const isOverThreshold = device.threshold > 0 && watts > device.threshold;
    const isActive = watts > 0.1;

    return `
      <div class="device-card stove-card" data-outlet-index="${index}">
        <div class="stove-faceplate">
          <div class="outlet-name outlet-name-top" title="${(device.name || '').replace(/"/g, '&quot;')}">${device.name || ''}</div>
          <div class="stove-body">
            <div class="stove-cooktop">
              <div class="stove-burner ${isActive ? 'active' : ''}"></div>
              <div class="stove-burner"></div>
              <div class="stove-burner"></div>
              <div class="stove-burner"></div>
            </div>
            <div class="stove-control-panel">
              <div class="stove-knob ${isActive ? 'active' : ''}"></div>
              <div class="stove-knob"></div>
              <div class="stove-knob"></div>
              <div class="stove-knob"></div>
            </div>
            <div class="stove-oven-door ${isActive ? 'active' : ''}">
              <div class="stove-handle"></div>
              <div class="stove-oven-window"></div>
            </div>
            <div class="stove-base"></div>
          </div>
          <div class="outlet-meta">
            <div class="outlet-total ${isOverThreshold ? 'over-threshold' : ''}">${watts.toFixed(1)} W</div>
            <div class="outlet-threshold">
              <span class="threshold-badge">${device.threshold > 0 ? `${device.threshold}W` : '∞ W'}</span>
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
          <div class="receptacle ${plug1Active ? 'active' : ''}">
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

          <div class="receptacle ${plug2Active ? 'active' : ''}">
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

  _renderBreakerPanel() {
    const breakerLines = this._config?.breaker_lines || [];
    const breakerData = this._breakerData?.breaker_lines || [];

    if (breakerLines.length === 0) {
      return `
        <div class="empty-state">
          <svg class="empty-state-icon" viewBox="0 0 24 24">${icons.flash}</svg>
          <h3 class="empty-state-title">No Breaker Lines Configured</h3>
          <p class="empty-state-desc">Set up breaker lines in settings to monitor circuit loads.</p>
        </div>
      `;
    }

    return `
      <div class="breakers-grid">
        ${breakerLines.map(breaker => {
          const data = breakerData.find(b => b.id === breaker.id) || {
            total_watts: 0,
            total_day_wh: 0,
            max_load: breaker.max_load || 2400,
            outlets: [],
          };
          const percentage = data.max_load > 0 ? Math.min((data.total_watts / data.max_load) * 100, 100) : 0;
          const isNearThreshold = breaker.threshold > 0 && data.total_watts >= breaker.threshold;
          const isAtMax = data.max_load > 0 && data.total_watts >= data.max_load;
          const outlets = data.outlets || [];

          return `
            <div class="breaker-card" data-breaker-id="${breaker.id}" style="border-left: 4px solid ${breaker.color || '#03a9f4'}">
              <div class="breaker-header">
                <div class="breaker-info">
                  <h3 class="breaker-name">${breaker.name}</h3>
                  <div class="breaker-meta">
                    <span>${breaker.outlet_ids?.length || 0} outlets</span>
                  </div>
                </div>
                <div class="breaker-stats">
                  <div class="breaker-total-watts ${isAtMax ? 'over-threshold' : ''}">${data.total_watts.toFixed(1)} W</div>
                  <div class="breaker-total-day">${(data.total_day_wh / 1000).toFixed(2)} kWh today</div>
                </div>
              </div>
              <div class="breaker-content">
                <div class="breaker-progress-info">
                  <span class="progress-label">${data.total_watts.toFixed(1)}W / ${data.max_load}W</span>
                  <span class="progress-percentage">${percentage.toFixed(1)}%</span>
                </div>
                <div class="breaker-progress-bar">
                  <div class="breaker-progress-fill" style="width: ${percentage}%; background: ${breaker.color || '#03a9f4'}"></div>
                  ${breaker.threshold > 0 && data.max_load > 0 && (breaker.threshold / data.max_load) * 100 > 0 ? `
                    <div class="breaker-threshold-indicator" style="left: ${(breaker.threshold / data.max_load) * 100}%">
                      <span class="threshold-label">Warning: ${breaker.threshold}W</span>
                    </div>
                  ` : ''}
                </div>
                ${outlets.length > 0 ? `
                  <div class="breaker-outlets-list">
                    ${outlets.map(outlet => `
                      <div class="breaker-outlet-item">
                        <span class="breaker-outlet-name">${outlet.name}</span>
                        <span class="breaker-outlet-percentage">${outlet.percentage.toFixed(1)}%</span>
                        <span class="breaker-outlet-watts">${outlet.total_watts.toFixed(1)}W</span>
                      </div>
                    `).join('')}
                  </div>
                ` : ''}
              </div>
            </div>
          `;
        }).join('')}
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

  _updateBreakerDisplay() {
    if (!this._breakerData || this._showSettings || this._dashboardView !== 'breakers') return;

    const breakerLines = this._config?.breaker_lines || [];
    const breakerData = this._breakerData?.breaker_lines || [];

    breakerLines.forEach(breaker => {
      const data = breakerData.find(b => b.id === breaker.id);
      if (!data) return;

      const breakerCard = this.shadowRoot.querySelector(`.breaker-card[data-breaker-id="${breaker.id}"]`);
      if (!breakerCard) return;

      const totalWattsEl = breakerCard.querySelector('.breaker-total-watts');
      const totalDayEl = breakerCard.querySelector('.breaker-total-day');
      const progressLabel = breakerCard.querySelector('.progress-label');
      const progressFill = breakerCard.querySelector('.breaker-progress-fill');
      const progressPercentage = breakerCard.querySelector('.progress-percentage');

      if (totalWattsEl) {
        totalWattsEl.textContent = `${data.total_watts.toFixed(1)} W`;
        totalWattsEl.classList.toggle('over-threshold', data.max_load > 0 && data.total_watts >= data.max_load);
      }
      if (totalDayEl) totalDayEl.textContent = `${(data.total_day_wh / 1000).toFixed(2)} kWh today`;
      if (progressLabel) progressLabel.textContent = `${data.total_watts.toFixed(1)}W / ${data.max_load}W`;
      if (progressFill) {
        const percentage = data.max_load > 0 ? Math.min((data.total_watts / data.max_load) * 100, 100) : 0;
        progressFill.style.width = `${percentage}%`;
      }
      if (progressPercentage) {
        const percentage = data.max_load > 0 ? Math.min((data.total_watts / data.max_load) * 100, 100) : 0;
        progressPercentage.textContent = `${percentage.toFixed(1)}%`;
      }

      // Update outlet list
      const outletsList = breakerCard.querySelector('.breaker-outlets-list');
      if (outletsList && data.outlets) {
        const outletItems = outletsList.querySelectorAll('.breaker-outlet-item');
        data.outlets.forEach((outlet, index) => {
          const item = outletItems[index];
          if (item) {
            const nameEl = item.querySelector('.breaker-outlet-name');
            const percentageEl = item.querySelector('.breaker-outlet-percentage');
            const wattsEl = item.querySelector('.breaker-outlet-watts');
            
            if (nameEl) nameEl.textContent = outlet.name;
            if (percentageEl) percentageEl.textContent = `${outlet.percentage.toFixed(1)}%`;
            if (wattsEl) wattsEl.textContent = `${outlet.total_watts.toFixed(1)}W`;
          }
        });
      }
    });
  }

  _renderSettings(styles) {
    const rooms = this._config?.rooms || [];
    const mediaPlayers = this._entities?.media_players || [];
    const powerSensors = this._entities?.power_sensors || [];
    const ttsSettings = this._config?.tts_settings || {};

    this.shadowRoot.innerHTML = `
      <style>
        ${styles}
        
        .settings-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 16px;
          background: rgba(0, 0, 0, 0.2);
          padding: 4px;
          border-radius: 8px;
        }
        
        .settings-tab {
          flex: 1;
          padding: 10px 16px;
          border: none;
          background: transparent;
          color: var(--secondary-text-color);
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
            <button class="settings-tab ${this._settingsTab === 'breakers' ? 'active' : ''}" data-tab="breakers">
              Breaker Settings
            </button>
            <button class="settings-tab ${this._settingsTab === 'stove' ? 'active' : ''}" data-tab="stove">
              Stove Safety
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
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Message Prefix</div>
                <div class="tts-msg-desc">Added to the beginning of all alert messages</div>
                <input type="text" class="form-input" id="tts-prefix" 
                  value="${ttsSettings.prefix || 'Message from Home Energy.'}" 
                  placeholder="Message from Home Energy.">
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Room Warning Message</div>
                <div class="tts-msg-desc">Spoken when room total exceeds threshold</div>
                <input type="text" class="form-input" id="tts-room-warn" 
                  value="${ttsSettings.room_warn_msg || '{prefix} {room_name} is pulling {watts} watts'}" 
                  placeholder="{prefix} {room_name} is pulling {watts} watts">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{watts}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Outlet Warning Message</div>
                <div class="tts-msg-desc">Spoken when outlet total exceeds threshold</div>
                <input type="text" class="form-input" id="tts-outlet-warn" 
                  value="${ttsSettings.outlet_warn_msg || '{prefix} {room_name} {outlet_name} is pulling {watts} watts'}" 
                  placeholder="{prefix} {room_name} {outlet_name} is pulling {watts} watts">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{watts}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Shutoff Reset Message</div>
                <div class="tts-msg-desc">Spoken when a plug is shut off and reset due to overload</div>
                <input type="text" class="form-input" id="tts-shutoff" 
                  value="${ttsSettings.shutoff_msg || '{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload'}" 
                  placeholder="{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{outlet_name}</code> <code>{plug}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Breaker Warning Message</div>
                <div class="tts-msg-desc">Spoken when breaker line is near its max load</div>
                <input type="text" class="form-input" id="tts-breaker-warn" 
                  value="${ttsSettings.breaker_warn_msg || '{prefix} {breaker_name} is near its max load, reduce electric use to prevent safety shutoff'}" 
                  placeholder="{prefix} {breaker_name} is near its max load, reduce electric use to prevent safety shutoff">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{breaker_name}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Breaker Shutoff Message</div>
                <div class="tts-msg-desc">Spoken when breaker line hits its max limit and safety shutoff is enabled</div>
                <input type="text" class="form-input" id="tts-breaker-shutoff" 
                  value="${ttsSettings.breaker_shutoff_msg || '{prefix} {breaker_name} is currently at its max limit, safety shutoff enabled'}" 
                  placeholder="{prefix} {breaker_name} is currently at its max limit, safety shutoff enabled">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{breaker_name}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Turned On Message</div>
                <div class="tts-msg-desc">Spoken when stove is detected as turned on</div>
                <input type="text" class="form-input" id="tts-stove-on" 
                  value="${ttsSettings.stove_on_msg || '{prefix} Stove has been turned on'}" 
                  placeholder="{prefix} Stove has been turned on">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Turned Off Message</div>
                <div class="tts-msg-desc">Spoken when stove is detected as turned off</div>
                <input type="text" class="form-input" id="tts-stove-off" 
                  value="${ttsSettings.stove_off_msg || '{prefix} Stove has been turned off'}" 
                  placeholder="{prefix} Stove has been turned off">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Timer Started Message</div>
                <div class="tts-msg-desc">Spoken when stove is on and no one is in the kitchen (timer just started)</div>
                <input type="text" class="form-input" id="tts-stove-timer-started" 
                  value="${ttsSettings.stove_timer_started_msg || '{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.'}" 
                  placeholder="{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{cooking_time_minutes}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Cooking-Time Warning</div>
                <div class="tts-msg-desc">Spoken when stove has been on for the configured cooking time with no presence detected</div>
                <input type="text" class="form-input" id="tts-stove-15min" 
                  value="${ttsSettings.stove_15min_warn_msg || '{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns'}" 
                  placeholder="{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{cooking_time_minutes}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Final Warning</div>
                <div class="tts-msg-desc">Spoken when final countdown begins before auto-shutoff</div>
                <input type="text" class="form-input" id="tts-stove-30sec" 
                  value="${ttsSettings.stove_30sec_warn_msg || '{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen'}" 
                  placeholder="{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code> <code>{final_warning_seconds}</code>
                </div>
              </div>
              
              <div class="tts-msg-group">
                <div class="tts-msg-title">Stove Auto-Shutoff Message</div>
                <div class="tts-msg-desc">Spoken when stove is automatically turned off for safety</div>
                <input type="text" class="form-input" id="tts-stove-auto-off" 
                  value="${ttsSettings.stove_auto_off_msg || '{prefix} Stove has been automatically turned off for safety'}" 
                  placeholder="{prefix} Stove has been automatically turned off for safety">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Microwave Cut Power Message</div>
                <div class="tts-msg-desc">Spoken when stove power is cut because microwave is on (shared breaker)</div>
                <input type="text" class="form-input" id="tts-microwave-cut" 
                  value="${ttsSettings.microwave_cut_power_msg || '{prefix} Microwave is on. Stove power cut to protect circuit. Power will restore when microwave is off.'}" 
                  placeholder="{prefix} Microwave is on. Stove power cut to protect circuit. Power will restore when microwave is off.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Microwave Restore Power Message</div>
                <div class="tts-msg-desc">Spoken when stove power is restored after microwave turns off</div>
                <input type="text" class="form-input" id="tts-microwave-restore" 
                  value="${ttsSettings.microwave_restore_power_msg || '{prefix} Microwave is off. Stove power restored.'}" 
                  placeholder="{prefix} Microwave is off. Stove power restored.">
                <div class="tts-var-help">
                  Variables: <code>{prefix}</code>
                </div>
              </div>
            </div>
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'breakers' ? 'active' : ''}" id="tab-breakers">
            ${this._renderBreakerSettings()}
          </div>
          
          <div class="settings-tab-content ${this._settingsTab === 'stove' ? 'active' : ''}" id="tab-stove">
            ${this._renderStoveSafetySettings()}
          </div>
        </div>
      </div>
    `;

    this._attachSettingsEventListeners();
    initCustomSelects(this.shadowRoot);
    if (this._settingsTab === 'breakers') {
      this._attachBreakerEventListeners();
    }
  }

  _renderStoveSafetySettings() {
    const stoveConfig = this._config?.stove_safety || {};
    const powerSensors = this._entities?.power_sensors || [];
    const switches = this._entities?.switches || [];
    const binarySensors = this._entities?.binary_sensors || [];
    const mediaPlayers = this._entities?.media_players || [];

    // Get binary sensors (presence/motion sensors)
    if (!binarySensors || binarySensors.length === 0) {
      // Try to get from entities if not already loaded
      const allEntities = this._entities || {};
      binarySensors = Object.values(allEntities).filter(e => 
        e.entity_id && e.entity_id.startsWith('binary_sensor.')
      ) || [];
    }

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Stove Safety Configuration</h2>
        </div>
        <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 16px; padding: 0 12px;">
          Configure stove monitoring to automatically turn off the stove if left unattended.
        </p>
        
        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Stove Plug Power Sensor</label>
          ${renderCustomSelect('stove-plug-entity', [{value: '', label: 'None'}, ...powerSensors.map(s => ({value: s.entity_id, label: s.friendly_name}))], stoveConfig.stove_plug_entity)}
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Stove Plug Switch</label>
          ${renderCustomSelect('stove-plug-switch', [{value: '', label: 'None'}, ...switches.map(s => ({value: s.entity_id, label: s.friendly_name}))], stoveConfig.stove_plug_switch)}
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Power Threshold (W)</label>
          <input type="number" class="form-input" id="stove-power-threshold" 
            value="${stoveConfig.stove_power_threshold || 100}" 
            placeholder="100" min="0" step="10">
          <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
            Stove is considered "on" when power exceeds this threshold
          </div>
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Cooking Time (minutes)</label>
          <input type="number" class="form-input" id="stove-cooking-time" 
            value="${stoveConfig.cooking_time_minutes ?? 15}" 
            placeholder="15" min="1" max="120" step="1">
          <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
            Time with no presence before warning and final countdown
          </div>
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Final Warning (seconds)</label>
          <input type="number" class="form-input" id="stove-final-warning" 
            value="${stoveConfig.final_warning_seconds ?? 30}" 
            placeholder="30" min="5" max="300" step="1">
          <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
            Countdown after warning before auto-shutoff
          </div>
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Kitchen Presence Sensor</label>
          ${renderCustomSelect('stove-presence-sensor', [{value: '', label: 'None'}, ...binarySensors.map(s => ({value: s.entity_id, label: s.friendly_name || s.entity_id}))], stoveConfig.presence_sensor)}
          <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
            Presence = detected or on. No presence = clear, cleared, unavailable, unknown, or off.
          </div>
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">Media Player for Alerts</label>
          ${renderCustomSelect('stove-media-player', [{value: '', label: 'None'}, ...mediaPlayers.map(mp => ({value: mp.entity_id, label: mp.friendly_name}))], stoveConfig.media_player)}
        </div>

        <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
          <label class="form-label">TTS Volume</label>
          <div style="display: flex; align-items: center; gap: 12px;">
            <input type="range" class="form-range" id="stove-volume" 
              min="0" max="1" step="0.1" 
              value="${stoveConfig.volume || 0.7}">
            <span class="stove-volume-display" style="min-width: 40px; text-align: right;">
              ${Math.round((stoveConfig.volume || 0.7) * 100)}%
            </span>
          </div>
        </div>

        <div class="card" style="margin-top: 24px; border: 1px solid var(--panel-warning, #ff9800);">
          <div class="card-header">
            <h2 class="card-title" style="color: var(--panel-warning);">Microwave Safety (shared breaker)</h2>
          </div>
          <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px; padding: 0 12px;">
            For older homes where microwave and electric stove share the same breaker. When microwave is on, stove power is cut until microwave turns off, then restored. <strong style="color: var(--panel-warning);">Using this feature can damage the stove's LED panel—use at your discretion.</strong>
          </p>
          <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
            <label class="form-label">Microwave Plug Power Sensor</label>
            ${renderCustomSelect('stove-microwave-plug-entity', [{value: '', label: 'None (disabled)'}, ...powerSensors.map(s => ({value: s.entity_id, label: s.friendly_name}))], stoveConfig.microwave_plug_entity, 'None (disabled)')}
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
              Power sensor for the microwave outlet
            </div>
          </div>
          <div class="form-group" style="padding: 0 12px; margin-bottom: 16px;">
            <label class="form-label">Microwave On Threshold (W)</label>
            <input type="number" class="form-input" id="stove-microwave-threshold" 
              value="${stoveConfig.microwave_power_threshold ?? 50}" 
              placeholder="50" min="0" step="10">
            <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">
              Microwave is considered "on" when power exceeds this threshold
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderBreakerSettings() {
    const breakerLines = this._config?.breaker_lines || [];

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Breaker Lines</h2>
          <button class="btn btn-secondary" id="add-breaker-btn">
            <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
            Add Breaker
          </button>
        </div>
        <div id="breakers-list">
          ${breakerLines.length === 0 ? `
            <p style="color: var(--secondary-text-color); text-align: center; padding: 20px;">
              No breaker lines configured. Add a breaker line to start monitoring circuit loads.
            </p>
          ` : breakerLines.map((breaker, i) => this._renderBreakerSettingsCard(breaker, i)).join('')}
        </div>
      </div>
    `;
  }

  _getAllOutlets() {
    const rooms = this._config?.rooms || [];
    const outlets = [];
    rooms.forEach(room => {
      const roomId = room.id || room.name.toLowerCase().replace(' ', '_');
      room.outlets?.forEach(outlet => {
        const outletId = `${roomId}_${outlet.name.toLowerCase().replace(' ', '_')}`;
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

  _getAvailableOutletsForBreaker(breakerId) {
    const allOutlets = this._getAllOutlets();
    const breakerLines = this._config?.breaker_lines || [];
    
    // Get all outlet IDs already assigned to any breaker
    const assignedOutletIds = new Set();
    breakerLines.forEach(breaker => {
      if (breaker.outlet_ids) {
        breaker.outlet_ids.forEach(id => assignedOutletIds.add(id));
      }
    });
    
    // Filter out already assigned outlets
    return allOutlets.filter(outlet => !assignedOutletIds.has(outlet.id));
  }

  _renderBreakerSettingsCard(breaker, index) {
    const allOutlets = this._getAllOutlets();
    const assignedOutlets = allOutlets.filter(o => breaker.outlet_ids?.includes(o.id));

    return `
      <div class="breaker-settings-card" data-breaker-index="${index}">
        <div class="breaker-settings-header">
          <div class="breaker-settings-name-color">
            <input type="text" class="form-input breaker-name-input" value="${breaker.name}" placeholder="Breaker name" style="max-width: 200px;">
            <input type="color" class="breaker-color-input" value="${breaker.color || '#03a9f4'}" title="Breaker color">
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary test-trip-breaker-btn" data-breaker-id="${breaker.id}">
              Test Trip
            </button>
            <button class="icon-btn danger remove-breaker-btn" data-index="${index}">
              <svg viewBox="0 0 24 24">${icons.delete}</svg>
            </button>
          </div>
        </div>
        <div class="breaker-settings-body">
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">Max Load (W)</label>
              <input type="number" class="form-input breaker-max-load" value="${breaker.max_load || 2400}" min="0" step="100">
            </div>
            <div class="form-group">
              <label class="form-label">Warning Threshold (W)</label>
              <input type="number" class="form-input breaker-threshold" value="${breaker.threshold || 0}" min="0" step="100">
            </div>
          </div>
          <div class="breaker-outlets-section">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div class="breaker-drop-label">Assigned Outlets</div>
              <button class="btn btn-secondary btn-small add-outlet-to-breaker-btn" data-breaker-id="${breaker.id}">
                <svg class="btn-icon" viewBox="0 0 24 24" style="width: 14px; height: 14px;">${icons.add}</svg>
                Add Outlet
              </button>
            </div>
            <div class="breaker-assigned-outlets-list">
              ${assignedOutlets.length === 0 ? `
                <p style="color: var(--secondary-text-color); text-align: center; padding: 12px; font-size: 11px;">
                  No outlets assigned. Click "Add Outlet" to assign outlets to this breaker line.
                </p>
              ` : assignedOutlets.map(outlet => `
                <div class="outlet-assigned-card" data-outlet-id="${outlet.id}">
                  <div class="outlet-assigned-info">
                    <span class="outlet-assigned-room">${outlet.room_name}</span>
                    <span class="outlet-assigned-name">${outlet.outlet_name}</span>
                  </div>
                  <svg class="outlet-remove-icon" viewBox="0 0 24 24">${icons.close}</svg>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderRoomSettings(room, index, mediaPlayers, powerSensors) {
    const areas = this._areas || [];
    const filteredSensors = room.area_id ? 
      (this._areaSensors?.[room.area_id] || powerSensors) : powerSensors;

    return `
      <div class="room-settings-card" data-room-index="${index}" data-area-id="${room.area_id || ''}">
        <div class="room-settings-header">
          <input type="text" class="form-input room-name-input" value="${room.name}" placeholder="Room name" style="max-width: 180px;">
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary toggle-room-btn" data-index="${index}">Edit</button>
            <button class="icon-btn danger remove-room-btn" data-index="${index}">
              <svg viewBox="0 0 24 24">${icons.delete}</svg>
            </button>
          </div>
        </div>

        <div class="room-settings-body" id="room-body-${index}" style="display: none;">
          <div class="form-group" style="margin-bottom: 12px; padding: 10px; background: var(--panel-accent-dim); border-radius: 8px;">
            <label class="form-label" style="color: var(--panel-accent);">HA Area (filters outlet list)</label>
            <select class="form-select room-area-select" data-room-index="${index}">
              <option value="">All areas (no filter)</option>
              ${areas.map(area => `
                <option value="${area.id}" ${room.area_id === area.id ? 'selected' : ''}>
                  ${area.name}
                </option>
              `).join('')}
            </select>
          </div>

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
          </div>

          <div class="form-group" style="margin-bottom: 12px;">
            <label class="form-label">TTS Volume</label>
            <div class="volume-control">
              <input type="range" class="volume-slider room-volume" min="0" max="1" step="0.05" value="${room.volume || 0.7}">
              <span class="volume-value room-volume-display">${Math.round((room.volume || 0.7) * 100)}%</span>
            </div>
          </div>

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
              </div>
            </div>
          </div>

          <div class="outlets-settings-list" id="outlets-list-${index}">
            ${(room.outlets || []).map((outlet, oi) => this._renderDeviceSettings(outlet, oi, filteredSensors, index)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderDeviceSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed = true) {
    const type = device.type || 'outlet';
    if (type === 'stove' || type === 'microwave') {
      return this._renderApplianceSettings(device, deviceIndex, powerSensors, roomIndex, type, isCollapsed);
    }
    return this._renderOutletSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed);
  }

  _renderApplianceSettings(device, deviceIndex, powerSensors, roomIndex, deviceType, isCollapsed = true) {
    const displayName = device.name || (deviceType === 'stove' ? 'Unnamed Stove' : 'Unnamed Microwave');
    const collapsedClass = isCollapsed ? 'collapsed' : '';

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
              <input type="number" class="form-input outlet-threshold" value="${device.threshold || ''}" placeholder="W" min="0" style="width: 70px;">
            </div>
          </div>
          <div class="plugs-settings-grid single-plug">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Power Sensor</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                <select class="form-select outlet-plug1">
                  <option value="">None</option>
                  ${powerSensors.map(s => `
                    <option value="${s.entity_id}" ${device.plug1_entity === s.entity_id ? 'selected' : ''}>
                      ${s.friendly_name}
                    </option>
                  `).join('')}
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletSettings(outlet, outletIndex, powerSensors, roomIndex, isCollapsed = true) {
    const isSingleOutlet = (outlet.type || 'outlet') === 'single_outlet';
    const switches = this._getFilteredSwitches(roomIndex);
    
    // Sort switches by similarity to each plug sensor
    const plug1Switches = this._sortSwitchesBySimilarity(switches, outlet.plug1_entity);
    const plug2Switches = isSingleOutlet ? [] : this._sortSwitchesBySimilarity(switches, outlet.plug2_entity);
    
    // Helper to render switch options with best match indicator
    const renderSwitchOptions = (sortedSwitches, sensorEntity, currentSwitch) => {
      let options = '<option value="">None</option>';
      options += sortedSwitches.map((s, idx) => {
        const score = this._getSimilarityScore(s.entity_id, sensorEntity);
        const isBestMatch = idx === 0 && score > 0.3 && sensorEntity;
        const label = isBestMatch ? `★ ${s.friendly_name}` : s.friendly_name;
        return `<option value="${s.entity_id}" ${s.entity_id === currentSwitch ? 'selected' : ''}>${label}</option>`;
      }).join('');
      return options;
    };

    const displayName = outlet.name || 'Unnamed Outlet';
    const collapsedClass = isCollapsed ? 'collapsed' : '';

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
                <select class="form-select outlet-plug1">
                  <option value="">None</option>
                  ${powerSensors.map(s => `
                    <option value="${s.entity_id}" ${outlet.plug1_entity === s.entity_id ? 'selected' : ''}>
                      ${s.friendly_name}
                    </option>
                  `).join('')}
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Switch <span style="font-size: 8px; color: var(--panel-accent);">★ = best match</span></label>
                <select class="form-select outlet-plug1-switch">
                  ${renderSwitchOptions(plug1Switches, outlet.plug1_entity, outlet.plug1_switch)}
                </select>
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
            </div>
            ${isSingleOutlet ? '' : `
            <div class="plug-settings-card" data-plug="2">
              <div class="plug-settings-title">Plug 2</div>
              <div class="form-group">
                <label class="form-label">Power Sensor</label>
                <select class="form-select outlet-plug2">
                  <option value="">None</option>
                  ${powerSensors.map(s => `
                    <option value="${s.entity_id}" ${outlet.plug2_entity === s.entity_id ? 'selected' : ''}>
                      ${s.friendly_name}
                    </option>
                  `).join('')}
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Switch <span style="font-size: 8px; color: var(--panel-accent);">★ = best match</span></label>
                <select class="form-select outlet-plug2-switch">
                  ${renderSwitchOptions(plug2Switches, outlet.plug2_entity, outlet.plug2_switch)}
                </select>
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

    const settingsBtn = this.shadowRoot.querySelector('#settings-btn');
    const emptySettingsBtn = this.shadowRoot.querySelector('#empty-settings-btn');

    if (settingsBtn) {
      settingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._showSettings = true;
          this._stopRefresh();
          this._render();
        }
      });
    }

    if (emptySettingsBtn) {
      emptySettingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._showSettings = true;
          this._stopRefresh();
          this._render();
        }
      });
    }

    // View tab switching
    const viewTabs = this.shadowRoot.querySelectorAll('.view-tab');
    viewTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const view = tab.dataset.view;
        if (view && (view === 'outlets' || view === 'breakers')) {
          this._dashboardView = view;
          this._render();
        }
      });
    });
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
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', () => this._saveSettings());
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
        
        // Attach breaker listeners if switching to breaker tab
        if (tabId === 'breakers') {
          setTimeout(() => this._attachBreakerEventListeners(), 100);
        }
      });
    });

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
    this.shadowRoot.querySelectorAll('.room-area-select').forEach(select => {
      select.addEventListener('change', async (e) => {
        const roomIndex = e.target.dataset.roomIndex;
        const areaId = e.target.value;
        await this._updateRoomOutletDropdowns(roomIndex, areaId);
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

    // Test switch buttons
    this.shadowRoot.querySelectorAll('.test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });

    // Stove safety volume slider
    const stoveVolumeSlider = this.shadowRoot.querySelector('#stove-volume');
    if (stoveVolumeSlider) {
      stoveVolumeSlider.addEventListener('input', (e) => {
        const display = e.target.closest('.form-group').querySelector('.stove-volume-display');
        if (display) {
          display.textContent = Math.round(parseFloat(e.target.value) * 100) + '%';
        }
      });
    }
  }

  async _testToggleSwitch(btn) {
    // Get switch entity from data attribute or from the adjacent select
    let switchEntity = btn.dataset.switch;
    
    // If no switch in data attribute, try to get from the select in the same plug card
    if (!switchEntity) {
      const plugCard = btn.closest('.plug-settings-card');
      const plugNum = plugCard?.dataset?.plug;
      const switchSelect = plugCard?.querySelector(`.outlet-plug${plugNum}-switch`);
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

  async _updateRoomOutletDropdowns(roomIndex, areaId) {
    const roomCard = this.shadowRoot.querySelector(`.room-settings-card[data-room-index="${roomIndex}"]`);
    if (!roomCard) return;

    // Update stored area_id
    roomCard.dataset.areaId = areaId;

    // Get sensors and switches for this area
    let sensors = this._entities?.power_sensors || [];
    let switches = this._entities?.switches || [];
    if (areaId) {
      await this._loadAreaSensors(areaId);
      sensors = this._areaSensors[areaId] || [];
      switches = this._areaSwitches[areaId] || [];
    }

    // Update all outlet dropdowns in this room - PRESERVE existing selections
    const outletItems = roomCard.querySelectorAll('.outlet-settings-item');
    outletItems.forEach(item => {
      const plug1Select = item.querySelector('.outlet-plug1');
      const plug2Select = item.querySelector('.outlet-plug2');
      const plug1SwitchSelect = item.querySelector('.outlet-plug1-switch');
      const plug2SwitchSelect = item.querySelector('.outlet-plug2-switch');
      
      // Save current values BEFORE rebuilding options
      const plug1Value = plug1Select?.value || '';
      const plug2Value = plug2Select?.value || '';
      const plug1SwitchValue = plug1SwitchSelect?.value || '';
      const plug2SwitchValue = plug2SwitchSelect?.value || '';

      // Helper to build options while preserving current selection
      const buildOptions = (entities, currentValue, type = 'sensor') => {
        let options = '<option value="">None</option>';
        
        // If there's a current value that's NOT in the filtered list, add it first (marked)
        const currentInList = entities.some(e => e.entity_id === currentValue);
        if (currentValue && !currentInList) {
          const label = currentValue.split('.').pop().replace(/_/g, ' ');
          options += `<option value="${currentValue}" selected style="color: var(--warning-color);">${label} (other area)</option>`;
        }
        
        // Add all entities from the filtered list
        options += entities.map(e => 
          `<option value="${e.entity_id}" ${e.entity_id === currentValue ? 'selected' : ''}>${e.friendly_name}</option>`
        ).join('');
        
        return options;
      };

      if (plug1Select) {
        plug1Select.innerHTML = buildOptions(sensors, plug1Value, 'sensor');
      }
      if (plug2Select) {
        plug2Select.innerHTML = buildOptions(sensors, plug2Value, 'sensor');
      }
      if (plug1SwitchSelect) {
        plug1SwitchSelect.innerHTML = buildOptions(switches, plug1SwitchValue, 'switch');
      }
      if (plug2SwitchSelect) {
        plug2SwitchSelect.innerHTML = buildOptions(switches, plug2SwitchValue, 'switch');
      }
    });

    const areaName = this._areas?.find(a => a.id === areaId)?.name || 'all areas';
    showToast(this.shadowRoot, `Filtering to ${areaName} (existing selections preserved)`, 'success');
  }

  _getFilteredSensors(roomIndex) {
    const roomCard = this.shadowRoot.querySelector(`.room-settings-card[data-room-index="${roomIndex}"]`);
    const areaId = roomCard?.dataset?.areaId;
    
    if (areaId && this._areaSensors[areaId]) {
      return this._areaSensors[areaId];
    }
    return this._entities?.power_sensors || [];
  }

  _getFilteredSwitches(roomIndex) {
    const roomCard = this.shadowRoot.querySelector(`.room-settings-card[data-room-index="${roomIndex}"]`);
    const areaId = roomCard?.dataset?.areaId;
    
    if (areaId && this._areaSwitches && this._areaSwitches[areaId]) {
      return this._areaSwitches[areaId];
    }
    return this._entities?.switches || [];
  }

  /**
   * Calculate similarity score between two entity names (0-1, higher = more similar)
   */
  _getSimilarityScore(str1, str2) {
    if (!str1 || !str2) return 0;
    
    // Extract the entity name part (after the domain prefix)
    const name1 = str1.includes('.') ? str1.split('.').pop() : str1;
    const name2 = str2.includes('.') ? str2.split('.').pop() : str2;
    
    // Convert to lowercase and split into words
    const words1 = name1.toLowerCase().replace(/_/g, ' ').split(/\s+/);
    const words2 = name2.toLowerCase().replace(/_/g, ' ').split(/\s+/);
    
    // Count matching words
    let matches = 0;
    for (const word of words1) {
      if (word.length > 1 && words2.includes(word)) {
        matches++;
      }
    }
    
    // Also check for substring containment
    const n1 = name1.toLowerCase();
    const n2 = name2.toLowerCase();
    if (n1.includes(n2) || n2.includes(n1)) {
      matches += 2;
    }
    
    // Normalize by total unique words
    const totalWords = new Set([...words1, ...words2]).size;
    return totalWords > 0 ? matches / totalWords : 0;
  }

  /**
   * Sort switches by similarity to a sensor entity_id
   */
  _sortSwitchesBySimilarity(switches, sensorEntityId) {
    if (!sensorEntityId || !switches.length) return switches;
    
    return [...switches].sort((a, b) => {
      const scoreA = this._getSimilarityScore(a.entity_id, sensorEntityId);
      const scoreB = this._getSimilarityScore(b.entity_id, sensorEntityId);
      return scoreB - scoreA; // Higher score first
    });
  }

  /**
   * Update switch dropdown options sorted by similarity to the selected plug sensor
   */
  _updateSwitchDropdownOrder(plugSelect, switchSelect, switches) {
    if (!switchSelect) return;
    
    const sensorValue = plugSelect?.value || '';
    const currentSwitchValue = switchSelect.value || '';
    
    // Sort switches by similarity to the selected sensor
    const sortedSwitches = this._sortSwitchesBySimilarity(switches, sensorValue);
    
    // Helper to build options
    const buildOptions = (entities, currentValue) => {
      let options = '<option value="">None</option>';
      
      // If current value not in list, add it first
      const currentInList = entities.some(e => e.entity_id === currentValue);
      if (currentValue && !currentInList) {
        const label = currentValue.split('.').pop().replace(/_/g, ' ');
        options += `<option value="${currentValue}" selected>${label} (other area)</option>`;
      }
      
      // Add all switches, mark best match
      options += entities.map((e, idx) => {
        const score = this._getSimilarityScore(e.entity_id, sensorValue);
        const isBestMatch = idx === 0 && score > 0.3 && sensorValue;
        const label = isBestMatch ? `★ ${e.friendly_name}` : e.friendly_name;
        return `<option value="${e.entity_id}" ${e.entity_id === currentValue ? 'selected' : ''}>${label}</option>`;
      }).join('');
      
      return options;
    };
    
    switchSelect.innerHTML = buildOptions(sortedSwitches, currentSwitchValue);
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
      volume: 0.7,
      outlets: [],
    };
    
    const html = this._renderRoomSettings(newRoom, index, mediaPlayers, powerSensors);
    list.insertAdjacentHTML('beforeend', html);

    // Attach event listeners for the new room
    const newCard = list.querySelector(`.room-settings-card[data-room-index="${index}"]`);
    
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

    const areaSelect = newCard.querySelector('.room-area-select');
    if (areaSelect) {
      areaSelect.addEventListener('change', async (e) => {
        await this._updateRoomOutletDropdowns(index, e.target.value);
      });
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
    
    // Generate new device based on type
    const isAppliance = deviceType === 'stove' || deviceType === 'microwave';
    const newOutlet = {
      name: '',
      type: deviceType,
      plug1_entity: '',
      plug2_entity: deviceType === 'outlet' ? '' : null,
      plug1_switch: isAppliance ? null : '',
      plug2_switch: deviceType === 'outlet' ? '' : null,
      threshold: 0,
      plug1_shutoff: isAppliance ? 0 : 0,
      plug2_shutoff: deviceType === 'outlet' ? 0 : null,
    };
    
    // Render as expanded (not collapsed)
    const html = this._renderDeviceSettings(newOutlet, 0, sensors, roomIndex, false);
    
    // Insert at TOP of list
    list.insertAdjacentHTML('afterbegin', html);
    
    // Re-index all outlets
    list.querySelectorAll('.outlet-settings-item').forEach((item, idx) => {
      item.dataset.outletIndex = idx;
    });

    const newItem = list.querySelector('.outlet-settings-item:first-child');
    
    // Attach event listeners to new item
    this._attachOutletEventListeners(newItem, roomIndex);
    
    // Focus on name input
    const nameInput = newItem.querySelector('.outlet-name');
    if (nameInput) {
      setTimeout(() => nameInput.focus(), 100);
    }
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

    // Smart switch sorting
    outletItem.querySelectorAll('.outlet-plug1, .outlet-plug2').forEach(plugSelect => {
      plugSelect.addEventListener('change', (e) => {
        const isPlug1 = e.target.classList.contains('outlet-plug1');
        const switchSelect = isPlug1 
          ? outletItem.querySelector('.outlet-plug1-switch')
          : outletItem.querySelector('.outlet-plug2-switch');
        
        const switches = this._getFilteredSwitches(roomIndex);
        this._updateSwitchDropdownOrder(e.target, switchSelect, switches);
      });
    });

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
    outletItem.querySelectorAll('.test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });
  }

  _attachBreakerEventListeners() {
    // Add breaker button
    const addBreakerBtn = this.shadowRoot.querySelector('#add-breaker-btn');
    if (addBreakerBtn) {
      addBreakerBtn.addEventListener('click', () => this._addBreaker());
    }

    // Remove breaker buttons
    this.shadowRoot.querySelectorAll('.remove-breaker-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const card = btn.closest('.breaker-settings-card');
        if (card) card.remove();
      });
    });

    // Test trip breaker buttons
    this.shadowRoot.querySelectorAll('.test-trip-breaker-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const breakerId = btn.dataset.breakerId;
        if (breakerId) {
          await this._testTripBreaker(breakerId, btn);
        }
      });
    });

    // Add outlet to breaker buttons
    this.shadowRoot.querySelectorAll('.add-outlet-to-breaker-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const breakerId = btn.dataset.breakerId;
        if (breakerId) {
          this._showOutletSelector(breakerId);
        }
      });
    });

    // Remove outlet from breaker (click X icon)
    this.shadowRoot.querySelectorAll('.outlet-assigned-card').forEach(card => {
      const removeIcon = card.querySelector('.outlet-remove-icon');
      if (removeIcon) {
        removeIcon.addEventListener('click', () => {
          const breakerCard = card.closest('.breaker-settings-card');
          if (breakerCard) {
            card.remove();
          }
        });
      }
    });
  }

  _showOutletSelector(breakerId) {
    const availableOutlets = this._getAvailableOutletsForBreaker(breakerId);
    
    if (availableOutlets.length === 0) {
      showToast(this.shadowRoot, 'No available outlets to add', 'info');
      return;
    }

    // Create dropdown/modal
    const modal = document.createElement('div');
    modal.className = 'outlet-selector-modal';
    modal.innerHTML = `
      <div class="outlet-selector-overlay"></div>
      <div class="outlet-selector-content">
        <div class="outlet-selector-header">
          <h3>Select Outlet to Add</h3>
          <button class="outlet-selector-close">×</button>
        </div>
        <div class="outlet-selector-list">
          ${availableOutlets.map(outlet => `
            <div class="outlet-selector-item" data-outlet-id="${outlet.id}">
              <div class="outlet-selector-info">
                <span class="outlet-selector-room">${outlet.room_name}</span>
                <span class="outlet-selector-name">${outlet.outlet_name}</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    // Add styles
    const style = document.createElement('style');
    style.textContent = `
      .outlet-selector-modal {
        position: fixed;
        inset: 0;
        z-index: 2000;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .outlet-selector-overlay {
        position: absolute;
        inset: 0;
        background: rgba(0, 0, 0, 0.7);
        backdrop-filter: blur(4px);
      }
      .outlet-selector-content {
        position: relative;
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        width: 90%;
        max-width: 400px;
        max-height: 80vh;
        display: flex;
        flex-direction: column;
        box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
      }
      .outlet-selector-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        border-bottom: 1px solid var(--card-border);
      }
      .outlet-selector-header h3 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .outlet-selector-close {
        background: transparent;
        border: none;
        color: var(--secondary-text-color);
        font-size: 24px;
        cursor: pointer;
        padding: 0;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 4px;
        transition: background 0.2s;
      }
      .outlet-selector-close:hover {
        background: rgba(255, 255, 255, 0.1);
      }
      .outlet-selector-list {
        padding: 8px;
        overflow-y: auto;
        max-height: calc(80vh - 70px);
      }
      .outlet-selector-item {
        padding: 10px 12px;
        border-radius: 6px;
        cursor: pointer;
        transition: background 0.2s;
        margin-bottom: 4px;
      }
      .outlet-selector-item:hover {
        background: rgba(255, 255, 255, 0.05);
      }
      .outlet-selector-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .outlet-selector-room {
        font-size: 10px;
        color: var(--secondary-text-color);
      }
      .outlet-selector-name {
        font-size: 13px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
    `;
    modal.appendChild(style);

    // Add event listeners
    modal.querySelector('.outlet-selector-overlay').addEventListener('click', () => modal.remove());
    modal.querySelector('.outlet-selector-close').addEventListener('click', () => modal.remove());
    
    modal.querySelectorAll('.outlet-selector-item').forEach(item => {
      item.addEventListener('click', () => {
        const outletId = item.dataset.outletId;
        this._assignOutletToBreaker(breakerId, outletId);
        modal.remove();
      });
    });

    document.body.appendChild(modal);
  }

  _addBreaker() {
    const list = this.shadowRoot.querySelector('#breakers-list');
    const noItems = list.querySelector('p');
    if (noItems) noItems.remove();

    const index = list.querySelectorAll('.breaker-settings-card').length;
    const newBreaker = {
      id: `breaker_${Date.now()}`,
      name: `Breaker ${index + 1}`,
      color: '#03a9f4',
      max_load: 2400,
      threshold: 0,
      outlet_ids: [],
    };

    const html = this._renderBreakerSettingsCard(newBreaker, index);
    list.insertAdjacentHTML('beforeend', html);
    this._attachBreakerEventListeners();
  }

  _assignOutletToBreaker(breakerId, outletId) {
    // Find breaker card by finding the breaker in config and using its index
    const breakerLines = this._config?.breaker_lines || [];
    const breaker = breakerLines.find(b => b.id === breakerId);
    if (!breaker) return;
    
    const index = breakerLines.indexOf(breaker);
    const breakerCard = this.shadowRoot.querySelector(`.breaker-settings-card[data-breaker-index="${index}"]`);
    if (!breakerCard) return;

    const outletsList = breakerCard.querySelector('.breaker-assigned-outlets-list');
    if (!outletsList) return;

    // Check if already assigned
    if (outletsList.querySelector(`[data-outlet-id="${outletId}"]`)) {
      showToast(this.shadowRoot, 'Outlet already assigned to this breaker', 'info');
      return;
    }

    // Remove empty message if present
    const emptyMsg = outletsList.querySelector('p');
    if (emptyMsg) emptyMsg.remove();

    const allOutlets = this._getAllOutlets();
    const outlet = allOutlets.find(o => o.id === outletId);
    if (!outlet) return;

    const html = `
      <div class="outlet-assigned-card" data-outlet-id="${outletId}">
        <div class="outlet-assigned-info">
          <span class="outlet-assigned-room">${outlet.room_name}</span>
          <span class="outlet-assigned-name">${outlet.outlet_name}</span>
        </div>
        <svg class="outlet-remove-icon" viewBox="0 0 24 24">${icons.close}</svg>
      </div>
    `;
    outletsList.insertAdjacentHTML('beforeend', html);
    this._attachBreakerEventListeners();
  }

  async _testTripBreaker(breakerId, btn) {
    if (!btn) {
      btn = this.shadowRoot.querySelector(`.test-trip-breaker-btn[data-breaker-id="${breakerId}"]`);
    }
    
    if (btn) {
      btn.disabled = true;
    }
    
    try {
      const result = await this._hass.callWS({
        type: 'smart_dashboards/test_trip_breaker',
        breaker_id: breakerId,
      });
      
      // Show feedback
      showToast(this.shadowRoot, result.message || `Test trip: ${result.total_switches} switches tested`, 'success');
    } catch (e) {
      console.error('Test trip failed:', e);
      showToast(this.shadowRoot, 'Test trip failed', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
      }
    }
  }

  async _saveSettings() {
    const roomCards = this.shadowRoot.querySelectorAll('.room-settings-card');
    const rooms = [];

    roomCards.forEach((card) => {
      const nameInput = card.querySelector('.room-name-input');
      const areaSelect = card.querySelector('.room-area-select');
      const mediaPlayerSelect = card.querySelector('.room-media-player');
      const thresholdInput = card.querySelector('.room-threshold');
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
        const plug1SwitchSelect = item.querySelector('.outlet-plug1-switch');
        const isSingleOutlet = !plug2Select;
        const isAppliance = !plug1SwitchSelect;

        if (outletName) {
          const device = {
            name: outletName,
            plug1_entity: plug1 || null,
            threshold: outletThreshold,
          };
          if (isAppliance) {
            device.type = item.dataset.deviceType || 'stove';
            device.plug2_entity = null;
            device.plug1_switch = null;
            device.plug2_switch = null;
            device.plug1_shutoff = 0;
            device.plug2_shutoff = 0;
          } else {
            device.type = isSingleOutlet ? 'single_outlet' : 'outlet';
            device.plug2_entity = isSingleOutlet ? null : (plug2 || null);
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = isSingleOutlet ? null : (plug2Switch || null);
            device.plug1_shutoff = plug1Shutoff;
            device.plug2_shutoff = isSingleOutlet ? 0 : plug2Shutoff;
          }
          outlets.push(device);
        }
      });

      const roomName = nameInput?.value?.trim();
      if (roomName) {
        rooms.push({
          id: roomName.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
          name: roomName,
          area_id: areaSelect?.value || null,
          media_player: mediaPlayerSelect?.value || null,
          threshold: parseInt(thresholdInput?.value) || 0,
          volume: parseFloat(volumeSlider?.value) || 0.7,
          outlets: outlets,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';
    const ttsPrefix = this.shadowRoot.querySelector('#tts-prefix')?.value || 'Message from Home Energy.';
    const ttsRoomWarn = this.shadowRoot.querySelector('#tts-room-warn')?.value || '{prefix} {room_name} is pulling {watts} watts';
    const ttsOutletWarn = this.shadowRoot.querySelector('#tts-outlet-warn')?.value || '{prefix} {room_name} {outlet_name} is pulling {watts} watts';
    const ttsShutoff = this.shadowRoot.querySelector('#tts-shutoff')?.value || '{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload';
    const ttsBreakerWarn = this.shadowRoot.querySelector('#tts-breaker-warn')?.value || '{prefix} {breaker_name} is near its max load, reduce electric use to prevent safety shutoff';
    const ttsBreakerShutoff = this.shadowRoot.querySelector('#tts-breaker-shutoff')?.value || '{prefix} {breaker_name} is currently at its max limit, safety shutoff enabled';
    const ttsStoveOn = this.shadowRoot.querySelector('#tts-stove-on')?.value || '{prefix} Stove has been turned on';
    const ttsStoveOff = this.shadowRoot.querySelector('#tts-stove-off')?.value || '{prefix} Stove has been turned off';
    const ttsStoveTimerStarted = this.shadowRoot.querySelector('#tts-stove-timer-started')?.value || '{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.';
    const ttsStove15Min = this.shadowRoot.querySelector('#tts-stove-15min')?.value || '{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns';
    const ttsStove30Sec = this.shadowRoot.querySelector('#tts-stove-30sec')?.value || '{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen';
    const ttsStoveAutoOff = this.shadowRoot.querySelector('#tts-stove-auto-off')?.value || '{prefix} Stove has been automatically turned off for safety';
    const ttsMicrowaveCut = this.shadowRoot.querySelector('#tts-microwave-cut')?.value || '{prefix} Microwave is on. Stove power cut to protect circuit. Power will restore when microwave is off.';
    const ttsMicrowaveRestore = this.shadowRoot.querySelector('#tts-microwave-restore')?.value || '{prefix} Microwave is off. Stove power restored.';

    // Collect breaker lines
    const breakerCards = this.shadowRoot.querySelectorAll('.breaker-settings-card');
    const breakerLines = [];
    breakerCards.forEach(card => {
      const nameInput = card.querySelector('.breaker-name-input');
      const colorInput = card.querySelector('.breaker-color-input');
      const maxLoadInput = card.querySelector('.breaker-max-load');
      const thresholdInput = card.querySelector('.breaker-threshold');
      const assignedCards = card.querySelectorAll('.outlet-assigned-card');
      
      const outletIds = Array.from(assignedCards).map(c => c.dataset.outletId).filter(Boolean);
      
      if (nameInput?.value) {
        breakerLines.push({
          id: nameInput.value.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
          name: nameInput.value,
          color: colorInput?.value || '#03a9f4',
          max_load: parseInt(maxLoadInput?.value) || 2400,
          threshold: parseInt(thresholdInput?.value) || 0,
          outlet_ids: outletIds,
        });
      }
    });

    // Collect stove safety config
    const stovePlugEntity = this.shadowRoot.querySelector('#stove-plug-entity')?.value || null;
    const stovePlugSwitch = this.shadowRoot.querySelector('#stove-plug-switch')?.value || null;
    const stovePowerThreshold = parseInt(this.shadowRoot.querySelector('#stove-power-threshold')?.value) || 100;
    const stoveCookingTime = parseInt(this.shadowRoot.querySelector('#stove-cooking-time')?.value) || 15;
    const stoveFinalWarning = parseInt(this.shadowRoot.querySelector('#stove-final-warning')?.value) || 30;
    const stovePresenceSensor = this.shadowRoot.querySelector('#stove-presence-sensor')?.value || null;
    const stoveMediaPlayer = this.shadowRoot.querySelector('#stove-media-player')?.value || null;
    const stoveVolume = parseFloat(this.shadowRoot.querySelector('#stove-volume')?.value) || 0.7;
    const stoveMicrowavePlugEntity = this.shadowRoot.querySelector('#stove-microwave-plug-entity')?.value || null;
    const stoveMicrowaveThreshold = parseInt(this.shadowRoot.querySelector('#stove-microwave-threshold')?.value) || 50;

    const config = {
      rooms: rooms,
      breaker_lines: breakerLines,
      stove_safety: {
        stove_plug_entity: stovePlugEntity,
        stove_plug_switch: stovePlugSwitch,
        stove_power_threshold: stovePowerThreshold,
        cooking_time_minutes: stoveCookingTime,
        final_warning_seconds: stoveFinalWarning,
        presence_sensor: stovePresenceSensor,
        media_player: stoveMediaPlayer,
        volume: stoveVolume,
        microwave_plug_entity: stoveMicrowavePlugEntity || null,
        microwave_power_threshold: stoveMicrowaveThreshold,
      },
      tts_settings: {
        language: ttsLanguage,
        speed: 1.0,
        prefix: ttsPrefix,
        room_warn_msg: ttsRoomWarn,
        outlet_warn_msg: ttsOutletWarn,
        shutoff_msg: ttsShutoff,
        breaker_warn_msg: ttsBreakerWarn,
        breaker_shutoff_msg: ttsBreakerShutoff,
        stove_on_msg: ttsStoveOn,
        stove_off_msg: ttsStoveOff,
        stove_timer_started_msg: ttsStoveTimerStarted,
        stove_15min_warn_msg: ttsStove15Min,
        stove_30sec_warn_msg: ttsStove30Sec,
        stove_auto_off_msg: ttsStoveAutoOff,
        microwave_cut_power_msg: ttsMicrowaveCut,
        microwave_restore_power_msg: ttsMicrowaveRestore,
      },
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: config,
      });

      this._config = config;
      showToast(this.shadowRoot, 'Settings saved!', 'success');
      
      setTimeout(() => {
        this._showSettings = false;
        this._render();
        this._startRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', 'error');
    }
  }
}

customElements.define('energy-panel', EnergyPanel);
