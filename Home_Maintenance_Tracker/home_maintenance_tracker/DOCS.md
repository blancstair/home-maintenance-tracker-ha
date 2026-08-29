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

## Nabu Casa and QR labels

Ingress uses your existing Home Assistant authentication. If you open Home Assistant through Nabu Casa, the app works inside that same connection. QR labels use the stable Home Assistant app-panel route rather than a temporary Ingress session address. Generate labels while using the Home Assistant address that the phone should later open. The scanning phone must be signed into Home Assistant.

## Troubleshooting

- **App does not appear:** In Settings → Apps → App store, select the three-dot menu and **Check for updates**, then refresh the browser.
- **Build fails:** Confirm the mini PC has internet access and inspect the app build log. The first installation downloads the Home Assistant base image and three pinned Python packages.
- **No phones listed:** Open or restart Home Assistant Companion on the phone and verify a `notify.mobile_app_*` action exists in Developer Tools.
- **QR opens a sign-in page:** Sign into the same Home Assistant/Nabu Casa address and scan again.
- **Import is rejected:** Only unmodified export ZIPs from this app are accepted.
- **Video backup is too large:** Remove or compress large videos, download a manual export, or adjust the selected Home Assistant backup destination.
