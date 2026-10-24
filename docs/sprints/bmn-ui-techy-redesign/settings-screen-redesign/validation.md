# validation: settings-screen-redesign (coder)

Design checklist from the plan: all items implemented against the pinned dep contracts; none verified in a browser (coder runs no browser).
Not verified: the Settings board visuals, the assumed TopBar/ConfirmDialog prop names, dirty-border `--halo` token (owned by glass-theme-shell).
Gates: eslint clean. tsc fails only on dep-owned modules/types (glass-theme-shell components, `ConfigGroupOut`, `McpStatusOut`, `McpTestOut`, ConfigEntry extra fields) until those merge and `npm run api:sync` runs.
Deviation: conflict state headline is generic ("Someone saved a newer version first") because staging does not keep the current version number.
