# Home Assistant Configuration Fixes

This document describes common Home Assistant configuration issues that may appear in your logs and how to fix them. These are **not** issues with the Smart Dashboards integration—they are configuration problems in your HA setup.

## 1. Template Float Errors

### Symptoms

Logs show errors like:

```
ValueError: Template error: float got invalid input 'unknown' when rendering template 
'{{ states('sensor.kitchen_outlet_current_consumption') | float > 15 }}' 
but no default was specified
```

### Cause

When a sensor is unavailable or returns `unknown`, the `| float` filter fails because it cannot convert non-numeric values.

### Fix

Add a default value to all `| float` filters in your templates:

**Before (broken):**
```yaml
binary_sensor:
  - platform: template
    sensors:
      stove_in_use:
        value_template: "{{ states('sensor.kitchen_outlet_current_consumption') | float > 15 }}"
```

**After (fixed):**
```yaml
binary_sensor:
  - platform: template
    sensors:
      stove_in_use:
        value_template: "{{ states('sensor.kitchen_outlet_current_consumption') | float(0) > 15 }}"
```

The `| float(0)` syntax returns `0` when the sensor value is `unknown` or unavailable, preventing the template error.

### Where to Apply

Check these files for `| float` without defaults:
- `configuration.yaml`
- `templates.yaml`  
- `binary_sensors.yaml`
- `sensors.yaml`
- Any automation or script templates

---

## 2. Duplicate Automation IDs

### Symptoms

Logs show warnings like:

```
ID news_roundup_tts_hourly already exists - ignoring automation.news_roundup_tts_hourly
```

### Cause

Two automations in `automations.yaml` share the same `id` field. Home Assistant requires unique IDs.

### Fix

1. Open `automations.yaml`
2. Search for the duplicate ID (e.g., `news_roundup_tts_hourly`)
3. You'll find two automation blocks with the same ID
4. Either:
   - Delete the duplicate automation block entirely, OR
   - Change one automation's `id` to something unique

**Example conflict:**
```yaml
- id: news_roundup_tts_hourly
  alias: "News TTS (morning)"
  ...

- id: news_roundup_tts_hourly   # ← Duplicate! Change this
  alias: "News TTS (evening)"
  ...
```

**Fixed:**
```yaml
- id: news_roundup_tts_hourly_morning
  alias: "News TTS (morning)"
  ...

- id: news_roundup_tts_hourly_evening
  alias: "News TTS (evening)"
  ...
```

---

## 3. Verifying Fixes

After making changes:

1. Validate configuration: **Settings → System → Check Configuration**
2. Reload automations: **Developer Tools → YAML → Reload Automations**
3. Check logs: **Settings → System → Logs**

If using File Editor add-on, you can edit files directly. Otherwise use VS Code or another editor.
