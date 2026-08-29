# Home Maintenance Tracker for Home Assistant

A local, responsive material-history database and home-maintenance scheduler for Home Assistant OS. It uses SQLite, managed attachment storage, Home Assistant Ingress, Companion notifications, QR labels, printable reports, and portable export/import.

The application repository contains no personal data. Its installed demonstration database is fictional and can be removed with one click.

## Recommended installation: GitHub repository

This route makes later updates easier. The GitHub repository can be public because it contains application source only; your database and attachments never go to GitHub.

### 1. Create the repository

1. Extract the delivered ZIP on your computer.
2. Sign into GitHub and create a new **public** repository named `home-maintenance-tracker-ha`.
3. Do not add a GitHub README, license, or `.gitignore` during creation.
4. Upload everything inside the extracted `Home_Maintenance_Tracker` folder so `repository.yaml` is at the root.
5. Commit the files to the default branch. The repository URLs are already configured for the GitHub account `blancstair`.

### 2. Add it to Home Assistant

1. Open Home Assistant through your normal Nabu Casa address.
2. Go to **Settings → Apps → App store**.
3. Open the three-dot menu and select **Repositories**.
4. Paste `https://github.com/blancstair/home-maintenance-tracker-ha` and add it.
5. Open the three-dot menu again and choose **Check for updates**.
6. Find **Home Maintenance Tracker** under the newly added repository and select **Install**.
7. After installation, enable **Start on boot**, **Watchdog**, and **Show in sidebar** if Home Assistant does not enable them automatically.
8. Select **Start**, then **Open web UI** or the **Maintenance** sidebar entry.

The first build can take several minutes because Home Assistant constructs the local container and downloads its Python dependencies.

## Private/local installation alternative

If you do not want the source repository public:

1. Install and start the official Samba app in Home Assistant.
2. From Windows File Explorer, open `\\homeassistant.local\addons`.
3. Copy only the `home_maintenance_tracker` folder into that share.
4. Go to **Settings → Apps → App store**, choose **Check for updates**, and install it from **Local apps**.

This alternative must be updated by replacing the local source folder and incrementing the version in `config.yaml`.

## First-run checklist

1. Browse the fictional sample property and open several equipment records.
2. Go to **Settings → Notifications** and select the Companion devices that should receive reminders.
3. Send the automatic test notification.
4. Create a real top-level item and test an attachment upload.
5. Download a manual full export.
6. Confirm Home Assistant automatic backups include Home Maintenance Tracker.
7. Remove the sample dataset when you no longer need it.

## Updates

For a future release, replace the application files in GitHub, keep your repository-specific URLs, and increment the `version` value in `home_maintenance_tracker/config.yaml`. Home Assistant will then offer the new version after **Check for updates**. Updating does not replace `/data`.

## Recovery

Home Assistant backups are the normal recovery method. The in-app export is intentionally independent: it contains the application database and every managed attachment in a portable ZIP. Import replaces the current application data, so make a current export first.

## Supported architectures

- `amd64` — normal Intel/AMD Home Assistant mini PCs
- `aarch64` — 64-bit ARM Home Assistant systems
