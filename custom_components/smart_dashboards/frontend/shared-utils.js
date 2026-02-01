/**
 * Shared utilities for Smart Dashboards panels
 */

// Common CSS styles for both panels - Home Assistant blue theme
export const sharedStyles = `
  :host {
    display: block;
    height: 100%;
    background: var(--primary-background-color, #111318);
    color: var(--primary-text-color, #e1e1e1);
    font-family: var(--paper-font-body1_-_font-family, 'Roboto', 'Segoe UI', sans-serif);
    --panel-accent: #03a9f4;
    --panel-accent-rgb: 3, 169, 244;
    --panel-accent-dim: rgba(3, 169, 244, 0.15);
    --panel-accent-hover: #29b6f6;
    --panel-danger: #f44336;
    --panel-warning: #ff9800;
    --panel-success: #4caf50;
    --card-bg: var(--card-background-color, rgba(32, 33, 39, 0.95));
    --card-border: rgba(255, 255, 255, 0.08);
    --input-bg: rgba(255, 255, 255, 0.04);
    --input-border: rgba(255, 255, 255, 0.12);
  }

  * {
    box-sizing: border-box;
  }

  .panel-container {
    min-height: 100vh;
    padding: 0;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    background: linear-gradient(135deg, rgba(3, 169, 244, 0.1) 0%, rgba(3, 169, 244, 0.02) 100%);
    border-bottom: 1px solid var(--card-border);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(12px);
  }

  .menu-btn {
    display: none;
    width: 40px;
    height: 40px;
    border-radius: 8px;
    border: none;
    background: transparent;
    color: var(--primary-text-color);
    cursor: pointer;
    align-items: center;
    justify-content: center;
    margin-right: 8px;
    flex-shrink: 0;
  }

  .menu-btn svg {
    width: 24px;
    height: 24px;
    fill: currentColor;
  }

  .menu-btn:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  @media (max-width: 870px) {
    .menu-btn {
      display: flex;
    }
  }

  .panel-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-size: 16px;
    font-weight: 500;
    letter-spacing: 0.3px;
  }

  .panel-title-icon {
    width: 20px;
    height: 20px;
    fill: var(--panel-accent);
  }

  .header-actions {
    display: flex;
    gap: 10px;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    font-size: 12px;
    font-weight: 500;
    transition: all 0.2s ease;
    font-family: inherit;
  }

  .btn-primary {
    background: var(--panel-accent);
    color: #fff;
  }

  .btn-primary:hover {
    background: var(--panel-accent-hover);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(3, 169, 244, 0.3);
  }

  .btn-secondary {
    background: var(--input-bg);
    color: var(--primary-text-color);
    border: 1px solid var(--input-border);
  }

  .btn-secondary:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .btn-icon {
    width: 18px;
    height: 18px;
    fill: currentColor;
  }

  .btn-danger {
    background: rgba(244, 67, 54, 0.15);
    color: var(--panel-danger);
    border: 1px solid rgba(244, 67, 54, 0.3);
  }

  .btn-danger:hover {
    background: rgba(244, 67, 54, 0.25);
  }

  .content-area {
    padding: 12px 16px;
    max-width: 1800px;
    margin: 0 auto;
  }

  .card {
    background: var(--card-bg);
    border-radius: 12px;
    border: 1px solid var(--card-border);
    padding: 20px;
    margin-bottom: 16px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--card-border);
  }

  .card-title {
    font-size: 16px;
    font-weight: 500;
    margin: 0;
    color: var(--primary-text-color);
  }

  /* Form Elements */
  .form-group {
    margin-bottom: 16px;
  }

  .form-label {
    display: block;
    margin-bottom: 6px;
    font-size: 12px;
    color: var(--secondary-text-color, #9e9e9e);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .form-input, .form-select {
    width: 100%;
    padding: 12px 14px;
    border-radius: 8px;
    border: 1px solid var(--input-border, rgba(255,255,255,0.12));
    background: var(--input-bg, #2a2a2a);
    color: var(--primary-text-color, #e0e0e0);
    font-size: 14px;
    font-family: inherit;
    transition: border-color 0.2s, background 0.2s;
  }

  .form-input:focus, .form-select:focus {
    outline: none;
    border-color: var(--panel-accent);
    background: rgba(3, 169, 244, 0.05);
  }

  .form-select {
    cursor: pointer;
    appearance: none;
    background-color: var(--input-bg, #2a2a2a);
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239e9e9e' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 36px;
  }

  .form-select option {
    background: var(--input-bg, #2a2a2a);
    color: var(--primary-text-color, #e0e0e0);
  }

  /* Volume Slider */
  .volume-control {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .volume-icon {
    width: 20px;
    height: 20px;
    fill: var(--secondary-text-color);
    flex-shrink: 0;
  }

  .volume-slider {
    flex: 1;
    height: 6px;
    -webkit-appearance: none;
    appearance: none;
    background: var(--input-bg);
    border-radius: 3px;
    outline: none;
  }

  .volume-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--panel-accent);
    cursor: pointer;
    border: none;
    box-shadow: 0 2px 6px rgba(3, 169, 244, 0.4);
  }

  .volume-slider::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--panel-accent);
    cursor: pointer;
    border: none;
  }

  .volume-value {
    min-width: 40px;
    text-align: right;
    font-size: 13px;
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  /* Grid Layouts */
  .grid-2 {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }

  .grid-3 {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }

  .grid-4 {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }

  @media (max-width: 1200px) {
    .grid-4 {
      grid-template-columns: repeat(3, 1fr);
    }
  }

  @media (max-width: 900px) {
    .grid-3, .grid-4 {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  @media (max-width: 600px) {
    .grid-2, .grid-3, .grid-4 {
      grid-template-columns: 1fr;
    }
  }

  /* Loading State */
  .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px;
    color: var(--secondary-text-color);
  }

  .loading-spinner {
    width: 36px;
    height: 36px;
    border: 3px solid var(--input-border);
    border-top-color: var(--panel-accent);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 16px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* Empty State */
  .empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--secondary-text-color);
  }

  .empty-state-icon {
    width: 56px;
    height: 56px;
    fill: rgba(255, 255, 255, 0.1);
    margin-bottom: 16px;
  }

  .empty-state-title {
    font-size: 18px;
    font-weight: 500;
    margin: 0 0 8px;
    color: var(--primary-text-color);
  }

  .empty-state-desc {
    font-size: 14px;
    margin: 0 0 20px;
  }

  /* Modal/Dialog */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.75);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    backdrop-filter: blur(4px);
  }

  .modal {
    background: var(--card-bg);
    border-radius: 16px;
    border: 1px solid var(--card-border);
    width: 90%;
    max-width: 560px;
    max-height: 85vh;
    overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 24px;
    border-bottom: 1px solid var(--card-border);
  }

  .modal-title {
    font-size: 18px;
    font-weight: 500;
    margin: 0;
  }

  .modal-close {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: none;
    background: var(--input-bg);
    color: var(--secondary-text-color);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
  }

  .modal-close:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .modal-body {
    padding: 24px;
  }

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding: 16px 24px;
    border-top: 1px solid var(--card-border);
  }

  /* Toast Notification */
  .toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-left: 3px solid var(--panel-accent);
    border-radius: 8px;
    padding: 14px 20px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    z-index: 1100;
    animation: slideIn 0.3s ease;
  }

  .toast.error {
    border-left-color: var(--panel-danger);
  }

  .toast.success {
    border-left-color: var(--panel-success);
  }

  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateX(20px);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }
`;

// SVG Icons
export const icons = {
  settings: `<svg viewBox="0 0 24 24"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>`,
  camera: `<svg viewBox="0 0 24 24"><path d="M17,10.5V7c0-0.55-0.45-1-1-1H4C3.45,6,3,6.45,3,7v10c0,0.55,0.45,1,1,1h12c0.55,0,1-0.45,1-1v-3.5l4,4v-11L17,10.5z"/></svg>`,
  flash: `<svg viewBox="0 0 24 24"><path d="M7,2v11h3v9l7-12h-4l4-8z"/></svg>`,
  speaker: `<svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z M14,3.23v2.06c2.89,0.86,5,3.54,5,6.71s-2.11,5.85-5,6.71v2.06c4.01-0.91,7-4.49,7-8.77S18.01,4.14,14,3.23z"/></svg>`,
  add: `<svg viewBox="0 0 24 24"><path d="M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6V13z"/></svg>`,
  close: `<svg viewBox="0 0 24 24"><path d="M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41z"/></svg>`,
  delete: `<svg viewBox="0 0 24 24"><path d="M6,19c0,1.1,0.9,2,2,2h8c1.1,0,2-0.9,2-2V7H6V19z M19,4h-3.5l-1-1h-5l-1,1H5v2h14V4z"/></svg>`,
  edit: `<svg viewBox="0 0 24 24"><path d="M3,17.25V21h3.75L17.81,9.94l-3.75-3.75L3,17.25z M20.71,7.04c0.39-0.39,0.39-1.02,0-1.41l-2.34-2.34 c-0.39-0.39-1.02-0.39-1.41,0l-1.83,1.83l3.75,3.75L20.71,7.04z"/></svg>`,
  volume: `<svg viewBox="0 0 24 24"><path d="M3,9v6h4l5,5V4L7,9H3z M16.5,12c0-1.77-1.02-3.29-2.5-4.03v8.05C15.48,15.29,16.5,13.77,16.5,12z"/></svg>`,
  plug: `<svg viewBox="0 0 24 24"><path d="M12,2C6.48,2,2,6.48,2,12s4.48,10,10,10s10-4.48,10-10S17.52,2,12,2z M12,20c-4.41,0-8-3.59-8-8s3.59-8,8-8s8,3.59,8,8 S16.41,20,12,20z M11,7h2v6h-2V7z M11,15h2v2h-2V15z"/></svg>`,
  room: `<svg viewBox="0 0 24 24"><path d="M12,3L2,12h3v8h14v-8h3L12,3z M12,16c-1.1,0-2-0.9-2-2c0-1.1,0.9-2,2-2s2,0.9,2,2C14,15.1,13.1,16,12,16z"/></svg>`,
  check: `<svg viewBox="0 0 24 24"><path d="M9,16.17L4.83,12l-1.42,1.41L9,19L21,7l-1.41-1.41L9,16.17z"/></svg>`,
  warning: `<svg viewBox="0 0 24 24"><path d="M1,21h22L12,2L1,21z M13,18h-2v-2h2V18z M13,14h-2v-4h2V14z"/></svg>`,
  outlet: `<svg viewBox="0 0 24 24"><path d="M12,2A10,10,0,1,0,22,12,10,10,0,0,0,12,2Zm0,18a8,8,0,1,1,8-8A8,8,0,0,1,12,20ZM9,9H11V13H9ZM13,9h2v4H13Z"/></svg>`,
  menu: `<svg viewBox="0 0 24 24"><path d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>`,
  power: `<svg viewBox="0 0 24 24"><path d="M13,3h-2v10h2V3z M17.83,5.17l-1.42,1.42C17.99,7.86,19,9.81,19,12c0,3.87-3.13,7-7,7s-7-3.13-7-7 c0-2.19,1.01-4.14,2.58-5.42L6.17,5.17C4.23,6.82,3,9.26,3,12c0,4.97,4.03,9,9,9s9-4.03,9-9C21,9.26,19.77,6.82,17.83,5.17z"/></svg>`,
};

// Helper function to show toast
export function showToast(shadowRoot, message, type = 'default') {
  // Remove existing toast
  const existing = shadowRoot.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  shadowRoot.appendChild(toast);

  setTimeout(() => toast.remove(), 3000);
}

// Passcode modal styles
export const passcodeModalStyles = `
  .passcode-modal {
    background: var(--card-bg);
    border-radius: 16px;
    border: 1px solid var(--card-border);
    width: 90%;
    max-width: 320px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
    animation: modalSlideIn 0.2s ease;
  }

  @keyframes modalSlideIn {
    from {
      opacity: 0;
      transform: scale(0.95) translateY(-10px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  .passcode-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--card-border);
  }

  .passcode-title {
    font-size: 16px;
    font-weight: 500;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .passcode-title svg {
    width: 20px;
    height: 20px;
    fill: var(--panel-accent);
  }

  .passcode-body {
    padding: 24px 20px;
    text-align: center;
  }

  .passcode-desc {
    font-size: 13px;
    color: var(--secondary-text-color);
    margin: 0 0 20px;
  }

  .passcode-input-wrapper {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-bottom: 16px;
  }

  .passcode-digit {
    width: 48px;
    height: 56px;
    border-radius: 10px;
    border: 2px solid var(--input-border);
    background: var(--input-bg);
    color: var(--primary-text-color);
    font-size: 24px;
    font-weight: 600;
    text-align: center;
    font-family: 'Roboto Mono', monospace;
    transition: border-color 0.2s, background 0.2s;
  }

  .passcode-digit:focus {
    outline: none;
    border-color: var(--panel-accent);
    background: rgba(3, 169, 244, 0.05);
  }

  .passcode-digit.error {
    border-color: var(--panel-danger);
    animation: shake 0.3s ease;
  }

  @keyframes shake {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(-5px); }
    75% { transform: translateX(5px); }
  }

  .passcode-error {
    font-size: 12px;
    color: var(--panel-danger);
    margin: 0 0 12px;
    min-height: 18px;
  }

  .passcode-footer {
    display: flex;
    gap: 10px;
    padding: 0 20px 20px;
  }

  .passcode-footer .btn {
    flex: 1;
  }
`;

// Lock icon for passcode
export const lockIcon = `<svg viewBox="0 0 24 24"><path d="M18,8h-1V6c0-2.76-2.24-5-5-5S7,3.24,7,6v2H6c-1.1,0-2,0.9-2,2v10c0,1.1,0.9,2,2,2h12c1.1,0,2-0.9,2-2V10 C20,8.9,19.1,8,18,8z M12,17c-1.1,0-2-0.9-2-2s0.9-2,2-2s2,0.9,2,2S13.1,17,12,17z M15.1,8H8.9V6c0-1.71,1.39-3.1,3.1-3.1 s3.1,1.39,3.1,3.1V8z"/></svg>`;

/**
 * Show passcode modal and verify with backend
 * @param {ShadowRoot} shadowRoot - The shadow root to attach modal to
 * @param {object} hass - Home Assistant object for WS calls
 * @returns {Promise<boolean>} - True if passcode verified, false if cancelled
 */
export function showPasscodeModal(shadowRoot, hass) {
  return new Promise((resolve) => {
    // Create modal HTML
    const modalOverlay = document.createElement('div');
    modalOverlay.className = 'modal-overlay';
    modalOverlay.innerHTML = `
      <div class="passcode-modal">
        <div class="passcode-header">
          <h3 class="passcode-title">
            ${lockIcon}
            Settings Locked
          </h3>
        </div>
        <div class="passcode-body">
          <p class="passcode-desc">Enter your 4-digit passcode to access settings</p>
          <div class="passcode-input-wrapper">
            <input type="tel" class="passcode-digit" maxlength="1" inputmode="numeric" pattern="[0-9]" autocomplete="off">
            <input type="tel" class="passcode-digit" maxlength="1" inputmode="numeric" pattern="[0-9]" autocomplete="off">
            <input type="tel" class="passcode-digit" maxlength="1" inputmode="numeric" pattern="[0-9]" autocomplete="off">
            <input type="tel" class="passcode-digit" maxlength="1" inputmode="numeric" pattern="[0-9]" autocomplete="off">
          </div>
          <p class="passcode-error"></p>
        </div>
        <div class="passcode-footer">
          <button class="btn btn-secondary passcode-cancel">Cancel</button>
          <button class="btn btn-primary passcode-submit">Unlock</button>
        </div>
      </div>
    `;

    shadowRoot.appendChild(modalOverlay);

    const digits = modalOverlay.querySelectorAll('.passcode-digit');
    const errorEl = modalOverlay.querySelector('.passcode-error');
    const cancelBtn = modalOverlay.querySelector('.passcode-cancel');
    const submitBtn = modalOverlay.querySelector('.passcode-submit');

    // Focus first digit
    setTimeout(() => digits[0].focus(), 100);

    // Handle digit input - auto-advance to next
    digits.forEach((digit, idx) => {
      digit.addEventListener('input', (e) => {
        // Only allow numbers
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
        
        if (e.target.value && idx < 3) {
          digits[idx + 1].focus();
        }
        
        // Clear error state
        digits.forEach(d => d.classList.remove('error'));
        errorEl.textContent = '';
      });

      digit.addEventListener('keydown', (e) => {
        // Handle backspace - go to previous
        if (e.key === 'Backspace' && !e.target.value && idx > 0) {
          digits[idx - 1].focus();
        }
        // Handle Enter - submit
        if (e.key === 'Enter') {
          submitBtn.click();
        }
      });

      // Select all on focus for easy replace
      digit.addEventListener('focus', () => digit.select());
    });

    // Cancel button
    cancelBtn.addEventListener('click', () => {
      modalOverlay.remove();
      resolve(false);
    });

    // Click outside to cancel
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) {
        modalOverlay.remove();
        resolve(false);
      }
    });

    // Escape key to cancel
    const escHandler = (e) => {
      if (e.key === 'Escape') {
        modalOverlay.remove();
        document.removeEventListener('keydown', escHandler);
        resolve(false);
      }
    };
    document.addEventListener('keydown', escHandler);

    // Submit button
    submitBtn.addEventListener('click', async () => {
      const passcode = Array.from(digits).map(d => d.value).join('');
      
      if (passcode.length !== 4) {
        errorEl.textContent = 'Please enter all 4 digits';
        digits.forEach(d => d.classList.add('error'));
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Checking...';

      try {
        const result = await hass.callWS({
          type: 'smart_dashboards/verify_passcode',
          passcode: passcode,
        });

        if (result.valid) {
          modalOverlay.remove();
          document.removeEventListener('keydown', escHandler);
          resolve(true);
        } else {
          errorEl.textContent = 'Incorrect passcode';
          digits.forEach(d => {
            d.value = '';
            d.classList.add('error');
          });
          digits[0].focus();
          submitBtn.disabled = false;
          submitBtn.textContent = 'Unlock';
        }
      } catch (e) {
        console.error('Passcode verification failed:', e);
        errorEl.textContent = 'Verification failed';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Unlock';
      }
    });
  });
}
