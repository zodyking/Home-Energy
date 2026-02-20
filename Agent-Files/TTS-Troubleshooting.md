# TTS Troubleshooting (Home Energy Integration)

## "failed to init decoder" Error

If you see errors like `Failed to send TTS: ('failed to init decoder', -1)` or `Failed to send outlet threshold alert: ('failed to init decoder', -1)` in Home Assistant logs, this typically originates from **Home Assistant and the Apple TV / HomePod integration**, not from the Home Energy custom integration.

### Common causes

- Using **HomePod** or **Apple TV** as the TTS media player (pyatv / miniaudio decoder issues)
- External TTS engines (e.g., Piper, ElevenLabs) with Apple TV devices
- TTS audio taking longer than expected, causing timeouts

### Mitigations to try

1. **Use a different media player** – Use a non–Apple TV device (e.g., Echo, Chromecast, Sonos) for TTS alerts.
2. **Set `internal_url` to an IP** – In `configuration.yaml`, change `internal_url` from a hostname (e.g. `http://homeassistant.local:8123`) to an IP address (e.g. `http://192.168.1.100:8123`) and restart Home Assistant.
3. **Try another TTS engine** – Use a different TTS integration (e.g., Google Translate, Piper) in Home Assistant.
4. **Update Home Assistant** – This is a known issue in some versions; updates may include fixes.

The Home Energy integration uses non-blocking TTS by default to avoid blocking the energy monitor loop when decoder issues occur.
