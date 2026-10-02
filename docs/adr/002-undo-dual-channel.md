# ADR-002: Dual-channel undo (SQLite + CSV)

## Status
Accepted

## Context
Renaming mutates hundreds of files on disk. Users need to revert the last
batch and occasionally older batches. A CSV report is already written for
audit (`reporte_renombrado.csv`).

## Decision
1. **Primary**: SQLite history (`logs/undo_history.sqlite`) stores
   `new → original` mappings per folder after each successful rename.
2. **Fallback**: Revert via CSV when no SQLite entry exists for the folder
   (legacy runs, manual CSV edits).
3. **Core helper**: `src/core/rename_report.py` owns CSV path and mapping
   parsing; UI owns SQLite persistence.

## Consequences
- **Easier**: undo works even if the user only has the CSV; mapping is
  defined once in core.
- **Harder**: two code paths must stay consistent on column names; full
  folder-tree undo in CSV mode is slower than SQLite index lookup.
