# Architecture Decision Records

| ADR | Title |
|-----|--------|
| [001](001-modular-monolith.md) | Modular monolith (`core` + `ui_qt`) |
| [002](002-undo-dual-channel.md) | Dual-channel undo (SQLite + CSV) |
| [003](003-qt-worker-boundary.md) | Qt workers for long-running work |
| [004](004-spatial-index-and-session-extraction.md) | Spatial index for nearest-PK and Qt-free session/recents extraction |
| [005](005-calibrated-chainage.md) | Calibrated linear referencing, corridor distance, coverage QA |
| [006](006-analysis-hot-path-indexing.md) | One directory listing per folder, one point partition per KML |
| [007](007-trace-relative-coverage.md) | Coverage against the trace, cadence-aware gap threshold |
| [008](008-lxml-only-kml-and-dependency-contract.md) | lxml as the only KML parser, dependency assumptions under test |
| [009](009-virtual-telemetry-frames.md) | Telemetry frames are analysis evidence, not rename targets |

New decisions: add the next numbered file using the template in `.cursor/rules/software-architect.mdc`.
