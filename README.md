# Home Maintenance Tracker for Home Assistant

Home Maintenance Tracker is a local material-history database and preventive-maintenance scheduler for Home Assistant OS. It tracks properties, vehicles, appliances, systems, components, manuals, service history, meter readings, recurring work, replacement records, costs, and attachments.

The application uses a responsive dashboard, a searchable asset hierarchy, SQLite storage, Home Assistant Ingress, Companion notifications, printable reports, QR labels, dark mode, and manual export/import. Its included demonstration data is fictional and contains no names or personally identifiable information.

## Requirements

- Home Assistant Operating System with access to **Settings → Apps**
- An `amd64` Intel/AMD system or an `aarch64` 64-bit ARM system
- Internet access while installing or updating the application
- A supported browser or the Home Assistant Companion app
- For automatic single-scan QR opening: Home Assistant Companion on Android and permission to display over other apps

The tracker runs on the Home Assistant system. A separate server, NAS, Microsoft Access installation, or continuously running desktop computer is not required.

## Installation

1. Open Home Assistant.
2. Go to **Settings → Apps → App store**.
3. Open the three-dot menu and select **Repositories**.
4. Add this repository:

   ```text
   https://github.com/blancstair/home-maintenance-tracker-ha
   ```

5. Close the repository dialog.
6. Open the three-dot menu again and select **Check for updates**.
7. Find **Home Maintenance Tracker** in the App store and open it.
8. Select **Install**. The first build may take several minutes while Home Assistant downloads and builds the required components.
9. When installation finishes, enable:

   - **Start on boot**
   - **Watchdog**
   - **Show in sidebar**

10. Select **Start**, then open **Maintenance** from the Home Assistant sidebar or select **Open web UI**.

## First-Run Setup

The initial database contains a large fictional property, equipment hierarchy, maintenance schedule, meter history, and service records. Use these records to explore the application without entering personal information.

Recommended first steps:

1. Browse several sample items under **Assets**.
2. Open **Maintenance** and review the agenda, calendar, and dense-table views.
3. Open **Meter Readings** and test individual and bulk reading entry.
4. Go to **Settings → Notifications** and select any registered Home Assistant Companion devices that should receive reminders.
5. On the Android device that will scan labels, complete **Settings → Android QR Auto-Open** as described below.
6. Create a real item and attach a test document.
7. Download a manual export from **Settings**.
8. Confirm Home Assistant backups include Home Maintenance Tracker.
9. Remove the fictional sample data from **Settings** when it is no longer needed.

Removing the sample data does not remove records created by the user. The sample dataset can be reinstalled later.

## Navigation and Display

The primary sidebar provides access to Dashboard, Assets, Maintenance, Meter Readings, Reports, Help, and Settings.

- Select or tap the sidebar collapse button to switch to an icon-only navigation rail on computers and tablets.
- Hover over or focus a collapsed icon to display its destination.
- Use the theme button in the upper-right corner to switch between light and dark mode.
- On phones, use the bottom navigation bar.
- Select the circled question mark beside a screen or tool title to open contextual instructions.
- Use the searchable **Help** screen for the complete operating reference.

Display preferences are remembered by the browser being used.

## Assets and Material History

An asset is any property, vehicle, appliance, system, component, part, or other item that should retain an individual history.

### Create an Item

1. Open **Assets**.
2. Select **Add Item**.
3. Enter the required item name.
4. Select a parent item or leave the item at the top level.
5. Add only the standardized fields needed for the record.
6. Select **Create Item**.

Available optional fields include category/type, manufacturer, model number, serial number, part number, lot number, asset/tag number, physical location, purchase date, in-service date, vendor/installer, and warranty expiration.

The hierarchy supports unlimited nesting. Each item has no more than one parent but can have any number of children. For example:

```text
Property
└── Garage
    └── Vehicle
        └── Engine
            └── Oil Filter
```

### Move an Item

In the tree view, drag an item onto its new parent. The application prevents circular relationships. Remarks, maintenance tasks, meters, attachments, and history remain with the moved item.

### Remarks

Use **Remark** on an item to record:

- Preventive maintenance
- Corrective maintenance
- Observations

The entry timestamp is automatic. The work date can be selected separately. Remarks may be edited, deleted, and given their own attachments.

### Manuals and Attachments

Use **Upload** to attach manuals, receipts, warranty documents, diagrams, photographs, videos, service records, or other files. Each attachment belongs to one exact item, remark, maintenance task, or completion record.

Files are copied into managed application storage. Moving or deleting the original file on another device will not break the stored attachment. Large videos will increase backup and export size.

### Archive, Replace, Restore, or Delete

Use an item's **Actions** menu for lifecycle operations.

- **Archive** retains the complete record and is the normal method for removing an item from active use.
- **Replace** archives the old item, creates a linked replacement in the same location, and allows selected children and maintenance plans to transfer.
- **Restore** returns an archived item to active use.
- **Delete permanently** removes the item and its retained history and cannot be undone.

When archiving a parent, every active child must be moved or archived. The application presents the children for individual selection.

## Maintenance Tasks

Maintenance tasks may be assigned to one exact item or left unassigned as a general task.

### Supported Schedule Types

- One-time date
- Recurring calendar interval in days, weeks, months, or years
- Runtime, mileage, cycles, counts, volume, energy, or mass
- Calendar and meter threshold, using whichever comes first or last
- Seasonal schedule
- Specific calendar pattern
- Condition-based or manual trigger

Recurring maintenance normally calculates its next due point from the actual completion date or reading. Seasonal and patterned schedules remain anchored to their specified calendar pattern.

### Create a Task

1. Open **Maintenance** and select **Add Task**, or create the task from an item's Maintenance section.
2. Enter the task title and optional description.
3. Select the associated item if applicable.
4. Choose the schedule basis.
5. Enter the required interval, meter, date, or calendar pattern.
6. Optionally enter estimated duration and planned cost.
7. Select **Create Task**.

Meter-based schedules list only active meters belonging to the selected item. If none exist, the meter selector displays **No meters configured for this item**.

### Complete a Task

1. Select the task and choose **Complete**.
2. Confirm the work date and outcome.
3. Enter an applicable meter reading.
4. Enter optional labor time, total cost, and materials used.
5. Review or edit the generated material-history remark.
6. Select **Approve & Complete**.

An approved completion creates or updates the associated item's material-history remark. The completion remains editable without maintaining a separate revision audit trail.

Use **⇧ Completed by higher authority** when corrective work or component replacement satisfies an ordinary inspection or maintenance requirement. This outcome links the corrective or replacement item and resets the ordinary maintenance periodicity.

A skipped task requires a reason. The completion form controls whether the skipped occurrence advances the schedule.

### Snooze and Escalation

Snoozing delays ordinary reminders without changing the recurring schedule. A task turns red when it passes 1.5 times its normal periodicity. Snoozing cannot conceal this escalation state.

## Meter Readings

Meters retain timestamped running totals and support maintenance forecasting. Examples include vehicle mileage, generator runtime, appliance cycles, equipment starts, water volume, or energy consumption.

### Standard Meter Types and Units

| Type | Available units |
|---|---|
| Distance / mileage | miles, kilometers, nautical miles |
| Runtime | hours, minutes |
| Counts / cycles | cycles, starts, uses, loads, operations |
| Volume | US gallons, Imperial gallons, liters, cubic feet, cubic meters |
| Energy | kWh, MWh, therms, BTU, megajoules |
| Mass | pounds, kilograms |

Use one consistent unit for each meter. Changing a unit does not convert earlier readings or linked maintenance thresholds.

### Create a Meter

A meter can be created from an item's Meters section or from **Meter Readings → New Meter**. Select the associated item, meter name, type, and unit. An optional initial reading and timestamp can be recorded during creation.

### Enter Readings

- Select **Update** on a meter row to enter one reading.
- Select **Update Readings** to enter multiple readings at the same timestamp. Blank rows are ignored.
- Scan a meter's QR label to open its individual quick-entry form.
- A new running-total reading cannot be lower than a prior reading.

With sufficient timestamped history, the tracker estimates usage rate, remaining usage, and the projected date of meter-based maintenance. Actual maintenance remains governed by the configured meter threshold.

### Meter QR Labels

Select **QR** on a meter row to display its label. On the configured Android device, one scan launches Home Assistant Companion and opens that meter's individual reading form. Select **Download QR Code** to save an SVG that can be printed from the browser.

Version 0.3.0 labels use a native Home Assistant tag URL with a random opaque identifier. They do not contain a Home Assistant hostname, local IP address, Nabu Casa address, asset or meter ID, or credentials. Regenerate every item and meter label created before version 0.3.0.

### Configure Android Single-Scan Opening

The Android workflow deliberately avoids sending an asset or meter through an Ingress path, query string, or fragment. Home Assistant normalizes app-panel navigation to the tracker root, which caused earlier labels to open the Dashboard or return a 404. Version 0.3.0 transfers the record destination internally instead.

1. Install, connect, and open Home Assistant Companion on the Android phone or tablet that will scan labels.
2. In Home Maintenance Tracker, open **Settings → Android QR Auto-Open**.
3. Select that Android device, then choose **Save and Test**.
4. The first test opens Android's special-access settings. Allow Home Assistant to **Display over other apps**.
5. Return to Home Assistant and confirm the test opens the tracker.
6. Generate a new item or meter QR code and scan it with that Android device.

During a scan:

1. Android recognizes the standard `https://www.home-assistant.io/tag/...` address and sends a `tag_scanned` event to Home Assistant.
2. The tracker matches the opaque tag to one item or meter and stores that destination for up to 90 seconds.
3. The tracker sends Android Companion a `command_webview` request to open the tracker's stable Home Assistant panel.
4. The Android WebView consumes the pending destination and opens the exact item or individual meter-reading form.

Only one Android Companion device is configured as the automatic target. Select the Android device that you intend to use for scanning. If **Display over other apps** is denied, the tag event still reaches Home Assistant but Android cannot complete automatic one-scan opening. Apple devices do not support this automatic workflow in version 0.3.0.

### Manage a Meter

- Edit the meter name, type, or unit with **Edit**.
- Permanently delete a meter only when it has no readings or linked tasks.
- Archive a meter that has retained history.
- Change or cancel active maintenance tasks before archiving their meter.
- Restore an archived meter when it returns to service.

Archived meters remain available in reports and history but are excluded from new maintenance-task and reading-entry selections.

## Dashboard, Calendar, and Reports

The Dashboard shows escalated tasks, overdue work, tasks approaching within the selected planning window, active items, recent completions, and upcoming warranty dates. Change the planning window under **Settings → Dashboard Window**.

Maintenance can be reviewed as an action-oriented agenda, monthly calendar, or dense database-style table.

Available reports include:

- Upcoming maintenance
- Overdue maintenance
- Complete service history
- Material hierarchy
- Archived and replaced items
- Warranty expiration
- Maintenance cost
- Parts and materials used
- Meter-reading history

Run the selected report, then choose **Print / Save PDF**. Navigation and screen controls are removed from printed output.

## Home Assistant Companion Notifications

1. Install and open the Home Assistant Companion app on every desired device.
2. Open **Settings → Notifications** in Home Maintenance Tracker.
3. Select the registered devices that should receive reminders.
4. Choose the daily notification check hour.
5. Save the selection. A test notification is sent to selected services.

The tracker sends overdue notifications using a cadence based on task periodicity. Red escalation reminders cannot be suppressed by snoozing.

If no devices appear, open or restart the Companion app and verify that its `notify.mobile_app_*` action exists in Home Assistant.

## Data Storage, Backups, and Transfer

The SQLite database and managed attachments are stored in the application's persistent Home Assistant `/data` directory. Application updates do not replace this directory.

Use both forms of protection:

1. Include Home Maintenance Tracker in scheduled Home Assistant backups.
2. Periodically select **Settings → Download Full Export** and keep the downloaded ZIP on another device.

The manual export contains the database, attachments, and an export manifest. It can transfer the tracker independently of a complete Home Assistant restoration.

### Manual Import

1. Open **Settings → Manual Import**.
2. Select an unmodified export ZIP created by Home Maintenance Tracker.
3. Select **Import and Replace**.
4. Confirm the warning and allow the application to reload.

Import replaces the current tracker database and attachments. Download a current export first if the existing data may be needed later.

## Updating

1. Create a current Home Assistant backup or manual tracker export.
2. Open **Settings → Apps → App store**.
3. Open the three-dot menu and select **Check for updates**.
4. Return to the installed **Home Maintenance Tracker** app page.
5. Select **Update** when a newer version is available.
6. Start the application if it does not restart automatically.
7. Open the tracker and verify the displayed version number.

If the updated version is not detected, refresh the App store, run **Check for updates** again, and confirm the custom repository remains configured.

## Uninstallation

Download a manual export before uninstalling the application. Removing the application and its stored data may permanently remove the database and managed attachments. The GitHub repository can be removed separately from the App store's **Repositories** dialog if updates and reinstallation are no longer wanted.

## Troubleshooting

### Application Does Not Appear

- Confirm the repository URL was entered correctly.
- Run **Check for updates** from the App store menu.
- Refresh the browser.
- Confirm the Home Assistant system uses Home Assistant OS.

### Installation or Build Fails

- Confirm the Home Assistant system has internet access.
- Review the application build log.
- Retry after confirming adequate free disk space.

### Updated Application Shows the Old Interface

- Perform a hard browser refresh.
- Fully close and reopen the Home Assistant Companion app.
- Confirm the installed application page shows the expected version.

### No Meters Appear in a Maintenance Task

- Select the task's associated item first.
- Confirm an active meter exists on that exact item.
- Create the meter from the item record or Meter Readings screen.
- Archived meters cannot be assigned to active tasks.

### A Meter Cannot Be Archived

Open every active maintenance task using that meter and reassign, change, or cancel the task. The meter can then be archived without losing its readings.

### QR Code Does Not Open the Record

- Confirm the tracker shows version 0.3.0 or later.
- Confirm the Android device appears under **Settings → Android QR Auto-Open** and is selected.
- Run **Save and Test** again and grant Home Assistant **Display over other apps** permission.
- Confirm the test opens the tracker before testing a label.
- Regenerate the label; every pre-0.3.0 QR code contains the obsolete routing format.
- In Home Assistant's Tags panel, confirm the scan appears. If it does but the tracker does not open, review the Home Maintenance Tracker app log for a disconnected QR tag listener.
- Confirm Android is routing `www.home-assistant.io/tag` links to Home Assistant Companion rather than a web browser.

### Sidebar Does Not Minimize on a Tablet

Confirm the installed application is version 0.2.2 or later and reopen Home Assistant Companion. If Chrome shows the new interface but Companion does not, Android may have retained a mixed-version Ingress frontend. Clearing ordinary cache may be insufficient; clear Home Assistant Companion's app data, sign in again, and reopen the tracker. On phone-sized screens, the desktop sidebar is intentionally replaced by bottom navigation.

### Import Is Rejected

Only unmodified export ZIPs created by Home Maintenance Tracker are accepted. Verify the file was not extracted, recompressed, or edited.

### Backup or Export Is Too Large

Review stored video attachments. Large videos can substantially increase Home Assistant backup and manual-export size.

## Privacy and Remote Access

Records and attachments remain on the Home Assistant system unless included in a configured Home Assistant backup destination or manually exported. The application repository contains source code and fictional sample records, not the user's installed database.

Home Assistant Ingress uses the existing Home Assistant authentication session. When Home Assistant is accessed through Nabu Casa, the tracker is available through that same authenticated connection.

## Version

Current release: **0.3.0**

See [`home_maintenance_tracker/CHANGELOG.md`](home_maintenance_tracker/CHANGELOG.md) for release details.

## License

This project is distributed under the MIT License. See [`LICENSE`](LICENSE).
