/**
 * Cameras Panel for Smart Dashboards
 * Live camera feeds with TTS integration
 */

import { sharedStyles, icons, showToast, passcodeModalStyles, showPasscodeModal } from './shared-utils.js';

class CamerasPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._entities = null;
    this._showSettings = false;
    this._refreshIntervals = new Map();
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
    this._refreshIntervals.forEach((interval) => clearInterval(interval));
    this._refreshIntervals.clear();
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
      this._startCameraRefresh();
    } catch (e) {
      console.error('Failed to load cameras config:', e);
      this._loading = false;
      this._error = e.message || 'Failed to load configuration';
      this._render();
    }
  }

  _startCameraRefresh() {
    this._cleanup();
    
    // Refresh all camera images every 500ms for smooth live feed
    const mainCamera = this._config?.main_camera;
    if (mainCamera) {
      const entityId = typeof mainCamera === 'string' ? mainCamera : mainCamera?.entity_id;
      if (entityId) {
        this._startImageRefresh('main-camera-img', entityId);
      }
    }

    const subCameras = this._config?.sub_cameras || [];
    subCameras.forEach((cam, i) => {
      if (cam?.entity_id) {
        this._startImageRefresh(`sub-camera-img-${i}`, cam.entity_id);
      }
    });
  }

  _startImageRefresh(imgId, entityId) {
    const updateImage = () => {
      const img = this.shadowRoot.querySelector(`#${imgId}`);
      if (img && this._hass) {
        const timestamp = Date.now();
        img.src = `/api/camera_proxy/${entityId}?token=${this._hass.auth.data.access_token}&t=${timestamp}`;
      }
    };
    
    // Initial load
    updateImage();
    
    // Refresh every 500ms
    const interval = setInterval(updateImage, 500);
    this._refreshIntervals.set(imgId, interval);
  }

  _render() {
    const styles = `
      ${sharedStyles}
      ${passcodeModalStyles}
      
      .cameras-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 16px;
      }

      .main-camera-section {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
      }

      @media (max-width: 1000px) {
        .main-camera-section {
          grid-template-columns: 1fr;
        }
      }

      .camera-card {
        position: relative;
        border-radius: 12px;
        overflow: hidden;
        background: #000;
        aspect-ratio: 16/9;
      }

      .camera-card.main {
        aspect-ratio: 16/9;
      }

      .camera-card img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
      }

      .camera-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 12px 16px;
        background: linear-gradient(transparent, rgba(0,0,0,0.9));
      }

      .camera-name {
        font-size: 13px;
        font-weight: 500;
        color: #fff;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .live-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        background: rgba(244, 67, 54, 0.9);
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .live-badge::before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #fff;
        animation: pulse 1.5s infinite;
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }

      .camera-tts-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .camera-tts-input {
        flex: 1;
        padding: 8px 12px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,0.2);
        background: rgba(255,255,255,0.1);
        color: #fff;
        font-size: 13px;
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
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: var(--panel-accent);
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: transform 0.2s, background 0.2s;
      }

      .camera-tts-btn:hover {
        transform: scale(1.08);
        background: var(--panel-accent-hover);
      }

      .camera-tts-btn svg {
        width: 16px;
        height: 16px;
        fill: #fff;
      }

      .camera-volume-mini {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .camera-volume-mini svg {
        width: 16px;
        height: 16px;
        fill: rgba(255,255,255,0.6);
      }

      .camera-volume-mini input {
        width: 60px;
        height: 4px;
        -webkit-appearance: none;
        appearance: none;
        background: rgba(255,255,255,0.2);
        border-radius: 2px;
      }

      .camera-volume-mini input::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--panel-accent);
        cursor: pointer;
      }

      .sub-cameras-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 12px;
      }

      .camera-card.sub {
        cursor: pointer;
        transition: transform 0.2s, box-shadow 0.2s;
      }

      .camera-card.sub:hover {
        transform: scale(1.02);
        box-shadow: 0 8px 24px rgba(3, 169, 244, 0.2);
      }

      .no-tts-indicator {
        font-size: 11px;
        color: rgba(255,255,255,0.4);
        font-style: italic;
      }

      .camera-placeholder {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        color: rgba(255,255,255,0.4);
      }

      .camera-placeholder svg {
        width: 40px;
        height: 40px;
        fill: currentColor;
        margin-bottom: 8px;
      }

      .camera-placeholder span {
        font-size: 12px;
      }

      /* Settings Styles */
      .camera-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: var(--input-bg);
        border-radius: 8px;
        margin-bottom: 8px;
      }

      .camera-item .form-group {
        flex: 1;
        margin: 0;
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
              <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.camera}</svg>
              Cameras
            </h1>
          </div>
          <div class="content-area">
            <div class="loading">
              <div class="loading-spinner"></div>
              <span>Loading cameras...</span>
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
              <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.camera}</svg>
              Cameras
            </h1>
          </div>
          <div class="content-area">
            <div class="empty-state">
              <svg class="empty-state-icon" viewBox="0 0 24 24" style="fill: var(--panel-danger);">
                ${icons.warning}
              </svg>
              <h3 class="empty-state-title">Error Loading Cameras</h3>
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
    const mainCamera = this._config?.main_camera;
    const subCameras = this._config?.sub_cameras || [];

    this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="panel-container">
        <div class="panel-header">
          <button class="menu-btn" id="menu-btn" title="Menu">
            <svg viewBox="0 0 24 24">${icons.menu}</svg>
          </button>
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.camera}</svg>
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
          
          ${mainCamera || subCameras.length > 0 ? `
            <div class="main-camera-section">
              ${mainCamera ? this._renderCameraCard(mainCamera, 'main', 'main-camera-img') : ''}
              ${subCameras.slice(0, 1).map((cam, i) => this._renderCameraCard(cam, 'main', `sub-camera-img-${i}`)).join('')}
            </div>
            
            ${subCameras.length > 1 ? `
              <div class="sub-cameras-grid" style="margin-top: 16px;">
                ${subCameras.slice(1).map((cam, i) => this._renderCameraCard(cam, 'sub', `sub-camera-img-${i + 1}`, i + 1)).join('')}
              </div>
            ` : ''}
          ` : ''}
        </div>
      </div>
    `;

    this._attachEventListeners();
  }

  _renderCameraCard(camera, type, imgId, index = 0) {
    const entityId = typeof camera === 'string' ? camera : camera?.entity_id;
    const mediaPlayer = typeof camera === 'object' ? camera?.media_player : null;
    const friendlyName = this._getEntityName(entityId);

    return `
      <div class="camera-card ${type}" data-entity="${entityId}" data-index="${index}">
        <div class="camera-placeholder">
          <svg viewBox="0 0 24 24">${icons.camera}</svg>
          <span>Loading feed...</span>
        </div>
        <img id="${imgId}" alt="${friendlyName}" style="position: absolute; top: 0; left: 0;" onerror="this.style.display='none'" onload="this.style.display='block'; this.previousElementSibling.style.display='none';">
        <div class="camera-overlay">
          <div class="camera-name">
            ${friendlyName}
            <span class="live-badge">Live</span>
          </div>
          ${mediaPlayer ? `
            <div class="camera-tts-row">
              <input type="text" class="camera-tts-input" placeholder="Type message to speak..." data-media-player="${mediaPlayer}">
              <button class="camera-tts-btn" data-media-player="${mediaPlayer}" title="Speak">
                <svg viewBox="0 0 24 24">${icons.speaker}</svg>
              </button>
              <div class="camera-volume-mini">
                <svg viewBox="0 0 24 24">${icons.volume}</svg>
                <input type="range" min="0" max="1" step="0.05" value="0.7" data-media-player="${mediaPlayer}">
              </div>
            </div>
          ` : `
            <div class="no-tts-indicator">No media player linked</div>
          `}
        </div>
      </div>
    `;
  }

  _renderEmptyState() {
    return `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24">${icons.camera}</svg>
        <h3 class="empty-state-title">No Cameras Configured</h3>
        <p class="empty-state-desc">Add cameras in settings to view live feeds here.</p>
        <button class="btn btn-primary" id="empty-settings-btn">
          <svg class="btn-icon" viewBox="0 0 24 24">${icons.settings}</svg>
          Open Settings
        </button>
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
          <button class="menu-btn" id="menu-btn" title="Menu">
            <svg viewBox="0 0 24 24">${icons.menu}</svg>
          </button>
          <h1 class="panel-title">
            <svg class="panel-title-icon" viewBox="0 0 24 24">${icons.settings}</svg>
            Camera Settings
          </h1>
          <div class="header-actions">
            <button class="btn btn-secondary" id="back-btn">Back to Cameras</button>
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
              <h2 class="card-title">Additional Cameras</h2>
              <button class="btn btn-secondary" id="add-sub-camera-btn">
                <svg class="btn-icon" viewBox="0 0 24 24">${icons.add}</svg>
                Add Camera
              </button>
            </div>
            <div id="sub-cameras-list">
              ${subCameras.length === 0 ? `
                <p style="color: var(--secondary-text-color); text-align: center; padding: 20px;">
                  No additional cameras added yet.
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
        <div class="form-group">
          <label class="form-label">Camera</label>
          <select class="form-select sub-camera-entity" data-index="${index}">
            <option value="">Select camera...</option>
            ${cameras.map(c => `
              <option value="${c.entity_id}" ${cam.entity_id === c.entity_id ? 'selected' : ''}>
                ${c.friendly_name}
              </option>
            `).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Media Player</label>
          <select class="form-select sub-camera-media-player" data-index="${index}">
            <option value="">None</option>
            ${mediaPlayers.map(mp => `
              <option value="${mp.entity_id}" ${cam.media_player === mp.entity_id ? 'selected' : ''}>
                ${mp.friendly_name}
              </option>
            `).join('')}
          </select>
        </div>
        <button class="icon-btn danger remove-sub-camera" data-index="${index}" style="margin-top: 20px;">
          <svg viewBox="0 0 24 24">${icons.delete}</svg>
        </button>
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
    // Menu button to toggle HA sidebar
    this._attachMenuButton();

    const settingsBtn = this.shadowRoot.querySelector('#settings-btn');
    const emptySettingsBtn = this.shadowRoot.querySelector('#empty-settings-btn');

    if (settingsBtn) {
      settingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._showSettings = true;
          this._cleanup();
          this._render();
        }
      });
    }

    if (emptySettingsBtn) {
      emptySettingsBtn.addEventListener('click', async () => {
        const verified = await showPasscodeModal(this.shadowRoot, this._hass);
        if (verified) {
          this._showSettings = true;
          this._cleanup();
          this._render();
        }
      });
    }

    // TTS buttons
    this.shadowRoot.querySelectorAll('.camera-tts-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const input = btn.previousElementSibling;
        this._sendTTS(input, btn.dataset.mediaPlayer);
      });
    });

    // TTS input enter key
    this.shadowRoot.querySelectorAll('.camera-tts-input').forEach(input => {
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          this._sendTTS(input, input.dataset.mediaPlayer);
        }
      });
    });

    // Volume sliders
    this.shadowRoot.querySelectorAll('.camera-volume-mini input').forEach(slider => {
      slider.addEventListener('input', (e) => {
        this._setVolume(e.target.dataset.mediaPlayer, parseFloat(e.target.value));
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
    const addSubCameraBtn = this.shadowRoot.querySelector('#add-sub-camera-btn');
    const ttsVolume = this.shadowRoot.querySelector('#tts-volume');
    const ttsVolumeDisplay = this.shadowRoot.querySelector('#tts-volume-display');

    if (backBtn) {
      backBtn.addEventListener('click', () => {
        this._showSettings = false;
        this._render();
        this._startCameraRefresh();
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
        const item = btn.closest('.camera-item');
        if (item) item.remove();
      });
    });
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
      showToast(this.shadowRoot, 'Message sent!', 'success');
    } catch (e) {
      console.error('TTS failed:', e);
      showToast(this.shadowRoot, 'Failed to send message', 'error');
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
      showToast(this.shadowRoot, 'Settings saved!', 'success');
      
      setTimeout(() => {
        this._showSettings = false;
        this._render();
        this._startCameraRefresh();
      }, 500);
    } catch (e) {
      console.error('Failed to save settings:', e);
      showToast(this.shadowRoot, 'Failed to save settings', 'error');
    }
  }
}

customElements.define('cameras-panel', CamerasPanel);
