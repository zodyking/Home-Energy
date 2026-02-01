# Smart Dashboards: Why Updates Don't Show in Home Assistant

If you updated the integration (HACS or manual) and restarted HA but still see the old behavior (Stove Safety tab, 500 on gear icon, camera streams not loading), use these steps.

## 1. Confirm HA is loading the new files

- **HACS:**  
  - HACS → Integrations → Smart Dashboards.  
  - Check **Version** (e.g. 1.0.2). If it still shows 1.0.0, HACS didn’t update.  
  - Click **Redownload** (or **Update**), then **Restart Home Assistant** (full restart, not just “Reload”).

- **Custom repository in HACS:**  
  - HACS → Integrations → ⋮ → Custom repositories.  
  - Ensure Smart Dashboards points to: `https://github.com/zodyking/Smart-Dashboards` and uses the **default branch** (main).

- **Manual install:**  
  - Replace the entire `custom_components/smart_dashboards` folder with the latest from GitHub (all files, including `frontend/*.js` and `manifest.json`).  
  - Then do a **full** Home Assistant restart.

## 2. Force the browser to load new frontend (panels)

The Cameras and Home Energy panels are JavaScript. Browsers often cache them.

- **Hard refresh:**  
  - Open the **Home Energy** or **Cameras** panel, then:  
    - **Windows/Linux:** `Ctrl + Shift + R` or `Ctrl + F5`  
    - **Mac:** `Cmd + Shift + R`
- **Or:** Clear cache for your Home Assistant URL (e.g. in Chrome: DevTools → Application → Clear storage → Clear site data for the HA origin).
- **Or:** Open HA in a **private/incognito** window and check the panels there.

From version 1.0.2 onward, panel URLs include `?v=1.0.2` (etc.), so after a real update and HA restart, a normal refresh should load the new JS.

## 3. Restart Home Assistant fully

- Use **Settings → System → Restart** (full restart), not only “Reload” or closing the browser.  
- After restart, in **Settings → Devices & Services → Smart Dashboards** you should see **Version 1.0.2** (or whatever is in `manifest.json`).

## 4. If the gear icon still gives 500

- Confirm the integration is really updated: version in HA must match the repo (e.g. 1.0.2).  
- Check **Developer Tools → Logs** for a Python traceback when you click the gear; that will show if an old `config_flow.py` is still loaded.

## Summary

1. Update the integration so HA has the new files (HACS Redownload or replace `custom_components/smart_dashboards`).  
2. Full HA restart.  
3. Hard refresh the browser on the Cameras/Home Energy pages (or clear cache / use incognito).  
4. Confirm version in HA matches the repo (e.g. 1.0.2).
