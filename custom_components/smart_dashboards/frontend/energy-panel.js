/**
 * Energy Panel for Smart Dashboards
 * Room-based power monitoring with automatic TTS threshold alerts
 */

import { sharedStyles, icons, showToast, passcodeModalStyles, showPasscodeModal } from './shared-utils.js';

class EnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._powerData = null;
    this._showSettings = false;
    this._settingsTab = 'rooms'; // 'rooms' or 'tts'
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
    this._refreshInterval = setInterval(() => this._loadPowerData(), 1000);
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
      this._areas = areasResult.areas || [];
      this._areaSensors = {};
      this._areaSwitches = {};
      await this._loadPowerData();
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
      this._updatePowerDisplay();
    } catch (e) {
      console.error('Failed to load power data:', e);
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
    if (totalWattsEl) totalWattsEl.textContent = `${totalWatts.toFixed(1)} W`;
    if (totalDayEl) totalDayEl.textContent = `${(totalDayWh / 1000).toFixed(2)} kWh`;
    
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

      // Update individual outlets
      room.outlets.forEach((outlet, i) => {
        const outletCard = roomCard.querySelector(`.outlet-card[data-outlet-index="${i}"]`);
        if (!outletCard) return;

        const outletConfig = roomConfig?.outlets?.[i];
        const outletThreshold = outletConfig?.threshold || 0;
        const outletTotal = outlet.plug1.watts + outlet.plug2.watts;

        const plug1Watts = outletCard.querySelector('.plug1-watts');
        const plug2Watts = outletCard.querySelector('.plug2-watts');
        const outletTotalEl = outletCard.querySelector('.outlet-total');

        if (plug1Watts) plug1Watts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
        if (plug2Watts) plug2Watts.textContent = `${outlet.plug2.watts.toFixed(1)} W`;
        if (outletTotalEl) {
          outletTotalEl.textContent = `${outletTotal.toFixed(1)} W`;
          outletTotalEl.classList.toggle('over-threshold', outletThreshold > 0 && outletTotal > outletThreshold);
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

      .room-stats {
        text-align: right;
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

      .outlet-card {
        width: 100px;
        min-width: 100px;
        flex-shrink: 0;
      }

      @media (max-width: 500px) {
        .outlet-card {
          width: 90px;
          min-width: 90px;
        }
      }

      .outlet-card {
        background: rgba(0, 0, 0, 0.3);
        border-radius: 8px;
        padding: 6px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        position: relative;
        box-sizing: border-box;
      }

      .outlet-header {
        text-align: center;
        margin-bottom: 4px;
        padding-bottom: 3px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }

      .outlet-name {
        font-size: 8px;
        font-weight: 500;
        color: var(--secondary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .outlet-name svg {
        display: none;
      }

      .outlet-total {
        font-size: 10px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        margin-top: 1px;
        white-space: nowrap;
        overflow: hidden;
      }

      .outlet-total.over-threshold {
        color: var(--panel-danger);
      }

      .plugs-container {
        display: flex;
        flex-direction: column;
        gap: 3px;
      }

      .plug-card {
        background: #1a1a1a;
        border-radius: 5px;
        padding: 4px 5px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }

      .plug-card::before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: rgba(3, 169, 244, 0.3);
        border: 1px solid rgba(3, 169, 244, 0.5);
        flex-shrink: 0;
      }

      .plug-card.active::before {
        background: var(--panel-accent);
        box-shadow: 0 0 4px var(--panel-accent);
      }

      .plug-label {
        font-size: 7px;
        text-transform: uppercase;
        letter-spacing: 0.2px;
        color: var(--secondary-text-color);
        flex: 1;
        margin-left: 4px;
      }

      .plug-watts {
        font-size: 9px;
        font-weight: 600;
        color: var(--primary-text-color);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
      }

      .threshold-badge {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        font-size: 7px;
        color: var(--secondary-text-color);
        padding: 1px 3px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 2px;
        white-space: nowrap;
        overflow: hidden;
      }

      .threshold-badge svg {
        width: 6px;
        height: 6px;
        fill: currentColor;
      }

      .outlet-threshold {
        text-align: center;
        margin-top: 3px;
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

      .room-settings-body .form-input,
      .room-settings-body .form-select {
        padding: 8px 10px;
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
        padding: 6px 8px;
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
                <div class="stat-value">${rooms.length}</div>
                <div class="stat-label">Monitored Rooms</div>
              </div>
            </div>
          ` : ''}

          ${rooms.length === 0 ? this._renderEmptyState() : ''}
          
          <div class="rooms-grid">
            ${rooms.map((room) => this._renderRoomCard(room)).join('')}
          </div>
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
      outlets: [],
    };

    const isOverThreshold = room.threshold > 0 && roomData.total_watts > room.threshold;

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
                <span>${room.outlets?.length || 0} outlets</span>
                ${room.threshold > 0 ? `
                  <span class="threshold-badge">
                    <svg viewBox="0 0 24 24">${icons.warning}</svg>
                    ${room.threshold}W limit
                  </span>
                ` : ''}
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
            ${(room.outlets || []).map((outlet, oi) => this._renderOutletCard(outlet, oi, roomData.outlets[oi])).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletCard(outlet, index, outletData) {
    const data = outletData || { plug1: { watts: 0 }, plug2: { watts: 0 } };
    const outletTotal = data.plug1.watts + data.plug2.watts;
    const isOverThreshold = outlet.threshold > 0 && outletTotal > outlet.threshold;
    const plug1Active = data.plug1.watts > 0.1;
    const plug2Active = data.plug2.watts > 0.1;

    return `
      <div class="outlet-card" data-outlet-index="${index}">
        <div class="outlet-header">
          <div class="outlet-name">${outlet.name}</div>
          <div class="outlet-total ${isOverThreshold ? 'over-threshold' : ''}">${outletTotal.toFixed(1)} W</div>
        </div>
        <div class="plugs-container">
          <div class="plug-card ${plug1Active ? 'active' : ''}">
            <span class="plug-label">P1</span>
            <span class="plug-watts plug1-watts">${data.plug1.watts.toFixed(1)}W</span>
          </div>
          <div class="plug-card ${plug2Active ? 'active' : ''}">
            <span class="plug-label">P2</span>
            <span class="plug-watts plug2-watts">${data.plug2.watts.toFixed(1)}W</span>
          </div>
        </div>
        <div class="outlet-threshold">
          <span class="threshold-badge">${outlet.threshold > 0 ? `${outlet.threshold}W` : '∞ W'}</span>
        </div>
      </div>
    `;
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
              Rooms & Outlets
            </button>
            <button class="settings-tab ${this._settingsTab === 'tts' ? 'active' : ''}" data-tab="tts">
              TTS Settings
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
            </div>
          </div>
        </div>
      </div>
    `;

    this._attachSettingsEventListeners();
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
            <h4 style="margin: 0; font-size: 11px; color: var(--secondary-text-color);">Outlets</h4>
            <button class="btn btn-secondary add-outlet-btn" data-room-index="${index}">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
              Add
            </button>
          </div>

          <div class="outlets-settings-list" id="outlets-list-${index}">
            ${(room.outlets || []).map((outlet, oi) => this._renderOutletSettings(outlet, oi, filteredSensors, index)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletSettings(outlet, outletIndex, powerSensors, roomIndex, isCollapsed = true) {
    const switches = this._getFilteredSwitches(roomIndex);
    
    // Sort switches by similarity to each plug sensor
    const plug1Switches = this._sortSwitchesBySimilarity(switches, outlet.plug1_entity);
    const plug2Switches = this._sortSwitchesBySimilarity(switches, outlet.plug2_entity);
    
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
          
          <div class="plugs-settings-grid">
            <div class="plug-settings-card" data-plug="1">
              <div class="plug-settings-title">Plug 1</div>
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

    // Add outlet buttons
    this.shadowRoot.querySelectorAll('.add-outlet-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const roomIndex = btn.dataset.roomIndex;
        this._addOutlet(roomIndex);
      });
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

    const addOutletBtn = newCard.querySelector('.add-outlet-btn');
    addOutletBtn.addEventListener('click', () => this._addOutlet(index));

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

  _addOutlet(roomIndex) {
    const sensors = this._getFilteredSensors(roomIndex);
    const list = this.shadowRoot.querySelector(`#outlets-list-${roomIndex}`);
    const roomCard = list.closest('.room-settings-card');
    
    // Collapse all existing outlets first
    list.querySelectorAll('.outlet-settings-item').forEach(item => {
      item.classList.add('collapsed');
    });
    
    // Generate new outlet index (will be at top, so re-index all)
    const newOutlet = {
      name: '',
      plug1_entity: '',
      plug2_entity: '',
      plug1_switch: '',
      plug2_switch: '',
      threshold: 0,
      plug1_shutoff: 0,
      plug2_shutoff: 0,
    };
    
    // Render as expanded (not collapsed)
    const html = this._renderOutletSettings(newOutlet, 0, sensors, roomIndex, false);
    
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
        const plug2 = item.querySelector('.outlet-plug2')?.value;
        const plug1Switch = item.querySelector('.outlet-plug1-switch')?.value;
        const plug2Switch = item.querySelector('.outlet-plug2-switch')?.value;
        const outletThreshold = parseInt(item.querySelector('.outlet-threshold')?.value) || 0;
        const plug1Shutoff = parseInt(item.querySelector('.outlet-plug1-shutoff')?.value) || 0;
        const plug2Shutoff = parseInt(item.querySelector('.outlet-plug2-shutoff')?.value) || 0;

        if (outletName) {
          outlets.push({
            name: outletName,
            plug1_entity: plug1 || null,
            plug2_entity: plug2 || null,
            plug1_switch: plug1Switch || null,
            plug2_switch: plug2Switch || null,
            threshold: outletThreshold,
            plug1_shutoff: plug1Shutoff,
            plug2_shutoff: plug2Shutoff,
          });
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

    const config = {
      rooms: rooms,
      tts_settings: {
        language: ttsLanguage,
        speed: 1.0,
        prefix: ttsPrefix,
        room_warn_msg: ttsRoomWarn,
        outlet_warn_msg: ttsOutletWarn,
        shutoff_msg: ttsShutoff,
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
