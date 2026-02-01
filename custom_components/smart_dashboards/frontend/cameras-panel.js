/**
 * Cameras Panel for Smart Dashboards
 * Live camera feeds with TTS integration
 */

import { sharedStyles, icons, showToast } from './shared-utils.js';

class CamerasPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._showSettings = false;
    this._hlsInstances = new Map();
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
    this._cleanup();
  }

  _cleanup() {
    // Clean up HLS instances
    this._hlsInstances.forEach((hls) => {
      if (hls && hls.destroy) {
        hls.destroy();
      }
    });
    this._hlsInstances.clear();

    // Clear refresh interval
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
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
      this._config = config.cameras || {};
      this._entities = entities;
      this._loading = false;
      this._render();
      this._setupStreams();
    } catch (e) {
      console.error('Failed to load cameras config:', e);
      this._loading = false;
      this._error = e.message || 'Failed to load configuration';
      this._render();
    }
  }

  _renderLoading() {
    return `
      <div class="loading">
        <div class="loading-spinner"></div>
        <span>Loading cameras...</span>
      </div>
    `;
  }

  _renderError(message) {
    return `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" style="fill: var(--panel-danger);">
          <path d="M1,21h22L12,2L1,21z M13,18h-2v-2h2V18z M13,14h-2v-4h2V14z"/>
        </svg>
        <h3 class="empty-state-title">Error Loading Cameras</h3>
        <p class="empty-state-desc">${message}</p>
        <button class="btn btn-primary" id="retry-btn">
          Retry
        </button>
      </div>
    `;
  }

  _render() {
    const styles = `
      ${sharedStyles}
      
      .main-camera-container {
        position: relative;
        width: 100%;
        max-width: 1200px;
        margin: 0 auto 24px;
        border-radius: 16px;
        overflow: hidden;
        background: #000;
        aspect-ratio: 16/9;
      }

      .main-camera-container video,
      .main-camera-container img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        display: block;
      }

      .camera-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 16px 20px;
        background: linear-gradient(transparent, rgba(0,0,0,0.85));
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .camera-name {
        font-size: 14px;
        font-weight: 500;
        color: #fff;
        flex-shrink: 0;
      }

      .camera-tts-input {
        flex: 1;
        padding: 10px 16px;
        border-radius: 24px;
        border: 1px solid rgba(255,255,255,0.2);
        background: rgba(255,255,255,0.1);
        color: #fff;
        font-size: 14px;
        font-family: inherit;
        backdrop-filter: blur(8px);
      }

      .camera-tts-input::placeholder {
        color: rgba(255,255,255,0.5);
      }

      .camera-tts-input:focus {
        outline: none;
        border-color: var(--panel-accent);
        background: rgba(255,255,255,0.15);
      }

      .camera-tts-btn {
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

      .camera-tts-btn:hover {
        transform: scale(1.08);
      }

      .camera-tts-btn svg {
        width: 18px;
        height: 18px;
        fill: #000;
      }

      .camera-volume {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 120px;
      }

      .camera-volume input {
        width: 80px;
        height: 4px;
        -webkit-appearance: none;
        appearance: none;
        background: rgba(255,255,255,0.2);
        border-radius: 2px;
      }

      .camera-volume input::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--panel-accent);
        cursor: pointer;
      }

      .camera-volume svg {
        width: 18px;
        height: 18px;
        fill: rgba(255,255,255,0.7);
      }

      .sub-cameras-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
      }

      .sub-camera-card {
        position: relative;
        border-radius: 12px;
        overflow: hidden;
        background: #000;
        aspect-ratio: 16/9;
        cursor: pointer;
        transition: transform 0.2s, box-shadow 0.2s;
      }

      .sub-camera-card:hover {
        transform: scale(1.02);
        box-shadow: 0 8px 24px rgba(0, 212, 170, 0.2);
      }

      .sub-camera-card video,
      .sub-camera-card img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
      }

      .sub-camera-label {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 8px 12px;
        background: linear-gradient(transparent, rgba(0,0,0,0.8));
        font-size: 13px;
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }

      .sub-camera-tts-icon {
        width: 16px;
        height: 16px;
        fill: var(--panel-accent);
        opacity: 0.8;
      }

      .no-media-player {
        opacity: 0.4;
      }

      /* Settings Styles */
      .settings-section {
        margin-bottom: 24px;
      }

      .settings-section-title {
        font-size: 14px;
        font-weight: 500;
        color: var(--panel-accent);
        margin: 0 0 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .camera-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: var(--input-bg);
        border-radius: 8px;
        margin-bottom: 8px;
      }

      .camera-item-info {
        flex: 1;
        min-width: 0;
      }

      .camera-item-name {
        font-size: 14px;
        font-weight: 500;
        margin: 0 0 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .camera-item-entity {
        font-size: 12px;
        color: var(--secondary-text-color);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .camera-item-actions {
        display: flex;
        gap: 8px;
      }

      .icon-btn {
        width: 32px;
        height: 32px;
        border-radius: 6px;
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
        background: rgba(255,255,255,0.1);
        color: var(--primary-text-color);
      }

      .icon-btn svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }

      .icon-btn.danger:hover {
        background: rgba(255, 92, 92, 0.15);
        color: var(--panel-danger);
      }

      .live-indicator {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        background: rgba(255, 0, 0, 0.2);
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        color: #ff4444;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .live-indicator::before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #ff4444;
        animation: pulse 1.5s infinite;
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }

      .placeholder-stream {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%);
        color: var(--secondary-text-color);
      }

      .placeholder-stream svg {
        width: 48px;
        height: 48px;
        fill: currentColor;
        margin-bottom: 12px;
        opacity: 0.4;
      }
    `;

    if (this._loading) {
      this.shadowRoot.innerHTML = `
        <style>${styles}</style>
        <div class="panel-container">
          <div class="panel-header">
            <h1 class="panel-title">
              <svg class="panel-title-icon" viewBox="0 0 24 24">
                <path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/>
              </svg>
              Cameras
            </h1>
          </div>
          <div class="content-area">
            ${this._renderLoading()}
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
                <path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/>
              </svg>
              Cameras
            </h1>
          </div>
          <div class="content-area">
            ${this._renderError(this._error)}
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
    const mainCamera = this._config?.main_camera;
    const subCameras = this._config?.sub_cameras || [];

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="panel-container">
        <div class="panel-header">
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">
              <path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/>
            </svg>
            Cameras
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="settings-btn">
              <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
              Settings
            </button>
          </div>
        </div>

        <div class="content-area">
          ${!mainCamera && subCameras.length === 0 ? this._renderEmptyState() : ''}
          
          ${mainCamera ? this._renderMainCamera(mainCamera) : ''}
          
          ${subCameras.length > 0 ? `
            <div class="sub-cameras-grid">
              ${subCameras.map((cam, i) => this._renderSubCamera(cam, i)).join('')}
            </div>
          ` : ''}
        </div>
      </div>
    `;

    this._attachEventListeners();
  }

  _renderEmptyState() {
    return `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24">
          <path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/>
        </svg>
        <h3 class="empty-state-title">No Cameras Configured</h3>
        <p class="empty-state-desc">Add cameras in settings to view live feeds here.</p>
        <button class="btn btn-primary" id="empty-settings-btn">
          <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
          Open Settings
        </button>
      </div>
    `;
  }

  _renderMainCamera(camera) {
    const entityId = typeof camera === 'string' ? camera : camera?.entity_id;
    const mediaPlayer = typeof camera === 'object' ? camera?.media_player : null;
    const friendlyName = this._getEntityName(entityId);

    return `
      <div class="main-camera-container" data-camera="${entityId}">
        <div class="placeholder-stream" id="main-stream-placeholder">
          <svg viewBox="0 0 24 24"><path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/></svg>
          <span>Loading stream...</span>
        </div>
        <video id="main-video" autoplay muted playsinline style="display: none;"></video>
        <div class="camera-overlay">
          <span class="camera-name">${friendlyName}</span>
          <span class="live-indicator">Live</span>
          ${mediaPlayer ? `
            <input type="text" class="camera-tts-input" placeholder="Type message to speak..." data-media-player="${mediaPlayer}" id="main-tts-input">
            <button class="camera-tts-btn" id="main-tts-btn" data-media-player="${mediaPlayer}">
              <svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z M14,3.23v2.06c2.89,0.86,5,3.54,5,6.71s-2.11,5.85-5,6.71v2.06c4.01-0.91,7-4.49,7-8.77S18.01,4.14,14,3.23z"/></svg>
            </button>
            <div class="camera-volume">
              <svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z"/></svg>
              <input type="range" min="0" max="1" step="0.05" value="0.7" id="main-volume" data-media-player="${mediaPlayer}">
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  _renderSubCamera(camera, index) {
    const entityId = camera?.entity_id;
    const mediaPlayer = camera?.media_player;
    const friendlyName = this._getEntityName(entityId);

    return `
      <div class="sub-camera-card" data-camera="${entityId}" data-index="${index}">
        <div class="placeholder-stream" id="sub-stream-placeholder-${index}">
          <svg viewBox="0 0 24 24"><path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/></svg>
        </div>
        <video id="sub-video-${index}" autoplay muted playsinline style="display: none;"></video>
        <div class="sub-camera-label">
          <span>${friendlyName}</span>
          ${mediaPlayer ? `
            <svg class="sub-camera-tts-icon" viewBox="0 0 24 24" title="TTS enabled">
              <path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z"/>
            </svg>
          ` : ''}
        </div>
      </div>
    `;
  }

  _renderSettings(styles) {
    const cameras = this._entities?.cameras || [];
    const mediaPlayers = this._entities?.media_players || [];
    const mainCamera = this._config?.main_camera;
    const subCameras = this._config?.sub_cameras || [];
    const ttsSettings = this._config?.tts_settings || {};

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="panel-container">
        <div class="panel-header">
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.settings}</svg>
            Camera Settings
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="back-btn">
              Back to Cameras
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
              <h2 class="card-title">Main Camera</h2>
            </div>
            <div class="grid-2">
              <div class="form-group">
                <label class="form-label">Camera Entity</label>
                <select class="form-select" id="main-camera-select">
                  <option value="">Select a camera...</option>
                  ${cameras.map(cam => `
                    <option value="${cam.entity_id}" ${this._getMainCameraEntity() === cam.entity_id ? 'selected' : ''}>
                      ${cam.friendly_name}
                    </option>
                  `).join('')}
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Media Player (for TTS)</label>
                <select class="form-select" id="main-media-player-select">
                  <option value="">None</option>
                  ${mediaPlayers.map(mp => `
                    <option value="${mp.entity_id}" ${this._getMainCameraMediaPlayer() === mp.entity_id ? 'selected' : ''}>
                      ${mp.friendly_name}
                    </option>
                  `).join('')}
                </select>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <h2 class="card-title">Sub Cameras</h2>
              <button class="btn btn-secondary" id="add-sub-camera-btn">
                <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
                Add Camera
              </button>
            </div>
            <div id="sub-cameras-list">
              ${subCameras.length === 0 ? `
                <p style="color: var(--secondary-text-color); text-align: center; padding: 20px;">
                  No sub cameras added yet.
                </p>
              ` : subCameras.map((cam, i) => this._renderSubCameraSettingsItem(cam, i, cameras, mediaPlayers)).join('')}
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <h2 class="card-title">TTS Settings</h2>
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
                <label class="form-label">Default Volume</label>
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

  _renderSubCameraSettingsItem(cam, index, cameras, mediaPlayers) {
    return `
      <div class="camera-item" data-index="${index}">
        <div class="camera-item-info" style="flex: 2;">
          <select class="form-select sub-camera-entity" data-index="${index}">
            <option value="">Select camera...</option>
            ${cameras.map(c => `
              <option value="${c.entity_id}" ${cam.entity_id === c.entity_id ? 'selected' : ''}>
                ${c.friendly_name}
              </option>
            `).join('')}
          </select>
        </div>
        <div class="camera-item-info" style="flex: 2;">
          <select class="form-select sub-camera-media-player" data-index="${index}">
            <option value="">No TTS</option>
            ${mediaPlayers.map(mp => `
              <option value="${mp.entity_id}" ${cam.media_player === mp.entity_id ? 'selected' : ''}>
                ${mp.friendly_name}
              </option>
            `).join('')}
          </select>
        </div>
        <div class="camera-item-actions">
          <button class="icon-btn danger remove-sub-camera" data-index="${index}">
            <svg viewBox="0 0 24 24">${icons.delete}</svg>
          </button>
        </div>
      </div>
    `;
  }

  _getMainCameraEntity() {
    const main = this._config?.main_camera;
    if (!main) return '';
    return typeof main === 'string' ? main : main?.entity_id || '';
  }

  _getMainCameraMediaPlayer() {
    const main = this._config?.main_camera;
    if (!main || typeof main === 'string') return '';
    return main?.media_player || '';
  }

  _getEntityName(entityId) {
    if (!entityId || !this._hass) return 'Unknown Camera';
    const state = this._hass.states[entityId];
    return state?.attributes?.friendly_name || entityId.split('.')[1] || entityId;
  }

  _attachEventListeners() {
    const settingsBtn = this.shadowRoot.querySelector('#settings-btn');
    const emptySettingsBtn = this.shadowRoot.querySelector('#empty-settings-btn');
    const mainTtsBtn = this.shadowRoot.querySelector('#main-tts-btn');
    const mainTtsInput = this.shadowRoot.querySelector('#main-tts-input');
    const mainVolume = this.shadowRoot.querySelector('#main-volume');

    if (settingsBtn) {
      settingsBtn.addEventListener('click', () => {
        this._showSettings = true;
        this._cleanup();
        this._render();
      });
    }

    if (emptySettingsBtn) {
      emptySettingsBtn.addEventListener('click', () => {
        this._showSettings = true;
        this._cleanup();
        this._render();
      });
    }

    if (mainTtsBtn && mainTtsInput) {
      mainTtsBtn.addEventListener('click', () => this._sendTTS(mainTtsInput, mainTtsBtn.dataset.mediaPlayer));
      mainTtsInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') this._sendTTS(mainTtsInput, mainTtsBtn.dataset.mediaPlayer);
      });
    }

    if (mainVolume) {
      mainVolume.addEventListener('input', (e) => {
        this._setVolume(e.target.dataset.mediaPlayer, parseFloat(e.target.value));
      });
    }

    // Sub camera clicks (to swap with main)
    this.shadowRoot.querySelectorAll('.sub-camera-card').forEach(card => {
      card.addEventListener('click', () => {
        const index = parseInt(card.dataset.index);
        this._swapWithMain(index);
      });
    });
  }

  _attachSettingsEventListeners() {
    const backBtn = this.shadowRoot.querySelector('#back-btn');
    const saveBtn = this.shadowRoot.querySelector('#save-btn');
    const addSubCameraBtn = this.shadowRoot.querySelector('#add-sub-camera-btn');
    const ttsVolume = this.shadowRoot.querySelector('#tts-volume');
    const ttsVolumeDisplay = this.shadowRoot.querySelector('#tts-volume-display');

    if (backBtn) {
      backBtn.addEventListener('click', () => {
        this._showSettings = false;
        this._render();
        this._setupStreams();
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', () => this._saveSettings());
    }

    if (addSubCameraBtn) {
      addSubCameraBtn.addEventListener('click', () => this._addSubCamera());
    }

    if (ttsVolume && ttsVolumeDisplay) {
      ttsVolume.addEventListener('input', () => {
        ttsVolumeDisplay.textContent = Math.round(parseFloat(ttsVolume.value) * 100) + '%';
      });
    }

    // Remove sub camera buttons
    this.shadowRoot.querySelectorAll('.remove-sub-camera').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = parseInt(btn.dataset.index);
        this._removeSubCamera(index);
      });
    });
  }

  async _setupStreams() {
    if (this._showSettings || !this._hass) return;

    // Setup main camera stream
    const mainCamera = this._config?.main_camera;
    if (mainCamera) {
      const entityId = typeof mainCamera === 'string' ? mainCamera : mainCamera?.entity_id;
      if (entityId) {
        await this._setupHLSStream('main-video', entityId, 'main-stream-placeholder');
      }
    }

    // Setup sub camera streams
    const subCameras = this._config?.sub_cameras || [];
    for (let i = 0; i < subCameras.length; i++) {
      const cam = subCameras[i];
      if (cam?.entity_id) {
        await this._setupHLSStream(`sub-video-${i}`, cam.entity_id, `sub-stream-placeholder-${i}`);
      }
    }
  }

  async _setupHLSStream(videoId, cameraEntityId, placeholderId) {
    const video = this.shadowRoot.querySelector(`#${videoId}`);
    const placeholder = this.shadowRoot.querySelector(`#${placeholderId}`);
    
    if (!video) return;

    try {
      // Get stream URL from backend
      const result = await this._hass.callWS({
        type: 'smart_dashboards/get_camera_stream_url',
        entity_id: cameraEntityId,
      });

      const streamUrl = result.stream_url;

      // Try HLS.js first
      if (window.Hls && Hls.isSupported()) {
        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: true,
        });
        
        this._hlsInstances.set(videoId, hls);
        
        hls.loadSource(streamUrl);
        hls.attachMedia(video);
        
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.style.display = 'block';
          if (placeholder) placeholder.style.display = 'none';
          video.play().catch(() => {});
        });

        hls.on(Hls.Events.ERROR, (event, data) => {
          if (data.fatal) {
            console.error('HLS error:', data);
            // Fallback to snapshot mode
            this._fallbackToSnapshot(video, placeholder, cameraEntityId);
          }
        });
      } 
      // Native HLS support (Safari)
      else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = streamUrl;
        video.addEventListener('loadedmetadata', () => {
          video.style.display = 'block';
          if (placeholder) placeholder.style.display = 'none';
          video.play().catch(() => {});
        });
      }
      // Fallback to snapshot updates
      else {
        this._fallbackToSnapshot(video, placeholder, cameraEntityId);
      }
    } catch (e) {
      console.error('Failed to setup stream:', e);
      this._fallbackToSnapshot(video, placeholder, cameraEntityId);
    }
  }

  _fallbackToSnapshot(video, placeholder, cameraEntityId) {
    // Hide video, show image
    video.style.display = 'none';
    
    const img = document.createElement('img');
    img.src = `/api/camera_proxy/${cameraEntityId}?t=${Date.now()}`;
    img.style.cssText = 'width: 100%; height: 100%; object-fit: contain; display: block;';
    
    const container = video.parentElement;
    if (placeholder) placeholder.style.display = 'none';
    container.insertBefore(img, video);

    // Refresh every 2 seconds
    const refresher = setInterval(() => {
      if (!this.isConnected || this._showSettings) {
        clearInterval(refresher);
        return;
      }
      img.src = `/api/camera_proxy/${cameraEntityId}?t=${Date.now()}`;
    }, 2000);
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

  async _swapWithMain(subIndex) {
    const subCameras = [...(this._config?.sub_cameras || [])];
    const mainCamera = this._config?.main_camera;
    
    if (subIndex < 0 || subIndex >= subCameras.length) return;

    // Swap
    const newMain = subCameras[subIndex];
    subCameras[subIndex] = typeof mainCamera === 'string' 
      ? { entity_id: mainCamera, media_player: null }
      : mainCamera;

    this._config.main_camera = newMain;
    this._config.sub_cameras = subCameras;

    // Re-render and setup streams
    this._cleanup();
    this._render();
    await this._setupStreams();
  }

  _addSubCamera() {
    const cameras = this._entities?.cameras || [];
    const mediaPlayers = this._entities?.media_players || [];
    
    const list = this.shadowRoot.querySelector('#sub-cameras-list');
    const noItems = list.querySelector('p');
    if (noItems) noItems.remove();

    const index = list.querySelectorAll('.camera-item').length;
    const html = this._renderSubCameraSettingsItem({ entity_id: '', media_player: '' }, index, cameras, mediaPlayers);
    
    list.insertAdjacentHTML('beforeend', html);
    
    // Attach remove listener
    const newItem = list.querySelector(`.camera-item[data-index="${index}"]`);
    const removeBtn = newItem.querySelector('.remove-sub-camera');
    removeBtn.addEventListener('click', () => this._removeSubCamera(index));
  }

  _removeSubCamera(index) {
    const item = this.shadowRoot.querySelector(`.camera-item[data-index="${index}"]`);
    if (item) item.remove();
  }

  async _saveSettings() {
    const mainCameraEntity = this.shadowRoot.querySelector('#main-camera-select')?.value || null;
    const mainMediaPlayer = this.shadowRoot.querySelector('#main-media-player-select')?.value || null;
    
    const subCameraItems = this.shadowRoot.querySelectorAll('.camera-item');
    const subCameras = [];
    
    subCameraItems.forEach(item => {
      const entitySelect = item.querySelector('.sub-camera-entity');
      const mediaPlayerSelect = item.querySelector('.sub-camera-media-player');
      
      if (entitySelect?.value) {
        subCameras.push({
          entity_id: entitySelect.value,
          media_player: mediaPlayerSelect?.value || null,
        });
      }
    });

    const ttsLanguage = this.shadowRoot.querySelector('#tts-language')?.value || 'en';
    const ttsVolume = parseFloat(this.shadowRoot.querySelector('#tts-volume')?.value || 0.7);

    const config = {
      main_camera: mainCameraEntity ? {
        entity_id: mainCameraEntity,
        media_player: mainMediaPlayer,
      } : null,
      sub_cameras: subCameras,
      tts_settings: {
        language: ttsLanguage,
        speed: 1.0,
        volume: ttsVolume,
      },
    };

    try {
      await this._hass.callWS({
        type: 'smart_dashboards/save_cameras',
        config: config,
      });

      this._config = config;
      showToast(this.shadowRoot, 'Settings saved!');
      
      // Go back to main view
      setTimeout(() => {
        this._showSettings = false;
        this._render();
        this._setupStreams();
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', true);
    }
  }
}

// Load HLS.js if not already loaded
if (!window.Hls) {
  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/hls.js@latest';
  document.head.appendChild(script);
}

customElements.define('cameras-panel', CamerasPanel);
