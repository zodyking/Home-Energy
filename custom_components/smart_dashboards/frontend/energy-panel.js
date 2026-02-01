/**
 * Energy Panel for Smart Dashboards
 * Room-based power monitoring with automatic TTS threshold alerts
 */

import { sharedStyles, icons, showToast } from './shared-utils.js';

class EnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._powerData = null;
    this._showSettings = false;
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
      const [config, entities] = await Promise.all([
        this._hass.callWS({ type: 'smart_dashboards/get_config' }),
        this._hass.callWS({ type: 'smart_dashboards/get_entities' }),
      ]);
      this._config = config.energy || {};
      this._entities = entities;
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

      .room-card {
        background: var(--card-bg);
        border-radius: 10px;
        border: 1px solid var(--card-border);
        margin-bottom: 10px;
        overflow: hidden;
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
      }

      .room-meta {
        font-size: 10px;
        color: var(--secondary-text-color);
        display: flex;
        align-items: center;
        gap: 8px;
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
      }

      .room-content {
        padding: 10px 14px;
      }

      .outlets-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
        gap: 8px;
      }

      .outlet-card {
        background: rgba(0, 0, 0, 0.3);
        border-radius: 12px;
        padding: 8px;
        border: 2px solid rgba(255, 255, 255, 0.08);
        position: relative;
      }

      .outlet-header {
        text-align: center;
        margin-bottom: 6px;
        padding-bottom: 4px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }

      .outlet-name {
        font-size: 10px;
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
        font-size: 12px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
        margin-top: 2px;
      }

      .outlet-total.over-threshold {
        color: var(--panel-danger);
      }

      .plugs-container {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .plug-card {
        background: #1a1a1a;
        border-radius: 8px;
        padding: 6px 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }

      .plug-card::before {
        content: '';
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: rgba(3, 169, 244, 0.3);
        border: 1px solid rgba(3, 169, 244, 0.5);
        flex-shrink: 0;
      }

      .plug-card.active::before {
        background: var(--panel-accent);
        box-shadow: 0 0 6px var(--panel-accent);
      }

      .plug-label {
        font-size: 8px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        color: var(--secondary-text-color);
        flex: 1;
        margin-left: 6px;
      }

      .plug-watts {
        font-size: 11px;
        font-weight: 600;
        color: var(--primary-text-color);
        font-variant-numeric: tabular-nums;
      }

      .threshold-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: 8px;
        color: var(--secondary-text-color);
        padding: 2px 5px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 3px;
      }

      .threshold-badge svg {
        width: 8px;
        height: 8px;
        fill: currentColor;
      }

      .outlet-threshold {
        text-align: center;
        margin-top: 4px;
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
        font-size: 16px;
        font-weight: 500;
        max-width: 200px;
      }

      .room-settings-body {
        padding: 20px;
      }

      .outlet-settings-item {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr 100px auto;
        gap: 12px;
        align-items: end;
        padding: 12px;
        background: var(--input-bg);
        border-radius: 8px;
        margin-bottom: 8px;
      }

      @media (max-width: 900px) {
        .outlet-settings-item {
          grid-template-columns: 1fr 1fr;
        }
      }

      .outlet-settings-item .form-group {
        margin: 0;
      }

      .outlet-settings-item .form-label {
        font-size: 10px;
        margin-bottom: 4px;
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
          
          ${rooms.map((room) => this._renderRoomCard(room)).join('')}
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
        ${outlet.threshold > 0 ? `
          <div class="outlet-threshold">
            <span class="threshold-badge">${outlet.threshold}W</span>
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderSettings(styles) {
    const rooms = this._config?.rooms || [];
    const mediaPlayers = this._entities?.media_players || [];
    const powerSensors = this._entities?.power_sensors || [];
    const ttsSettings = this._config?.tts_settings || {};

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
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

          <div class="card">
            <div class="card-header">
              <h2 class="card-title">TTS Alert Settings</h2>
            </div>
            <p style="color: var(--secondary-text-color); font-size: 11px; margin-bottom: 12px;">
              Alerts play automatically when thresholds are exceeded. Volume is set per room above.
            </p>
            <div class="form-group" style="max-width: 200px;">
              <label class="form-label">Language</label>
              <select class="form-select" id="tts-language">
                <option value="en" ${ttsSettings.language === 'en' ? 'selected' : ''}>English</option>
                <option value="es" ${ttsSettings.language === 'es' ? 'selected' : ''}>Spanish</option>
                <option value="fr" ${ttsSettings.language === 'fr' ? 'selected' : ''}>French</option>
                <option value="de" ${ttsSettings.language === 'de' ? 'selected' : ''}>German</option>
              </select>
            </div>
          </div>
        </div>
      </div>
    `;

    this._attachSettingsEventListeners();
  }

  _renderRoomSettings(room, index, mediaPlayers, powerSensors) {
    return `
      <div class="room-settings-card" data-room-index="${index}">
        <div class="room-settings-header">
          <input type="text" class="form-input room-name-input" value="${room.name}" placeholder="Room name">
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary toggle-room-btn" data-index="${index}">Edit</button>
            <button class="icon-btn danger remove-room-btn" data-index="${index}">
              <svg viewBox="0 0 24 24">${icons.delete}</svg>
            </button>
          </div>
        </div>

        <div class="room-settings-body" id="room-body-${index}" style="display: none;">
          <div class="grid-2" style="margin-bottom: 12px;">
            <div class="form-group">
              <label class="form-label">Media Player (for alerts)</label>
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
              <input type="number" class="form-input room-threshold" value="${room.threshold || ''}" placeholder="0 = disabled" min="0">
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 16px;">
            <label class="form-label">TTS Alert Volume</label>
            <div class="volume-control">
              <input type="range" class="volume-slider room-volume" min="0" max="1" step="0.05" value="${room.volume || 0.7}" data-index="${index}">
              <span class="volume-value room-volume-display">${Math.round((room.volume || 0.7) * 100)}%</span>
            </div>
          </div>

          <div class="divider"></div>

          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
            <h4 style="margin: 0; font-size: 12px; color: var(--secondary-text-color);">Outlets</h4>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-secondary load-room-outlets-btn" data-room-index="${index}" data-room-name="${room.name}">
                <svg class="btn-icon" viewBox="0 0 24 24">${icons.room}</svg>
                Load from HA Room
              </button>
              <button class="btn btn-secondary add-outlet-btn" data-room-index="${index}">
                <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
                Add Outlet
              </button>
            </div>
          </div>

          <div class="outlets-settings-list" id="outlets-list-${index}">
            ${(room.outlets || []).map((outlet, oi) => this._renderOutletSettings(outlet, oi, powerSensors)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletSettings(outlet, outletIndex, powerSensors) {
    return `
      <div class="outlet-settings-item" data-outlet-index="${outletIndex}">
        <div class="form-group">
          <label class="form-label">Outlet Name</label>
          <input type="text" class="form-input outlet-name" value="${outlet.name || ''}" placeholder="Name">
        </div>
        <div class="form-group">
          <label class="form-label">Plug 1 Entity</label>
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
          <label class="form-label">Plug 2 Entity</label>
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
          <label class="form-label">Threshold (W)</label>
          <input type="number" class="form-input outlet-threshold" value="${outlet.threshold || ''}" placeholder="0" min="0">
        </div>
        <button class="icon-btn danger remove-outlet-btn" data-outlet-index="${outletIndex}">
          <svg viewBox="0 0 24 24">${icons.delete}</svg>
        </button>
      </div>
    `;
  }

  _attachEventListeners() {
    // Menu button to toggle HA sidebar
    this._attachMenuButton();

    const settingsBtn = this.shadowRoot.querySelector('#settings-btn');
    const emptySettingsBtn = this.shadowRoot.querySelector('#empty-settings-btn');

    if (settingsBtn) {
      settingsBtn.addEventListener('click', () => {
        this._showSettings = true;
        this._stopRefresh();
        this._render();
      });
    }

    if (emptySettingsBtn) {
      emptySettingsBtn.addEventListener('click', () => {
        this._showSettings = true;
        this._stopRefresh();
        this._render();
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
    const ttsVolume = this.shadowRoot.querySelector('#tts-volume');
    const ttsVolumeDisplay = this.shadowRoot.querySelector('#tts-volume-display');

    if (backBtn) {
      backBtn.addEventListener('click', () => {
        this._showSettings = false;
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

    if (ttsVolume && ttsVolumeDisplay) {
      ttsVolume.addEventListener('input', () => {
        ttsVolumeDisplay.textContent = Math.round(parseFloat(ttsVolume.value) * 100) + '%';
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

    // Add outlet buttons
    this.shadowRoot.querySelectorAll('.add-outlet-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const roomIndex = btn.dataset.roomIndex;
        this._addOutlet(roomIndex);
      });
    });

    // Load from HA Room buttons
    this.shadowRoot.querySelectorAll('.load-room-outlets-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const roomIndex = btn.dataset.roomIndex;
        const roomName = btn.dataset.roomName;
        this._loadOutletsFromRoom(roomIndex, roomName);
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

    // Remove outlet buttons
    this.shadowRoot.querySelectorAll('.remove-outlet-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.outlet-settings-item');
        if (item) item.remove();
      });
    });
  }

  async _loadOutletsFromRoom(roomIndex, roomName) {
    if (!this._hass) return;

    const btn = this.shadowRoot.querySelector(`.load-room-outlets-btn[data-room-index="${roomIndex}"]`);
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span>Loading...</span>';
    }

    try {
      const result = await this._hass.callWS({
        type: 'smart_dashboards/get_entities_by_area',
        area_id: roomName,
      });

      if (!result.area_found) {
        showToast(this.shadowRoot, `Room "${roomName}" not found in Home Assistant`, 'error');
        return;
      }

      const outlets = result.outlets || [];
      if (outlets.length === 0) {
        showToast(this.shadowRoot, `No power sensors found in "${result.area_name}"`, 'error');
        return;
      }

      // Group sensors into outlet pairs (plug1/plug2)
      const outletPairs = this._groupSensorsIntoOutlets(outlets);
      
      // Add outlets to the list
      const list = this.shadowRoot.querySelector(`#outlets-list-${roomIndex}`);
      const powerSensors = this._entities?.power_sensors || [];

      outletPairs.forEach(pair => {
        const outletIndex = list.querySelectorAll('.outlet-settings-item').length;
        const html = this._renderOutletSettings(pair, outletIndex, powerSensors);
        list.insertAdjacentHTML('beforeend', html);

        // Attach remove listener
        const newItem = list.querySelector(`.outlet-settings-item[data-outlet-index="${outletIndex}"]`);
        const removeBtn = newItem.querySelector('.remove-outlet-btn');
        removeBtn.addEventListener('click', () => newItem.remove());
      });

      showToast(this.shadowRoot, `Loaded ${outletPairs.length} outlets from "${result.area_name}"`, 'success');

    } catch (e) {
      console.error('Failed to load outlets:', e);
      showToast(this.shadowRoot, 'Failed to load outlets from room', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg class="btn-icon" viewBox="0 0 24 24">${icons.room}</svg> Load from HA Room`;
      }
    }
  }

  _groupSensorsIntoOutlets(sensors) {
    // Try to group sensors by common name patterns (e.g., "Outlet 1 Plug 1", "Outlet 1 Plug 2")
    const outlets = [];
    const used = new Set();

    for (const sensor of sensors) {
      if (used.has(sensor.entity_id)) continue;

      const name = sensor.friendly_name.toLowerCase();
      
      // Look for a matching pair
      let plug1 = null;
      let plug2 = null;
      let outletName = sensor.friendly_name;

      // Check if this is a "plug 1" or "plug 2" style sensor
      if (name.includes('plug 1') || name.includes('plug1') || name.includes('outlet 1')) {
        plug1 = sensor.entity_id;
        outletName = sensor.friendly_name.replace(/plug\s*1/i, '').replace(/outlet\s*1/i, '').trim();
        
        // Find matching plug 2
        for (const other of sensors) {
          if (used.has(other.entity_id)) continue;
          const otherName = other.friendly_name.toLowerCase();
          if ((otherName.includes('plug 2') || otherName.includes('plug2') || otherName.includes('outlet 2')) &&
              other.friendly_name.replace(/plug\s*2/i, '').replace(/outlet\s*2/i, '').trim().toLowerCase() === outletName.toLowerCase()) {
            plug2 = other.entity_id;
            used.add(other.entity_id);
            break;
          }
        }
      } else if (name.includes('plug 2') || name.includes('plug2') || name.includes('outlet 2')) {
        plug2 = sensor.entity_id;
        outletName = sensor.friendly_name.replace(/plug\s*2/i, '').replace(/outlet\s*2/i, '').trim();
        
        // Find matching plug 1
        for (const other of sensors) {
          if (used.has(other.entity_id)) continue;
          const otherName = other.friendly_name.toLowerCase();
          if ((otherName.includes('plug 1') || otherName.includes('plug1') || otherName.includes('outlet 1')) &&
              other.friendly_name.replace(/plug\s*1/i, '').replace(/outlet\s*1/i, '').trim().toLowerCase() === outletName.toLowerCase()) {
            plug1 = other.entity_id;
            used.add(other.entity_id);
            break;
          }
        }
      } else {
        // Single sensor, put in plug1
        plug1 = sensor.entity_id;
        outletName = sensor.friendly_name;
      }

      used.add(sensor.entity_id);
      
      // Clean up outlet name
      outletName = outletName.replace(/current consumption/i, '').replace(/power/i, '').trim();
      if (!outletName) outletName = 'Outlet';

      outlets.push({
        name: outletName,
        plug1_entity: plug1,
        plug2_entity: plug2,
        threshold: 0,
      });
    }

    return outlets;
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

    const loadOutletsBtn = newCard.querySelector('.load-room-outlets-btn');
    loadOutletsBtn.addEventListener('click', () => {
      this._loadOutletsFromRoom(index, newRoom.name);
    });

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
    const powerSensors = this._entities?.power_sensors || [];
    const list = this.shadowRoot.querySelector(`#outlets-list-${roomIndex}`);
    
    const outletIndex = list.querySelectorAll('.outlet-settings-item').length;
    const html = this._renderOutletSettings({ name: '', plug1_entity: '', plug2_entity: '', threshold: 0 }, outletIndex, powerSensors);
    
    list.insertAdjacentHTML('beforeend', html);

    const newItem = list.querySelector(`.outlet-settings-item[data-outlet-index="${outletIndex}"]`);
    const removeBtn = newItem.querySelector('.remove-outlet-btn');
    removeBtn.addEventListener('click', () => newItem.remove());
  }

  async _saveSettings() {
    const roomCards = this.shadowRoot.querySelectorAll('.room-settings-card');
    const rooms = [];

    roomCards.forEach((card) => {
      const nameInput = card.querySelector('.room-name-input');
      const mediaPlayerSelect = card.querySelector('.room-media-player');
      const thresholdInput = card.querySelector('.room-threshold');
      const volumeSlider = card.querySelector('.room-volume');
      const outletItems = card.querySelectorAll('.outlet-settings-item');

      const outlets = [];
      outletItems.forEach(item => {
        const outletName = item.querySelector('.outlet-name')?.value;
        const plug1 = item.querySelector('.outlet-plug1')?.value;
        const plug2 = item.querySelector('.outlet-plug2')?.value;
        const outletThreshold = parseInt(item.querySelector('.outlet-threshold')?.value) || 0;

        if (outletName) {
          outlets.push({
            name: outletName,
            plug1_entity: plug1 || null,
            plug2_entity: plug2 || null,
            threshold: outletThreshold,
          });
        }
      });

      const roomName = nameInput?.value?.trim();
      if (roomName) {
        rooms.push({
          id: roomName.toLowerCase().replace(/\s+/g, '_').replace(/'/g, ''),
          name: roomName,
          media_player: mediaPlayerSelect?.value || null,
          threshold: parseInt(thresholdInput?.value) || 0,
          volume: parseFloat(volumeSlider?.value) || 0.7,
          outlets: outlets,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';

    const config = {
      rooms: rooms,
      tts_settings: {
        language: ttsLanguage,
        speed: 1.0,
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
