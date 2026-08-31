# Home Maintenance Tracker

Open the app from the **Maintenance** entry in the Home Assistant sidebar. The first-run guide explains the sample records and notification setup. Complete operating instructions are available on the app's **Help** page.

## App option

`max_upload_mb` sets the maximum size of one uploaded attachment. The default is 250 MB. Increasing this also increases the possible size of Home Assistant backups and manual exports.

## Data protection

The SQLite database and managed attachments live in the app's persistent `/data` directory. The app uses a cold-backup configuration so Home Assistant stops it briefly while copying its data.

Use both of these protections:

1. Include **Home Maintenance Tracker** in scheduled Home Assistant backups.
2. Periodically open **Settings → Manual export** and keep the downloaded ZIP on another device.

## Notifications

The app discovers `notify.mobile_app_*` services registered by Home Assistant Companion. Open the Companion app once on every desired device before selecting devices in **Settings → Notifications**.

The app checks once daily at the configured hour. It sends only overdue reminders, using the recurrence-based cadence documented in Help. Red escalation cannot be hidden by snoozing.

## Meter management

Create meters from an item record or directly from **Meter Readings → New Meter**. Meter units come from standardized type-specific lists. Use the row-level **Update** action for one meter or **Update Readings** for several meters at once.

Every active meter can produce a QR label. Scanning it launches Home Assistant Companion on Android or Apple devices and opens that meter's individual reading form. The same dialog can download the QR code as an SVG for printing. Meters with no readings or linked tasks can be permanently deleted; meters with history are archived. An active maintenance task must be changed or canceled before its meter can be archived.

## Contextual Help

Select the circled question mark beside any screen or tool title to open the relevant instructions without leaving the current workflow. The **Help** screen provides the complete searchable reference.

## Nabu Casa and QR labels

Ingress uses your existing Home Assistant authentication. If you open Home Assistant through Nabu Casa, the app works inside that same connection. QR labels use a `homeassistant://navigate` Companion deep link with the stable app-panel route rather than a desktop web address or temporary Ingress session address. Companion chooses the connection configured on the scanning device. The label contains no hostname or credentials. Regenerate labels printed by version 0.2.0 or 0.2.1 after updating.

## Troubleshooting

- **App does not appear:** In Settings → Apps → App store, select the three-dot menu and **Check for updates**, then refresh the browser.
- **Build fails:** Confirm the mini PC has internet access and inspect the app build log. The first installation downloads the Home Assistant base image and three pinned Python packages.
- **No phones listed:** Open or restart Home Assistant Companion on the phone and verify a `notify.mobile_app_*` action exists in Developer Tools.
- **QR opens a browser, connection error, or wrong screen:** Confirm Companion is installed and connected to Home Assistant, update to 0.2.2 or later, and regenerate any label made by an earlier version.
- **Tablet sidebar does not minimize:** Update to version 0.2.2 or later and reopen the app. Versioned assets and no-cache headers ensure Companion loads the corrected control. Phone layouts use bottom navigation instead.
- **Import is rejected:** Only unmodified export ZIPs from this app are accepted.
- **Video backup is too large:** Remove or compress large videos, download a manual export, or adjust the selected Home Assistant backup destination.
