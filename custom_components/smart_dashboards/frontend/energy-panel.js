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
    this._settingsTab = 'rooms'; // 'rooms' | 'tts' | 'statistics' | 'enforcement'
    this._dashboardView = 'rooms'; // 'rooms' | 'statistics' | 'stove'
    this._stoveData = null;
    this._refreshInterval = null;
    this._loading = true;
    this._error = null;
    this._draggedRoomCard = null;
    this._graphOpen = null;  // { type, roomId?, roomName? }
    this._graphData = null;  // from get_daily_history
    this._apexChartInstance = null;
    this._statsData = null;  // from get_statistics
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
      if (this._dashboardView === 'statistics') {
        this._loadStatistics();
      }
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
      await Promise.all([
        this._loadPowerData(),
        this._loadStatistics(),
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

  async _loadPowerData() {
    if (!this._hass || this._showSettings) return;

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
    try {
      this._statsData = await this._hass.callWS({ type: 'smart_dashboards/get_statistics' });
      if (this._dashboardView === 'statistics') {
        if (this.shadowRoot.querySelector('.statistics-view')) {
          this._updateStatisticsDisplay();
        } else {
          this._render();
        }
      }
    } catch (e) {
      console.error('Failed to load statistics:', e);
    }
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
    const fmt = (v) => (v == null ? '—' : (typeof v === 'number' ? v.toFixed(2) : String(v)));
    const rangeEl = this.shadowRoot.querySelector('#stat-range-banner');
    const narrowedEl = this.shadowRoot.querySelector('#stat-narrowed');
    if (rangeEl) rangeEl.textContent = rangeBanner;
    if (narrowedEl) narrowedEl.style.display = isNarrowed ? '' : 'none';
    const curEl = this.shadowRoot.querySelector('#stat-current-usage');
    const projEl = this.shadowRoot.querySelector('#stat-projected-usage');
    const costEl = this.shadowRoot.querySelector('#stat-kwh-cost');
    if (curEl) curEl.textContent = `${fmt(sensorValues.current_usage)} kWh`;
    if (projEl) projEl.textContent = `${fmt(sensorValues.projected_usage)} kWh`;
    if (costEl) costEl.textContent = `$${fmt(sensorValues.kwh_cost)}`;
    const totalKwh = s.total_kwh ?? 0;
    const totalWarnings = s.total_warnings ?? 0;
    const totalShutoffs = s.total_shutoffs ?? 0;
    const kwhEl = this.shadowRoot.querySelector('#stat-total-kwh');
    const warnEl = this.shadowRoot.querySelector('#stat-total-warnings');
    const shutEl = this.shadowRoot.querySelector('#stat-total-shutoffs');
    if (kwhEl) kwhEl.textContent = totalKwh.toFixed(2);
    if (warnEl) warnEl.textContent = totalWarnings;
    if (shutEl) shutEl.textContent = totalShutoffs;
    const rooms = s.rooms || [];
    const tbody = this.shadowRoot.querySelector('#stat-rooms-tbody');
    if (tbody) {
      tbody.innerHTML = rooms.length === 0
        ? '<tr><td colspan="5" class="statistics-empty">No room data for this range.</td></tr>'
        : rooms.map(r => `
          <tr>
            <td>${(r.name || r.id || '').replace(/</g, '&lt;')}</td>
            <td>${(r.kwh ?? 0).toFixed(2)}</td>
            <td>${(r.pct ?? 0).toFixed(1)}%</td>
            <td>${r.warnings ?? 0}</td>
            <td>${r.shutoffs ?? 0}</td>
          </tr>
        `).join('');
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
        eventCounts[0].textContent = `Warnings: ${warnings}`;
        eventCounts[1].textContent = `Shutoffs: ${shutoffs}`;
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
        const isAppliance = deviceType === 'stove' || deviceType === 'microwave';
        const outletTotal = isAppliance || isSingleOutlet || isMinisplit
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
      .stat-card.graph-clickable, .graph-clickable {
        cursor: pointer;
      }
      .stat-card.graph-clickable:hover, .graph-clickable:hover {
        opacity: 0.9;
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
        gap: 4px;
        margin-bottom: 16px;
        background: rgba(0, 0, 0, 0.2);
        padding: 4px;
        border-radius: 8px;
      }

      .view-tab {
        flex: 1;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--secondary-text-color);
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
      .statistics-narrowed { margin-left: 8px; font-size: 11px; opacity: 0.9; }
      .statistics-cards {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
        gap: clamp(12px, 3vw, 16px);
      }
      .statistics-sensor-card,
      .statistics-totals-card,
      .statistics-rooms-card {
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        padding: 14px 16px;
      }
      .statistics-card-title { font-size: 12px; font-weight: 600; margin: 0 0 12px; color: var(--panel-accent); }
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
      .statistics-sensor-value,
      .statistics-total-value { font-size: 13px; font-weight: 500; }
      .statistics-table-wrap { overflow-x: auto; }
      .statistics-table { width: 100%; border-collapse: collapse; font-size: 12px; }
      .statistics-table th, .statistics-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--card-border); }
      .statistics-table th { font-weight: 600; color: var(--secondary-text-color); }
      .statistics-empty { color: var(--secondary-text-color); text-align: center; padding: 16px !important; }

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

      .room-meta .meta-right {
        margin-left: auto;
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

      .room-stats {
        text-align: right;
      }

      .view-tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 16px;
        background: rgba(0, 0, 0, 0.2);
        padding: 4px;
        border-radius: 8px;
      }

      .view-tab {
        flex: 1;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--secondary-text-color);
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
      .device-card.minisplit-card .outlet-name-top {
        font-size: 12px;
        color: var(--primary-text-color);
      }

      .device-card.stove-card .outlet-meta,
      .device-card.microwave-card .outlet-meta {
        border-top-color: rgba(255,255,255,0.08);
      }

      .device-card.stove-card .threshold-badge,
      .device-card.microwave-card .threshold-badge {
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
        gap: 3px;
        font-size: 9px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 8px;
        color: #fff;
        background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
        box-shadow: 0 1px 3px rgba(255, 152, 0, 0.3);
        text-transform: uppercase;
        letter-spacing: 0.3px;
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
        align-items: center;
        justify-content: center;
      }

      .device-card.stove-card .stove-door-watts {
        position: absolute;
        font-size: 10px;
        font-weight: 800;
        color: var(--panel-accent, #03a9f4);
        font-variant-numeric: tabular-nums;
        text-shadow: 0 0 4px rgba(0,0,0,0.8);
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
        width: min(95vw, 600px);
        max-width: 100%;
        max-height: min(85vh, 400px);
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
      .graph-chart-container {
        flex: 1;
        min-height: clamp(200px, 45vw, 280px);
        width: 100%;
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
        align-items: center;
        justify-content: space-between;
        gap: 8px;
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
              <div class="stat-card graph-clickable" data-graph-type="total_watts_intraday">
                <div class="stat-value" id="summary-total-watts">${totalWatts.toFixed(1)} W</div>
                <div class="stat-label">Current Power</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_wh_intraday">
                <div class="stat-value" id="summary-total-day">${(totalDayWh / 1000).toFixed(2)} kWh</div>
                <div class="stat-label">Today's Usage</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_warnings">
                <div class="stat-value" id="summary-warnings">${totalWarnings}</div>
                <div class="stat-label">Threshold Warnings</div>
              </div>
              <div class="stat-card graph-clickable" data-graph-type="total_shutoffs">
                <div class="stat-value" id="summary-shutoffs">${totalShutoffs}</div>
                <div class="stat-label">Safety Shutoffs</div>
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
  }

  _renderGraphModal() {
    if (!this._graphData || !this._graphOpen) return '';
    const type = this._graphOpen.type;
    const roomId = this._graphOpen.roomId;
    const roomName = this._graphOpen.roomName || '';
    const labels = {
      total_wh: 'Usage (kWh)', total_watts_intraday: 'Current Power (W)', total_wh_intraday: "Today's Usage (kWh)",
      total_warnings: 'Threshold Warnings', total_shutoffs: 'Safety Shutoffs',
      room_wh: `${roomName} Usage (kWh)`, room_warnings: `${roomName} Warnings`, room_shutoffs: `${roomName} Shutoffs`
    };
    const title = labels[type] || '30-Day History';
    const isIntraday = type === 'total_watts_intraday' || type === 'total_wh_intraday' || type === 'room_wh';
    const dates = isIntraday ? (this._graphData.timestamps || []) : (this._graphData.dates || []);
    const dateLabel = (dates.slice(0, 3).join(' — ') || '') + (dates.length > 3 ? ' … ' : '') + (dates.length > 3 ? dates.slice(-2).join(' — ') : '');
    return `
      <div class="graph-modal-overlay" id="graph-modal-overlay">
        <div class="graph-modal">
          <div class="graph-modal-header">
            <h2 class="graph-modal-title">${title}</h2>
            <button type="button" class="graph-modal-close" id="graph-modal-close" aria-label="Close">×</button>
          </div>
          <div class="graph-modal-body">
            <div class="graph-chart-container" id="graph-apex-chart"></div>
            <div class="graph-dates">${dateLabel}</div>
          </div>
        </div>
      </div>
    `;
  }

  async _openGraph(type, roomId = null, roomName = null) {
    try {
      const isIntraday = type === 'total_watts_intraday' || type === 'total_wh_intraday' || type === 'room_wh';
      let result;
      if (isIntraday) {
        const payload = { type: 'smart_dashboards/get_intraday_history', minutes: 1440 };
        if (roomId) payload.room_id = roomId;
        result = await this._hass.callWS(payload);
      } else {
        result = await this._hass.callWS({ type: 'smart_dashboards/get_daily_history', days: 31 });
      }
      this._graphOpen = { type, roomId, roomName };
      this._graphData = result;
      this._render();
      this._attachGraphModalListeners();
      await this._initApexChart();
    } catch (e) {
      console.error('Failed to load graph data:', e);
      showToast(this.shadowRoot, 'Failed to load history', 'error');
    }
  }

  async _initApexChart() {
    const container = this.shadowRoot.getElementById('graph-apex-chart');
    if (!container || !this._graphData || !this._graphOpen) return;
    const type = this._graphOpen.type;
    const roomId = this._graphOpen.roomId;
    let values = [];
    let dates = [];
    const isIntraday = type === 'total_watts_intraday' || type === 'total_wh_intraday' || type === 'room_wh';
    if (isIntraday) {
      dates = this._graphData.timestamps || [];
      const watts = this._graphData.watts || [];
      if (type === 'total_wh_intraday' || type === 'room_wh') {
        let cum = 0;
        values = watts.map(w => { cum += (w || 0) / 60000; return cum; }); // kWh per minute = watts/60/1000
      } else {
        values = watts.map(w => w || 0);
      }
    } else if (type.startsWith('room_')) {
      const key = type.replace('room_', '');
      values = (this._graphData.rooms?.[roomId]?.[key] || []).map(v => (key === 'wh' ? v / 1000 : v));
      dates = this._graphData.dates || [];
    } else {
      const key = type.replace('total_', '');
      values = (this._graphData[key] || []).map(v => (key === 'wh' ? v / 1000 : v));
      dates = this._graphData.dates || [];
    }
    if (this._apexChartInstance) {
      this._apexChartInstance.destroy();
      this._apexChartInstance = null;
    }
    try {
      const ApexCharts = (await import('https://cdn.jsdelivr.net/npm/apexcharts@3.45.1/dist/apexcharts.esm.min.js')).default;
      const accent = getComputedStyle(this).getPropertyValue('--panel-accent').trim() || '#03a9f4';
      const textColor = getComputedStyle(this).getPropertyValue('--primary-text-color').trim() || '#e1e1e1';
      const gridColor = getComputedStyle(this).getPropertyValue('--card-border').trim() || 'rgba(255,255,255,0.08)';
      const options = {
        chart: {
          type: 'area',
          height: 260,
          fontFamily: 'inherit',
          background: 'transparent',
          toolbar: { show: false },
          zoom: { enabled: false },
          animations: { enabled: true },
        },
        series: [{ name: type.includes('wh') ? 'kWh' : (type.includes('watts') ? 'W' : 'Count'), data: values }],
        xaxis: {
          categories: dates,
          labels: {
            style: { colors: textColor, fontSize: '11px' },
            rotate: -45,
            rotateAlways: dates.length > 10,
            formatter: isIntraday ? (val) => {
              if (!val || typeof val !== 'string') return '';
              const m = val.match(/^\d{4}-\d{2}-\d{2}\s+(\d{1,2}):(\d{2})$/);
              if (!m) return val;
              const h = parseInt(m[1], 10);
              const min = parseInt(m[2], 10);
              if (min !== 0) return '';
              if (h === 0) return '12am';
              if (h === 12) return '12pm';
              return h < 12 ? `${h}am` : `${h - 12}pm`;
            } : undefined,
          },
          axisBorder: { show: true, color: gridColor },
          axisTicks: { show: true, color: gridColor },
        },
        yaxis: {
          labels: { show: false },
          axisBorder: { show: false },
          crosshairs: { show: false },
        },
        colors: [accent],
        fill: {
          type: 'gradient',
          gradient: { shadeIntensity: 0.3, opacityFrom: 0.5, opacityTo: 0.05 },
        },
        stroke: { curve: 'smooth', width: 2 },
        grid: {
          borderColor: gridColor,
          strokeDashArray: 4,
          xaxis: { lines: { show: false } },
          yaxis: { lines: { show: true } },
        },
        dataLabels: { enabled: false },
        tooltip: {
          theme: 'dark',
          x: { format: isIntraday ? 'MMM dd HH:mm' : 'dd MMM yyyy' },
        },
        plotOptions: {
          area: { fillTo: 'origin' },
          line: { dataLabels: { enabled: false } },
        },
        markers: {
          size: values.length <= 5 ? 4 : 0,
          hover: { size: 6 },
        },
      };
      if (dates.length === 0 || values.length === 0) {
        options.noData = { text: 'No data yet', style: { color: textColor } };
      }
      this._apexChartInstance = new ApexCharts(container, options);
      await this._apexChartInstance.render();
    } catch (e) {
      console.error('ApexCharts failed to load:', e);
      container.innerHTML = '<p style="color:var(--secondary-text-color);padding:20px;text-align:center;">Chart failed to load. Check network or try again.</p>';
    }
  }

  _attachGraphModalListeners() {
    const overlay = this.shadowRoot.getElementById('graph-modal-overlay');
    const closeBtn = this.shadowRoot.getElementById('graph-modal-close');
    const close = () => {
      if (this._apexChartInstance) {
        this._apexChartInstance.destroy();
        this._apexChartInstance = null;
      }
      this._graphOpen = null;
      this._graphData = null;
      this._render();
    };
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
    const rooms = s.rooms || [];

    const fmt = (v) => (v == null ? '—' : (typeof v === 'number' ? v.toFixed(2) : String(v)));

    return `
      <div class="statistics-view">
        <div class="statistics-banner">
          <span class="statistics-range" id="stat-range-banner">${rangeBanner}</span>
          <span class="statistics-narrowed" id="stat-narrowed" style="${isNarrowed ? '' : 'display:none'}">Narrowed from billing cycle.</span>
        </div>
        <div class="statistics-cards">
          <div class="statistics-sensor-card card">
            <h3 class="statistics-card-title">Utility Sensors</h3>
            <div class="statistics-sensor-grid">
              <div class="statistics-sensor-item">
                <span class="statistics-sensor-label">Current Usage</span>
                <span class="statistics-sensor-value" id="stat-current-usage">${fmt(currentUsage)} kWh</span>
              </div>
              <div class="statistics-sensor-item">
                <span class="statistics-sensor-label">Projected Usage</span>
                <span class="statistics-sensor-value" id="stat-projected-usage">${fmt(projectedUsage)} kWh</span>
              </div>
              <div class="statistics-sensor-item">
                <span class="statistics-sensor-label">kWh Cost</span>
                <span class="statistics-sensor-value" id="stat-kwh-cost">$${fmt(kwhCost)}</span>
              </div>
            </div>
          </div>
          <div class="statistics-totals-card card">
            <h3 class="statistics-card-title">Totals (from daily data)</h3>
            <div class="statistics-totals-grid">
              <div class="statistics-total-item">
                <span class="statistics-total-value" id="stat-total-kwh">${totalKwh.toFixed(2)}</span>
                <span class="statistics-total-label">kWh</span>
              </div>
              <div class="statistics-total-item">
                <span class="statistics-total-value" id="stat-total-warnings">${totalWarnings}</span>
                <span class="statistics-total-label">Warnings</span>
              </div>
              <div class="statistics-total-item">
                <span class="statistics-total-value" id="stat-total-shutoffs">${totalShutoffs}</span>
                <span class="statistics-total-label">Shutoffs</span>
              </div>
            </div>
          </div>
        </div>
        <div class="statistics-rooms-card card">
          <h3 class="statistics-card-title">Room Breakdown</h3>
          <div class="statistics-table-wrap">
            <table class="statistics-table">
              <thead>
                <tr>
                  <th>Room</th>
                  <th>kWh</th>
                  <th>%</th>
                  <th>Warnings</th>
                  <th>Shutoffs</th>
                </tr>
              </thead>
              <tbody id="stat-rooms-tbody">
                ${rooms.length === 0 ? '<tr><td colspan="5" class="statistics-empty">No room data for this range.</td></tr>' : ''}
                ${rooms.map(r => `
                  <tr>
                    <td>${(r.name || r.id || '').replace(/</g, '&lt;')}</td>
                    <td>${(r.kwh ?? 0).toFixed(2)}</td>
                    <td>${(r.pct ?? 0).toFixed(1)}%</td>
                    <td>${r.warnings ?? 0}</td>
                    <td>${r.shutoffs ?? 0}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
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
    const roomId = room.id || (room.name || '').toLowerCase().replace(/\s+/g, '_');
    const roomData = this._powerData?.rooms?.find(r => r.id === roomId) || {
      total_watts: 0,
      total_day_wh: 0,
      warnings: 0,
      shutoffs: 0,
      outlets: [],
    };

    const isOverThreshold = room.threshold > 0 && roomData.total_watts > room.threshold;
    const warnings = roomData.warnings || 0;
    const shutoffs = roomData.shutoffs || 0;
    const pe = this._config?.power_enforcement || {};
    const roomsEnabled = pe.rooms_enabled || [];
    const isEnforcementEnabled = pe.enabled && roomsEnabled.includes(roomId);

    return `
      <div class="room-card" data-room-id="${roomId}">
        <div class="room-header">
          <div class="room-info">
            <div class="room-icon">
              <svg viewBox="0 0 24 24">${icons.room}</svg>
            </div>
            <div>
              <h3 class="room-name">${(room.name || '').replace(/</g, '&lt;')}</h3>
              <div class="room-meta">
                <span class="has-tooltip" title="Number of outlets and devices in this room">${(room.outlets || []).length} devices</span>
                ${room.threshold > 0 ? `
                  <span class="threshold-badge has-tooltip" title="Room power threshold; TTS alert when exceeded">
                    <svg viewBox="0 0 24 24">${icons.warning}</svg>
                    ${room.threshold}W limit
                  </span>
                ` : ''}
                <span class="event-count graph-clickable has-tooltip" data-graph-type="room_warnings" data-room-id="${roomId}" title="TTS threshold warning count today">Warnings: ${warnings}</span>
                <span class="event-count graph-clickable has-tooltip" data-graph-type="room_shutoffs" data-room-id="${roomId}" title="Safety plug shutoff count today">Shutoffs: ${shutoffs}</span>
                ${isEnforcementEnabled && icons && icons.shield ? `
                  <span class="meta-right">
                    <span class="enforcement-badge has-tooltip" title="Power enforcement is active; volume escalation and power cycling may occur on repeated threshold breaches">
                      <svg viewBox="0 0 24 24" style="width: 12px; height: 12px; fill: #fff;">${icons.shield}</svg>
                      Enforced
                    </span>
                  </span>
                ` : ''}
              </div>
            </div>
          </div>
          <div class="room-stats">
            <div class="room-total-watts ${isOverThreshold ? 'over-threshold' : ''}">${roomData.total_watts.toFixed(1)} W</div>
            <div class="room-total-day graph-clickable" data-graph-type="room_wh" data-room-id="${roomId}">${(roomData.total_day_wh / 1000).toFixed(2)} kWh today</div>
          </div>
        </div>

        <div class="room-content">
          <div class="outlets-grid">
            ${(room.outlets || []).map((device, oi) => this._renderDeviceCard(device, oi, (roomData.outlets || [])[oi])).join('')}
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
    if (type === 'light') return this._renderLightCard(device, index, deviceData);
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

  _renderSettings(styles) {
    const rooms = this._config?.rooms || [];
    const mediaPlayers = this._entities?.media_players || [];
    const powerSensors = this._entities?.power_sensors || [];
    const sensors = this._entities?.sensors || this._entities?.power_sensors || [];
    const ttsSettings = this._config?.tts_settings || {};
    const statsSettings = this._config?.statistics_settings || {};
    const pe = this._config?.power_enforcement || {};
    const roomsEnabled = pe.rooms_enabled || [];

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
            <button class="settings-tab ${this._settingsTab === 'statistics' ? 'active' : ''}" data-tab="statistics">
              Statistics
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
              
              <h3 style="margin: 24px 0 12px 0; border-top: 1px solid var(--card-border); padding-top: 16px;">Power Enforcement Messages</h3>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 1 Warning (Volume Escalation)</div>
                <div class="tts-msg-desc">Spoken when warning count triggers volume escalation phase</div>
                <input type="text" class="form-input" id="tts-phase1-warn" 
                  value="${ttsSettings.phase1_warn_msg || ''}" 
                  placeholder="{prefix} {room_name} has hit {warning_count} threshold warnings within the hour...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{warning_count}</code> <code>{threshold}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase 2 Warning (Power Cycling)</div>
                <div class="tts-msg-desc">Spoken when warning count triggers power cycling phase</div>
                <input type="text" class="form-input" id="tts-phase2-warn" 
                  value="${ttsSettings.phase2_warn_msg || ''}" 
                  placeholder="{prefix} {room_name} has hit {warning_count} threshold warnings within 30 minutes...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{warning_count}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Phase Reset Message</div>
                <div class="tts-msg-desc">Spoken when room maintains power below threshold for reset time</div>
                <input type="text" class="form-input" id="tts-phase-reset" 
                  value="${ttsSettings.phase_reset_msg || ''}" 
                  placeholder="{prefix} {room_name} has maintained power below threshold...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Room kWh Warning</div>
                <div class="tts-msg-desc">Spoken when room exceeds daily kWh interval</div>
                <input type="text" class="form-input" id="tts-room-kwh-warn" 
                  value="${ttsSettings.room_kwh_warn_msg || ''}" 
                  placeholder="{prefix} {room_name} has exceeded {kwh_limit} kWh...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{room_name}</code> <code>{kwh_limit}</code> <code>{percentage}</code></div>
              </div>
              <div class="tts-msg-group">
                <div class="tts-msg-title">Home kWh Warning</div>
                <div class="tts-msg-desc">Spoken when home exceeds daily kWh limit</div>
                <input type="text" class="form-input" id="tts-home-kwh-warn" 
                  value="${ttsSettings.home_kwh_warn_msg || ''}" 
                  placeholder="{prefix} Your home has exceeded {kwh_limit} kWh...">
                <div class="tts-var-help">Variables: <code>{prefix}</code> <code>{kwh_limit}</code></div>
              </div>
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
                </div>
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
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Warning Count to Trigger</label>
                    <input type="number" class="form-input" id="pe-phase2-count" value="${pe.phase2_warning_count || 40}" min="1" max="200">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Time Window (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase2-window" value="${pe.phase2_time_window_minutes || 30}" min="1" max="120">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Cycle Delay (seconds)</label>
                    <input type="number" class="form-input" id="pe-phase2-delay" value="${pe.phase2_cycle_delay_seconds || 5}" min="1" max="30">
                  </div>
                  <div class="form-group">
                    <label class="form-label">Reset After (minutes)</label>
                    <input type="number" class="form-input" id="pe-phase2-reset" value="${pe.phase2_reset_minutes || 30}" min="1" max="180">
                  </div>
                </div>
              </div>
              <div class="tts-msg-group" style="margin-bottom: 16px;">
                <div class="tts-msg-title">Daily kWh Warnings</div>
                <div class="grid-2">
                  <div class="form-group">
                    <label class="form-label">Room kWh Intervals (comma-separated)</label>
                    <input type="text" class="form-input" id="pe-room-kwh-intervals" value="${(pe.room_kwh_intervals || [5, 10, 15, 20]).join(', ')}" placeholder="5, 10, 15, 20">
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
                    const roomId = room.id || (room.name || '').toLowerCase().replace(/\s+/g, '_');
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
      </div>
    `;

    this._attachSettingsEventListeners();
    initCustomSelects(this.shadowRoot);
  }

  _getAllOutlets() {
    const rooms = this._config?.rooms || [];
    const outlets = [];
    rooms.forEach(room => {
      const roomId = room.id || (room.name || '').toLowerCase().replace(/\s+/g, '_');
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

  _renderRoomSettings(room, index, mediaPlayers, powerSensors) {
    return `
      <div class="room-settings-card" data-room-index="${index}" draggable="false">
        <div class="room-settings-header">
          <div class="room-drag-handle" title="Drag to reorder rooms">
            <svg viewBox="0 0 24 24">${icons.menu}</svg>
          </div>
          <input type="text" class="form-input room-name-input" value="${room.name}" placeholder="Room name" style="max-width: 180px;">
          <div style="display: flex; gap: 8px;">
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
                <button class="add-device-option" data-type="minisplit">Mini-Split (Heater/AC)</button>
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
    if (type === 'light') {
      return this._renderLightSettings(device, deviceIndex, roomIndex, isCollapsed);
    }
    return this._renderOutletSettings(device, deviceIndex, powerSensors, roomIndex, isCollapsed);
  }

  _renderLightSettings(device, deviceIndex, roomIndex, isCollapsed = true) {
    // Switch Entity: only switch.* entities (e.g. switch.hallway_switch)
    const allSwitches = this._getFilteredSwitches(roomIndex);
    const switches = (allSwitches || []).filter(s => (s.entity_id || '').startsWith('switch.'));
    // Mapped Light Entities: only light.* entities (e.g. light.bathroom_light)
    const allLights = this._entities?.lights || [];
    const lights = allLights.filter(l => (l.entity_id || '').startsWith('light.'));
    const displayName = device.name || 'Unnamed Light';
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

    const lightRowsHtml = lightEntityRows.map((row, idx) => `
      <div class="light-entity-row" data-row-index="${idx}">
        <div class="light-field-inline">
          <span class="light-label">Entity</span>
          ${this._renderEntityAutocomplete(row.entity_id || '', 'light', roomIndex, 'light-entity-select', 'light.bathroom_light')}
        </div>
        <div class="light-field-inline">
          <span class="light-label">Max Power</span>
          <input type="number" class="form-input light-entity-watts" value="${row.watts}" min="0" max="500" step="1" placeholder="0" title="Running power when on">
        </div>
        <div class="light-field-inline">
          <span class="light-label">Is this a smart WRGB light?</span>
          <label class="toggle-switch">
            <input type="checkbox" class="light-entity-wrgb-toggle" ${row.wrgb ? 'checked' : ''} title="WRGB (White/Red/Green/Blue) light">
            <span class="toggle-slider"></span>
          </label>
        </div>
        <button type="button" class="icon-btn danger light-entity-remove-btn" title="Remove"><svg viewBox="0 0 24 24">${icons.delete}</svg></button>
      </div>
    `).join('');

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
              <div class="form-group">
                <label class="form-label">Switch Entity</label>
                ${this._renderEntityAutocomplete(device.switch_entity || '', 'switch', roomIndex, 'light-switch-entity', 'switch.hallway_switch')}
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Switch entities only (switch.*). Type to search. Primary switch for on/off state.</div>
              </div>
              <div class="form-group">
                <label class="form-label">Mapped Lights & Running Power (W)</label>
                <div class="light-entity-rows">
                  ${lightRowsHtml}
                </div>
                <button type="button" class="btn btn-secondary light-entity-add-btn" style="margin-top: 8px;">+ Add light</button>
                <div style="font-size: 10px; color: var(--secondary-text-color); margin-top: 4px;">Used for room totals and daily energy.</div>
              </div>
              <button class="test-switch-btn" data-switch="${device.switch_entity || ''}" title="Test switch">
                <svg viewBox="0 0 24 24">${icons.power}</svg> Test Switch
              </button>
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
              <label class="form-label">Final Warning (sec)</label>
              <input type="number" class="form-input stove-final-warning" value="${device.final_warning_seconds ?? 30}" min="5" max="300" placeholder="30">
            </div>
            <div class="form-group">
              <label class="form-label">Presence Sensor</label>
              ${this._renderEntityAutocomplete(device.presence_sensor || '', 'binary_sensor', roomIndex, 'stove-presence-sensor', 'binary_sensor.kitchen_presence')}
            </div>
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
        const room = roomId ? this._config?.rooms?.find(r => r.id === roomId) : null;
        this._openGraph(type, roomId, room?.name || null);
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
          this._showSettings = true;
          this._stopRefresh();
          await this._loadConfig();
          this._render();
        }
      });
    }

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

    // Room save buttons
    this.shadowRoot.querySelectorAll('.room-save-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const roomIndex = parseInt(btn.dataset.index);
        await this._saveSingleRoom(roomIndex);
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

    // Test switch buttons
    this.shadowRoot.querySelectorAll('.test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });

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
      volume: 0.7,
      outlets: [],
    };
    
    const html = this._renderRoomSettings(newRoom, index, mediaPlayers, powerSensors);
    list.insertAdjacentHTML('beforeend', html);

    // Attach event listeners for the new room
    const newCard = list.querySelector(`.room-settings-card[data-room-index="${index}"]`);
    this._attachRoomDragListeners(newCard);

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
    const newOutlet = {
      name: '',
      type: deviceType,
      plug1_entity: isLight ? null : '',
      plug2_entity: deviceType === 'outlet' ? '' : null,
      plug1_switch: isAppliance || isLight ? null : '',
      plug2_switch: deviceType === 'outlet' ? '' : null,
      threshold: 0,
      plug1_shutoff: isAppliance || isLight ? 0 : 0,
      plug2_shutoff: deviceType === 'outlet' ? 0 : null,
    };
    if (isLight) {
      newOutlet.switch_entity = '';
      newOutlet.light_entities = [];
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
    const lights = (this._entities?.lights || []).filter(l => (l.entity_id || '').startsWith('light.'));
    if (lightEntityRows && lightEntityAddBtn) {
      const addRow = () => {
        const row = document.createElement('div');
        row.className = 'light-entity-row';
        const acHtml = this._renderEntityAutocomplete('', 'light', roomIndex, 'light-entity-select', 'light.bathroom_light');
        row.innerHTML = `
          <div class="light-field-inline">
            <span class="light-label">Entity</span>
            ${acHtml}
          </div>
          <div class="light-field-inline">
            <span class="light-label">Max Power</span>
            <input type="number" class="form-input light-entity-watts" value="0" min="0" max="500" step="1" placeholder="0" title="Running power when on">
          </div>
          <div class="light-field-inline">
            <span class="light-label">Is this a smart WRGB light?</span>
            <label class="toggle-switch">
              <input type="checkbox" class="light-entity-wrgb-toggle" title="WRGB (White/Red/Green/Blue) light">
              <span class="toggle-slider"></span>
            </label>
          </div>
          <button type="button" class="icon-btn danger light-entity-remove-btn" title="Remove"><svg viewBox="0 0 24 24">${icons.delete}</svg></button>
        `;
        row.querySelector('.light-entity-remove-btn').addEventListener('click', () => row.remove());
        lightEntityRows.appendChild(row);
        this._initEntityAutocompletes(row);
      };
      lightEntityAddBtn.addEventListener('click', addRow);
      lightEntityRows.querySelectorAll('.light-entity-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => btn.closest('.light-entity-row')?.remove());
      });
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
    outletItem.querySelectorAll('.test-switch-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._testToggleSwitch(btn);
      });
    });
  }

  async _saveEnforcementSettings() {
    const pe = {
      enabled: this.shadowRoot.querySelector('#pe-enabled')?.checked || false,
      phase1_warning_count: parseInt(this.shadowRoot.querySelector('#pe-phase1-count')?.value) || 20,
      phase1_time_window_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase1-window')?.value) || 60,
      phase1_volume_increment: parseInt(this.shadowRoot.querySelector('#pe-phase1-vol-inc')?.value) || 2,
      phase1_reset_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase1-reset')?.value) || 60,
      phase2_warning_count: parseInt(this.shadowRoot.querySelector('#pe-phase2-count')?.value) || 40,
      phase2_time_window_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase2-window')?.value) || 30,
      phase2_cycle_delay_seconds: parseInt(this.shadowRoot.querySelector('#pe-phase2-delay')?.value) || 5,
      phase2_reset_minutes: parseInt(this.shadowRoot.querySelector('#pe-phase2-reset')?.value) || 30,
      room_kwh_intervals: (this.shadowRoot.querySelector('#pe-room-kwh-intervals')?.value || '5, 10, 15, 20')
        .split(',')
        .map(s => parseInt(s.trim()))
        .filter(n => !isNaN(n) && n > 0),
      home_kwh_limit: parseInt(this.shadowRoot.querySelector('#pe-home-kwh-limit')?.value) || 22,
      rooms_enabled: [],
    };
    this.shadowRoot.querySelectorAll('.pe-room-checkbox:checked').forEach(cb => {
      pe.rooms_enabled.push(cb.dataset.roomId);
    });
    try {
      const energyConfig = {
        ...this._config,
        power_enforcement: pe,
      };
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: energyConfig,
      });
      this._config.power_enforcement = pe;
      showToast(this.shadowRoot, 'Power enforcement settings saved!', 'success');
    } catch (e) {
      console.error('Failed to save enforcement settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', 'error');
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
            device.cooking_time_minutes = parseInt(item.querySelector('.stove-cooking-time')?.value) || 15;
            device.final_warning_seconds = parseInt(item.querySelector('.stove-final-warning')?.value) || 30;
            device.presence_sensor = item.querySelector('.stove-presence-sensor')?.value || null;
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
          } else if (deviceTypeFromItem === 'minisplit') {
            device.type = 'minisplit';
            device.plug2_entity = null;
            device.plug1_switch = plug1Switch || null;
            device.plug2_switch = null;
            device.plug1_shutoff = plug1Shutoff;
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
          volume: parseFloat(volumeSlider?.value) || 0.7,
          responsive_light_warnings: responsiveToggle?.checked === true && !responsiveToggle.disabled,
          responsive_light_color: rgb,
          responsive_light_temp: tempK,
          responsive_light_interval: interval,
          outlets: outlets,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';
    const ttsPrefix = this.shadowRoot.querySelector('#tts-prefix')?.value || 'Message from Home Energy.';
    const ttsRoomWarn = this.shadowRoot.querySelector('#tts-room-warn')?.value || '{prefix} {room_name} is pulling {watts} watts';
    const ttsOutletWarn = this.shadowRoot.querySelector('#tts-outlet-warn')?.value || '{prefix} {room_name} {outlet_name} is pulling {watts} watts';
    const ttsShutoff = this.shadowRoot.querySelector('#tts-shutoff')?.value || '{prefix} {room_name} {outlet_name} {plug} has been reset to protect circuit from overload';
    const ttsStoveOn = this.shadowRoot.querySelector('#tts-stove-on')?.value || '{prefix} Stove has been turned on';
    const ttsStoveOff = this.shadowRoot.querySelector('#tts-stove-off')?.value || '{prefix} Stove has been turned off';
    const ttsStoveTimerStarted = this.shadowRoot.querySelector('#tts-stove-timer-started')?.value || '{prefix} The stove is on with no one in the kitchen. A {cooking_time_minutes} minute Unattended cooking timer has started.';
    const ttsStove15Min = this.shadowRoot.querySelector('#tts-stove-15min')?.value || '{prefix} Stove has been on for {cooking_time_minutes} minutes with no one in the kitchen. Stove will automatically turn off in {final_warning_seconds} seconds if no one returns';
    const ttsStove30Sec = this.shadowRoot.querySelector('#tts-stove-30sec')?.value || '{prefix} Stove will automatically turn off in {final_warning_seconds} seconds if no one returns to the kitchen';
    const ttsStoveAutoOff = this.shadowRoot.querySelector('#tts-stove-auto-off')?.value || '{prefix} Stove has been automatically turned off for safety';
    const ttsPhase1Warn = this.shadowRoot.querySelector('#tts-phase1-warn')?.value || '';
    const ttsPhase2Warn = this.shadowRoot.querySelector('#tts-phase2-warn')?.value || '';
    const ttsPhaseReset = this.shadowRoot.querySelector('#tts-phase-reset')?.value || '';
    const ttsRoomKwhWarn = this.shadowRoot.querySelector('#tts-room-kwh-warn')?.value || '';
    const ttsHomeKwhWarn = this.shadowRoot.querySelector('#tts-home-kwh-warn')?.value || '';

    const tabStats = this.shadowRoot.querySelector('#tab-statistics');
    const _si = (cls) => (tabStats?.querySelector(`input.${cls}`)?.value ?? '').trim();
    const statistics_settings = {
      billing_start_sensor: _si('stats-billing-start'),
      billing_end_sensor: _si('stats-billing-end'),
      current_usage_sensor: _si('stats-current-usage'),
      projected_usage_sensor: _si('stats-projected-usage'),
      kwh_cost_sensor: _si('stats-kwh-cost'),
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
    const power_enforcement = {
      enabled: _pei('pe-enabled') === true,
      phase1_warning_count: parseInt(_pei('pe-phase1-count')) || 20,
      phase1_time_window_minutes: parseInt(_pei('pe-phase1-window')) || 60,
      phase1_volume_increment: parseInt(_pei('pe-phase1-vol-inc')) || 2,
      phase1_reset_minutes: parseInt(_pei('pe-phase1-reset')) || 60,
      phase2_warning_count: parseInt(_pei('pe-phase2-count')) || 40,
      phase2_time_window_minutes: parseInt(_pei('pe-phase2-window')) || 30,
      phase2_cycle_delay_seconds: parseInt(_pei('pe-phase2-delay')) || 5,
      phase2_reset_minutes: parseInt(_pei('pe-phase2-reset')) || 30,
      room_kwh_intervals: (_pei('pe-room-kwh-intervals') || '5, 10, 15, 20')
        .split(',')
        .map(s => parseInt(String(s).trim()))
        .filter(n => !isNaN(n) && n > 0),
      home_kwh_limit: parseInt(_pei('pe-home-kwh-limit')) || 22,
      rooms_enabled: roomsEnabled,
    };

    const config = {
      rooms: rooms,
      breaker_lines: this._config?.breaker_lines || [],
      breaker_panel_size: this._config?.breaker_panel_size ?? 20,
      statistics_settings,
      tts_settings: {
        language: ttsLanguage,
        speed: this._config?.tts_settings?.speed ?? 1.0,
        volume: this._config?.tts_settings?.volume ?? 0.7,
        prefix: ttsPrefix,
        room_warn_msg: ttsRoomWarn,
        outlet_warn_msg: ttsOutletWarn,
        shutoff_msg: ttsShutoff,
        stove_on_msg: ttsStoveOn,
        stove_off_msg: ttsStoveOff,
        stove_timer_started_msg: ttsStoveTimerStarted,
        stove_15min_warn_msg: ttsStove15Min,
        stove_30sec_warn_msg: ttsStove30Sec,
        stove_auto_off_msg: ttsStoveAutoOff,
        phase1_warn_msg: ttsPhase1Warn,
        phase2_warn_msg: ttsPhase2Warn,
        phase_reset_msg: ttsPhaseReset,
        room_kwh_warn_msg: ttsRoomKwhWarn,
        home_kwh_warn_msg: ttsHomeKwhWarn,
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
      
      // Refresh the same page instead of going back to dashboard
      setTimeout(() => {
        this._render();
        this._startRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', 'error');
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
          device.cooking_time_minutes = parseInt(item.querySelector('.stove-cooking-time')?.value) || 15;
          device.final_warning_seconds = parseInt(item.querySelector('.stove-final-warning')?.value) || 30;
          device.presence_sensor = item.querySelector('.stove-presence-sensor')?.value || null;
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
        } else if (deviceTypeFromItem === 'minisplit') {
          device.type = 'minisplit';
          device.plug2_entity = null;
          device.plug1_switch = plug1Switch || null;
          device.plug2_switch = null;
          device.plug1_shutoff = plug1Shutoff;
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

    const updatedRoom = {
      id: roomName.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
      name: roomName,
      media_player: mediaPlayer,
      threshold: parseInt(thresholdInput?.value) || 0,
      volume: parseFloat(volumeSlider?.value) || 0.7,
      responsive_light_warnings: responsiveToggle?.checked === true && !responsiveToggle.disabled,
      responsive_light_color: rgb,
      responsive_light_temp: tempK,
      responsive_light_interval: interval,
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
      rooms: filteredRooms,
      tts_settings: ttsSettings,
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: config,
      });

      this._config = config;
      showToast(this.shadowRoot, 'Room saved!', 'success');
      
      // Refresh the page to show updated data
      setTimeout(() => {
        this._render();
        this._startRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save room:', e);
      showToast(this.shadowRoot, 'Failed to save room', 'error');
    }
  }
}

customElements.define('energy-panel', EnergyPanel);
