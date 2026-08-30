UniSQ Betterbird Folder Sync

1. Copy the updated unisq-mail-sync.py to ~/scripts/mail/unisq-mail-sync.py.
2. Run install.sh.
3. With Betterbird closed, run:
   ~/scripts/mail/unisq-mail-sync.py --apply-filters
4. Start Betterbird.
5. In Add-ons and Themes, use Debug Add-ons / Load Temporary Add-on and
   select extension/manifest.json.
6. The helper creates missing folders and never deletes folders.
7. Check ~/.local/share/unisq-mail-sync/folder-status.json for status.
