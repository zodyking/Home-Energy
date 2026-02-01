/**
 * Energy Panel for Smart Dashboards
 * Room-based power monitoring with TTS threshold alerts
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
    this._editingRoom = null;
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
    
    rooms.forEach(room => {
      const roomCard = this.shadowRoot.querySelector(`.room-card[data-room-id="${room.id}"]`);
      if (!roomCard) return;

      // Update room totals
      const totalWatts = roomCard.querySelector('.room-total-watts');
      const totalDay = roomCard.querySelector('.room-total-day');
      const threshold = this._getRoomThreshold(room.id);
      
      if (totalWatts) {
        totalWatts.textContent = `${room.total_watts.toFixed(1)} W`;
        totalWatts.classList.toggle('over-threshold', room.total_watts > threshold);
      }
      if (totalDay) {
        const kwh = (room.total_day_wh / 1000).toFixed(2);
        totalDay.textContent = `${kwh} kWh today`;
      }

      // Update individual outlets
      room.outlets.forEach((outlet, i) => {
        const outletCard = roomCard.querySelector(`.outlet-card[data-outlet-index="${i}"]`);
        if (!outletCard) return;

        const plug1Watts = outletCard.querySelector('.plug1-watts');
        const plug1Day = outletCard.querySelector('.plug1-day');
        const plug2Watts = outletCard.querySelector('.plug2-watts');
        const plug2Day = outletCard.querySelector('.plug2-day');

        if (plug1Watts) plug1Watts.textContent = `${outlet.plug1.watts.toFixed(1)} W`;
        if (plug1Day) plug1Day.textContent = `${outlet.plug1.day_wh.toFixed(2)} Wh`;
        if (plug2Watts) plug2Watts.textContent = `${outlet.plug2.watts.toFixed(1)} W`;
        if (plug2Day) plug2Day.textContent = `${outlet.plug2.day_wh.toFixed(2)} Wh`;
      });
    });
  }

  _getRoomThreshold(roomId) {
    const rooms = this._config?.rooms || [];
    const room = rooms.find(r => r.id === roomId);
    return room?.threshold || 1000;
  }

  _render() {
    const styles = `
      ${sharedStyles}
      
      .room-card {
        background: var(--card-bg);
        border-radius: 16px;
        border: 1px solid var(--card-border);
        margin-bottom: 20px;
        overflow: hidden;
      }

      .room-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        background: linear-gradient(135deg, rgba(0, 212, 170, 0.08) 0%, transparent 100%);
        border-bottom: 1px solid var(--card-border);
        cursor: pointer;
      }

      .room-header:hover {
        background: linear-gradient(135deg, rgba(0, 212, 170, 0.12) 0%, transparent 100%);
      }

      .room-info {
        display: flex;
        align-items: center;
        gap: 16px;
      }

      .room-icon {
        width: 40px;
        height: 40px;
        border-radius: 10px;
        background: var(--panel-accent-dim);
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .room-icon svg {
        width: 22px;
        height: 22px;
        fill: var(--panel-accent);
      }

      .room-name {
        font-size: 16px;
        font-weight: 500;
        margin: 0 0 4px;
      }

      .room-meta {
        font-size: 13px;
        color: var(--secondary-text-color);
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .room-stats {
        text-align: right;
      }

      .room-total-watts {
        font-size: 24px;
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
        font-size: 13px;
        color: var(--secondary-text-color);
        margin-top: 4px;
        font-variant-numeric: tabular-nums;
      }

      .room-content {
        padding: 20px;
      }

      .outlets-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 16px;
      }

      .outlet-card {
        background: var(--input-bg);
        border-radius: 12px;
        padding: 16px;
        border: 1px solid var(--input-border);
      }

      .outlet-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
      }

      .outlet-name {
        font-size: 14px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .outlet-name svg {
        width: 18px;
        height: 18px;
        fill: var(--panel-accent);
      }

      .plugs-container {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }

      .plug-card {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 8px;
        padding: 12px;
        text-align: center;
      }

      .plug-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
        margin-bottom: 8px;
      }

      .plug-watts {
        font-size: 20px;
        font-weight: 600;
        color: var(--primary-text-color);
        font-variant-numeric: tabular-nums;
      }

      .plug-day {
        font-size: 11px;
        color: var(--secondary-text-color);
        margin-top: 4px;
        font-variant-numeric: tabular-nums;
      }

      .threshold-indicator {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .threshold-indicator svg {
        width: 14px;
        height: 14px;
        fill: currentColor;
      }

      .threshold-indicator.warning {
        color: var(--panel-warning);
      }

      .room-tts-bar {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px 20px;
        background: rgba(0, 0, 0, 0.2);
        border-top: 1px solid var(--card-border);
      }

      .room-tts-label {
        font-size: 12px;
        color: var(--secondary-text-color);
        flex-shrink: 0;
      }

      .room-tts-input {
        flex: 1;
        padding: 10px 16px;
        border-radius: 24px;
        border: 1px solid var(--input-border);
        background: var(--input-bg);
        color: var(--primary-text-color);
        font-size: 14px;
        font-family: inherit;
      }

      .room-tts-input:focus {
        outline: none;
        border-color: var(--panel-accent);
      }

      .room-tts-btn {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--panel-accent);
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: transform 0.2s;
      }

      .room-tts-btn:hover {
        transform: scale(1.08);
      }

      .room-tts-btn svg {
        width: 18px;
        height: 18px;
        fill: #000;
      }

      .room-volume {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 100px;
      }

      .room-volume input {
        width: 70px;
        height: 4px;
        -webkit-appearance: none;
        appearance: none;
        background: rgba(255,255,255,0.15);
        border-radius: 2px;
      }

      .room-volume input::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--panel-accent);
        cursor: pointer;
      }

      .room-volume svg {
        width: 16px;
        height: 16px;
        fill: var(--secondary-text-color);
      }

      /* Settings Styles */
      .room-settings-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        padding: 16px;
        margin-bottom: 12px;
      }

      .room-settings-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
      }

      .room-settings-name {
        font-size: 16px;
        font-weight: 500;
      }

      .outlet-settings-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: var(--input-bg);
        border-radius: 8px;
        margin-bottom: 8px;
      }

      .outlet-settings-item .form-group {
        flex: 1;
        margin: 0;
      }

      .outlet-settings-item .form-label {
        font-size: 11px;
        margin-bottom: 4px;
      }

      .divider {
        height: 1px;
        background: var(--card-border);
        margin: 16px 0;
      }

      .summary-stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
      }

      .stat-card {
        background: var(--card-bg);
        border-radius: 12px;
        border: 1px solid var(--card-border);
        padding: 20px;
        text-align: center;
      }

      .stat-value {
        font-size: 32px;
        font-weight: 600;
        color: var(--panel-accent);
        font-variant-numeric: tabular-nums;
      }

      .stat-label {
        font-size: 13px;
        color: var(--secondary-text-color);
        margin-top: 4px;
      }
    `;

    if (this._loading) {
      this.shadowRoot.innerHTML = `
        <style>${styles}</style>
        <div class="panel-container">
          <div class="panel-header">
            <h1 class="panel-title">
              <svg class="panel-title-icon" viewBox="0 0 24 24">
                <path d="M7,2v11h3v9l7-12h-4l4-8z"/>
              </svg>
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
            <h1 class="panel-title">
              <svg class="panel-title-icon" viewBox="0 0 24 24">
                <path d="M7,2v11h3v9l7-12h-4l4-8z"/>
              </svg>
              Home Energy
            </h1>
          </div>
          <div class="content-area">
            <div class="empty-state">
              <svg class="empty-state-icon" viewBox="0 0 24 24" style="fill: var(--panel-danger);">
                <path d="M1,21h22L12,2L1,21z M13,18h-2v-2h2V18z M13,14h-2v-4h2V14z"/>
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
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">
              <path d="M7,2v11h3v9l7-12h-4l4-8z"/>
            </svg>
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
                <div class="stat-value">${totalWatts.toFixed(1)} W</div>
                <div class="stat-label">Current Power</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">${(totalDayWh / 1000).toFixed(2)} kWh</div>
                <div class="stat-label">Today's Usage</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">${rooms.length}</div>
                <div class="stat-label">Monitored Rooms</div>
              </div>
            </div>
          ` : ''}

          ${rooms.length === 0 ? this._renderEmptyState() : ''}
          
          ${rooms.map((room, i) => this._renderRoomCard(room, i)).join('')}
        </div>
      </div>
    `;

    this._attachEventListeners();
  }

  _renderEmptyState() {
    return `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24">
          <path d="M7,2v11h3v9l7-12h-4l4-8z"/>
        </svg>
        <h3 class="empty-state-title">No Rooms Configured</h3>
        <p class="empty-state-desc">Set up rooms and outlets to monitor power usage.</p>
        <button class="btn btn-primary" id="empty-settings-btn">
          <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
          Open Settings
        </button>
      </div>
    `;
  }

  _renderRoomCard(room, index) {
    const roomData = this._powerData?.rooms?.find(r => r.id === room.id) || {
      total_watts: 0,
      total_day_wh: 0,
      outlets: [],
    };

    const isOverThreshold = roomData.total_watts > room.threshold;

    return `
      <div class="room-card" data-room-id="${room.id}">
        <div class="room-header">
          <div class="room-info">
            <div class="room-icon">
              <svg viewBox="0 0 24 24"><path d="M12,3L2,12h3v8h14v-8h3L12,3z M12,16c-1.1,0-2-0.9-2-2c0-1.1,0.9-2,2-2s2,0.9,2,2C14,15.1,13.1,16,12,16z"/></svg>
            </div>
            <div>
              <h3 class="room-name">${room.name}</h3>
              <div class="room-meta">
                <span>${room.outlets?.length || 0} outlets</span>
                <span class="threshold-indicator ${isOverThreshold ? 'warning' : ''}">
                  <svg viewBox="0 0 24 24"><path d="M1,21h22L12,2L1,21z M13,18h-2v-2h2V18z M13,14h-2v-4h2V14z"/></svg>
                  Threshold: ${room.threshold}W
                </span>
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

        ${room.media_player ? `
          <div class="room-tts-bar">
            <span class="room-tts-label">TTS:</span>
            <input type="text" class="room-tts-input" placeholder="Type a message..." data-media-player="${room.media_player}">
            <button class="room-tts-btn" data-media-player="${room.media_player}">
              <svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z M14,3.23v2.06c2.89,0.86,5,3.54,5,6.71s-2.11,5.85-5,6.71v2.06c4.01-0.91,7-4.49,7-8.77S18.01,4.14,14,3.23z"/></svg>
            </button>
            <div class="room-volume">
              <svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z"/></svg>
              <input type="range" min="0" max="1" step="0.05" value="0.7" data-media-player="${room.media_player}">
            </div>
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderOutletCard(outlet, index, outletData) {
    const data = outletData || { plug1: { watts: 0, day_wh: 0 }, plug2: { watts: 0, day_wh: 0 } };

    return `
      <div class="outlet-card" data-outlet-index="${index}">
        <div class="outlet-header">
          <div class="outlet-name">
            <svg viewBox="0 0 24 24"><path d="M12,2C6.48,2,2,6.48,2,12s4.48,10,10,10s10-4.48,10-10S17.52,2,12,2z M12,20c-4.41,0-8-3.59-8-8s3.59-8,8-8s8,3.59,8,8 S16.41,20,12,20z M11,7h2v6h-2V7z M11,15h2v2h-2V15z"/></svg>
            ${outlet.name}
          </div>
        </div>
        <div class="plugs-container">
          <div class="plug-card">
            <div class="plug-label">Plug 1</div>
            <div class="plug-watts plug1-watts">${data.plug1.watts.toFixed(1)} W</div>
            <div class="plug-day plug1-day">${data.plug1.day_wh.toFixed(2)} Wh</div>
          </div>
          <div class="plug-card">
            <div class="plug-label">Plug 2</div>
            <div class="plug-watts plug2-watts">${data.plug2.watts.toFixed(1)} W</div>
            <div class="plug-day plug2-day">${data.plug2.day_wh.toFixed(2)} Wh</div>
          </div>
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
      <style>${styles}</style>
      <div class="panel-container">
        <div class="panel-header">
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.settings}</svg>
            Energy Settings
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="back-btn">
              Back to Dashboard
            </button>
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
                  No rooms configured yet. Add a room to start monitoring power usage.
                </p>
              ` : rooms.map((room, i) => this._renderRoomSettings(room, i, mediaPlayers, powerSensors)).join('')}
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <h2 class="card-title">TTS Alert Settings</h2>
            </div>
            <div class="grid-2">
              <div class="form-group">
                <label class="form-label">Language</label>
                <select class="form-select" id="tts-language">
                  <option value="en" ${ttsSettings.language === 'en' ? 'selected' : ''}>English</option>
                  <option value="es" ${ttsSettings.language === 'es' ? 'selected' : ''}>Spanish</option>
                  <option value="fr" ${ttsSettings.language === 'fr' ? 'selected' : ''}>French</option>
                  <option value="de" ${ttsSettings.language === 'de' ? 'selected' : ''}>German</option>
                  <option value="it" ${ttsSettings.language === 'it' ? 'selected' : ''}>Italian</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Alert Volume</label>
                <div class="volume-control">
                  <input type="range" class="volume-slider" id="tts-volume" min="0" max="1" step="0.05" value="${ttsSettings.volume || 0.7}">
                  <span class="volume-value" id="tts-volume-display">${Math.round((ttsSettings.volume || 0.7) * 100)}%</span>
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
    return `
      <div class="room-settings-card" data-room-index="${index}">
        <div class="room-settings-header">
          <input type="text" class="form-input room-name-input" value="${room.name}" placeholder="Room name" style="max-width: 200px;">
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary btn-sm toggle-room-details" data-index="${index}">
              Edit
            </button>
            <button class="btn btn-danger btn-sm remove-room-btn" data-index="${index}">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.delete}</svg>
            </button>
          </div>
        </div>

        <div class="room-details" id="room-details-${index}" style="display: none;">
          <div class="grid-2" style="margin-bottom: 16px;">
            <div class="form-group">
              <label class="form-label">Media Player (for alerts)</label>
              <select class="form-select room-media-player" data-index="${index}">
                <option value="">None</option>
                ${mediaPlayers.map(mp => `
                  <option value="${mp.entity_id}" ${room.media_player === mp.entity_id ? 'selected' : ''}>
                    ${mp.friendly_name}
                  </option>
                `).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Power Threshold (Watts)</label>
              <input type="number" class="form-input room-threshold" value="${room.threshold || 1000}" min="0" data-index="${index}">
            </div>
          </div>

          <div class="divider"></div>

          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
            <h4 style="margin: 0; font-size: 14px; color: var(--secondary-text-color);">Outlets</h4>
            <button class="btn btn-secondary btn-sm add-outlet-btn" data-room-index="${index}">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
              Add Outlet
            </button>
          </div>

          <div class="outlets-settings-list" id="outlets-list-${index}">
            ${(room.outlets || []).map((outlet, oi) => this._renderOutletSettings(outlet, oi, index, powerSensors)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderOutletSettings(outlet, outletIndex, roomIndex, powerSensors) {
    return `
      <div class="outlet-settings-item" data-outlet-index="${outletIndex}">
        <div class="form-group" style="flex: 0.8;">
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
        <button class="icon-btn danger remove-outlet-btn" data-room-index="${roomIndex}" data-outlet-index="${outletIndex}" style="margin-top: 18px;">
          <svg viewBox="0 0 24 24">${icons.delete}</svg>
        </button>
      </div>
    `;
  }

  _attachEventListeners() {
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

    // TTS buttons in room cards
    this.shadowRoot.querySelectorAll('.room-tts-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const mediaPlayer = btn.dataset.mediaPlayer;
        const input = btn.previousElementSibling;
        this._sendTTS(input, mediaPlayer);
      });
    });

    // TTS input enter key
    this.shadowRoot.querySelectorAll('.room-tts-input').forEach(input => {
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          const mediaPlayer = input.dataset.mediaPlayer;
          this._sendTTS(input, mediaPlayer);
        }
      });
    });

    // Volume sliders
    this.shadowRoot.querySelectorAll('.room-volume input').forEach(slider => {
      slider.addEventListener('input', (e) => {
        this._setVolume(e.target.dataset.mediaPlayer, parseFloat(e.target.value));
      });
    });
  }

  _attachSettingsEventListeners() {
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
    this.shadowRoot.querySelectorAll('.toggle-room-details').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = btn.dataset.index;
        const details = this.shadowRoot.querySelector(`#room-details-${index}`);
        if (details) {
          const isVisible = details.style.display !== 'none';
          details.style.display = isVisible ? 'none' : 'block';
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

    // Remove outlet buttons
    this.shadowRoot.querySelectorAll('.remove-outlet-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = btn.closest('.outlet-settings-item');
        if (item) item.remove();
      });
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
      threshold: 1000,
      outlets: [],
    };
    
    const html = this._renderRoomSettings(newRoom, index, mediaPlayers, powerSensors);
    list.insertAdjacentHTML('beforeend', html);

    // Attach event listeners for the new room
    const newCard = list.querySelector(`.room-settings-card[data-room-index="${index}"]`);
    
    const toggleBtn = newCard.querySelector('.toggle-room-details');
    toggleBtn.addEventListener('click', () => {
      const details = newCard.querySelector(`#room-details-${index}`);
      if (details) {
        const isVisible = details.style.display !== 'none';
        details.style.display = isVisible ? 'none' : 'block';
        toggleBtn.textContent = isVisible ? 'Edit' : 'Collapse';
      }
    });

    const removeBtn = newCard.querySelector('.remove-room-btn');
    removeBtn.addEventListener('click', () => newCard.remove());

    const addOutletBtn = newCard.querySelector('.add-outlet-btn');
    addOutletBtn.addEventListener('click', () => this._addOutlet(index));

    // Auto-expand the new room
    toggleBtn.click();
  }

  _addOutlet(roomIndex) {
    const powerSensors = this._entities?.power_sensors || [];
    const list = this.shadowRoot.querySelector(`#outlets-list-${roomIndex}`);
    
    const outletIndex = list.querySelectorAll('.outlet-settings-item').length;
    const html = this._renderOutletSettings({ name: '', plug1_entity: '', plug2_entity: '' }, outletIndex, roomIndex, powerSensors);
    
    list.insertAdjacentHTML('beforeend', html);

    // Attach remove listener
    const newItem = list.querySelector(`.outlet-settings-item[data-outlet-index="${outletIndex}"]`);
    const removeBtn = newItem.querySelector('.remove-outlet-btn');
    removeBtn.addEventListener('click', () => newItem.remove());
  }

  async _sendTTS(input, mediaPlayer) {
    if (!input || !mediaPlayer || !this._hass) return;

    const message = input.value.trim();
    if (!message) return;

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/send_tts',
        media_player: mediaPlayer,
        message: message,
        language: this._config?.tts_settings?.language || 'en',
      });
      
      input.value = '';
      showToast(this.shadowRoot, 'Message sent!');
    } catch (e) {
      console.error('TTS failed:', e);
      showToast(this.shadowRoot, 'Failed to send message', true);
    }
  }

  async _setVolume(mediaPlayer, volume) {
    if (!mediaPlayer || !this._hass) return;

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/set_volume',
        media_player: mediaPlayer,
        volume: volume,
      });
    } catch (e) {
      console.error('Failed to set volume:', e);
    }
  }

  async _saveSettings() {
    const roomCards = this.shadowRoot.querySelectorAll('.room-settings-card');
    const rooms = [];

    roomCards.forEach((card, index) => {
      const nameInput = card.querySelector('.room-name-input');
      const mediaPlayerSelect = card.querySelector('.room-media-player');
      const thresholdInput = card.querySelector('.room-threshold');
      const outletItems = card.querySelectorAll('.outlet-settings-item');

      const outlets = [];
      outletItems.forEach(item => {
        const outletName = item.querySelector('.outlet-name')?.value;
        const plug1 = item.querySelector('.outlet-plug1')?.value;
        const plug2 = item.querySelector('.outlet-plug2')?.value;

        if (outletName) {
          outlets.push({
            name: outletName,
            plug1_entity: plug1 || null,
            plug2_entity: plug2 || null,
          });
        }
      });

      const roomName = nameInput?.value?.trim();
      if (roomName) {
        rooms.push({
          id: roomName.toLowerCase().replace(/\s+/g, '_'),
          name: roomName,
          media_player: mediaPlayerSelect?.value || null,
          threshold: parseInt(thresholdInput?.value) || 1000,
          outlets: outlets,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';
    const ttsVolume = parseFloat(this.shadowRoot.querySelector('#tts-volume')?.value || 0.7);

    const config = {
      rooms: rooms,
      tts_settings: {
        language: ttsLanguage,
        speed: 1.0,
        volume: ttsVolume,
      },
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_energy',
        config: config,
      });

      this._config = config;
      showToast(this.shadowRoot, 'Settings saved!');
      
      // Go back to main view
      setTimeout(() => {
        this._showSettings = false;
        this._render();
        this._startRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', true);
    }
  }
}

customElements.define('energy-panel', EnergyPanel);
