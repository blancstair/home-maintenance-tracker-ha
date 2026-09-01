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

Every active meter can produce a QR label. Version 0.3.0 labels are native Home Assistant tags. On the configured Android device, one scan opens Companion and the meter's individual reading form. The same dialog can download the QR code as an SVG for printing. Meters with no readings or linked tasks can be permanently deleted; meters with history are archived. An active maintenance task must be changed or canceled before its meter can be archived.

## Contextual Help

Select the circled question mark beside any screen or tool title to open the relevant instructions without leaving the current workflow. The **Help** screen provides the complete searchable reference.

## Android single-scan QR setup

1. Open Companion on the Android phone or tablet that will scan labels.
2. In the tracker, open **Settings → Android QR Auto-Open**.
3. Select that device and choose **Save and Test**.
4. Android opens the special-access screen. Grant Home Assistant **Display over other apps** permission.
5. Return to the tracker and scan a newly generated label.

The QR contains `https://www.home-assistant.io/tag/<random tag>` so Android routes it to Companion and Home Assistant fires `tag_scanned`. The tracker stores the selected destination for 90 seconds, sends `command_webview` to the configured Android device, opens the stable tracker panel, and consumes the destination internally. It does not depend on the PC address, Nabu Casa URL, or an Ingress query string. The label contains no hostname, record ID, or credentials.

Regenerate every asset and meter label printed before version 0.3.0. Android is the supported one-scan workflow; Apple devices are not configured for automatic opening in this release.

## Troubleshooting

- **App does not appear:** In Settings → Apps → App store, select the three-dot menu and **Check for updates**, then refresh the browser.
- **Build fails:** Confirm the mini PC has internet access and inspect the app build log. The first installation downloads the Home Assistant base image and the pinned Python packages.
- **No phones listed:** Open or restart Home Assistant Companion on the phone and verify a `notify.mobile_app_*` action exists in Developer Tools.
- **QR does not open the record:** Confirm version 0.3.0 is installed, select the scanning Android device under **Android QR Auto-Open**, run **Save and Test**, grant **Display over other apps**, and regenerate the label. Check the app log for `QR tag listener disconnected` if the scan appears in Home Assistant but the tracker does not open.
- **Tablet sidebar does not minimize:** Update to version 0.2.2 or later and reopen the app. Versioned assets and no-cache headers ensure Companion loads the corrected control. Phone layouts use bottom navigation instead.
- **Import is rejected:** Only unmodified export ZIPs from this app are accepted.
- **Video backup is too large:** Remove or compress large videos, download a manual export, or adjust the selected Home Assistant backup destination.
