# Changelog

## 0.2.1

- Changed item and meter QR labels to launch Home Assistant Companion on Android and Apple devices and navigate to the exact record.
- Added default-server routing without embedding a Home Assistant address or credentials in printed labels.
- Fixed sidebar minimization on tablet touchscreens with explicit pointer handling, a larger touch target, and resilient preference storage.
- Added regression coverage for Companion deep links and touch/click sidebar behavior.
- Documented label regeneration and tablet troubleshooting.

## 0.2.0

- Fixed Cancel and X controls being blocked by required-field validation in dialogs.
- Added standardized imperial and metric meter units selected from type-specific lists.
- Added meter creation from the Meter Readings screen, including an optional initial reading.
- Added individual meter updates while preserving the existing multi-meter update workflow.
- Added meter editing, safe permanent deletion, archival, restoration, and active-task safeguards.
- Added printable per-meter QR labels that open the individual reading workflow.
- Added a clear **No meters configured for this item** task-scheduling state.
- Added an icon-only collapsible sidebar with labels on hover/focus and remembered preference.
- Standardized screen and Dashboard section headings in Title Case.
- Added contextual Help buttons for every screen and tool plus a searchable master Help reference.
- Added automated meter-lifecycle, QR, dialog-cancellation, and Help-coverage tests.

## 0.1.0

- Initial release.
- Unlimited material-history hierarchy with drag-and-drop movement.
- Managed manuals, receipts, warranties, diagrams, photos, videos, and service records.
- Calendar, meter, seasonal, patterned, condition, and combined maintenance schedules.
- Approved 1.5× escalation and repeating reminder cadence.
- Guided replacement, archival, restoration, and permanent deletion workflows.
- Meter forecasting, maintenance completion drafts, materials used, reports, and PDF printing.
- Companion notification target selection, Nabu Casa-compatible Ingress, QR labels, and dark/mobile layouts.
- Home Assistant backups plus application-level full export/import.
- Large removable fictional sample dataset with no personal information.
