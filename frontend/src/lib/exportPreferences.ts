import { getPreference, setPreference } from './api';

// Account-level settings for the Pleco-export feature (Account page's
// "Export (Pleco)" card, ExportDialog.svelte) - backend-persisted (key
// "export", via the generic app.modules.preferences mechanism), NOT
// localStorage like this app's other preferences (theme, word-detail-panel
// section defaults, context length) - see api.ts's getPreference/
// setPreference docstring. This is the first *async* preference in the
// app: every consumer fetches fresh on its own mount (loadExportPreferences)
// rather than sharing cross-page reactive state, matching this codebase's
// existing "resolve fresh on read" habit elsewhere (is_hidden/is_garbage/
// evidence_tier, etc.) rather than inventing a caching layer for something
// that's cheap to just re-fetch.
export interface ExportPreferences {
	includePinyin: boolean;
	includeDefinitions: boolean;
	definitionSources: {
		corpusFrequency: boolean;
		hsk: boolean;
		cedict: boolean;
		userGlobal: boolean;
		userText: boolean;
		userAnalysis: boolean;
	};
}

// Only applied when the backend has no "export" row yet for this user (a
// first-ever visit) - everything on, so the feature is immediately useful
// without a trip to the Account page first. Once any row exists, whatever
// it holds is used as-is, never merged with these.
export const DEFAULT_EXPORT_PREFERENCES: ExportPreferences = {
	includePinyin: true,
	includeDefinitions: true,
	definitionSources: {
		corpusFrequency: true,
		hsk: true,
		cedict: true,
		userGlobal: true,
		userText: true,
		userAnalysis: true,
	},
};

export async function loadExportPreferences(): Promise<ExportPreferences> {
	const { value } = await getPreference<ExportPreferences>('export');
	return value ?? DEFAULT_EXPORT_PREFERENCES;
}

export async function saveExportPreferences(prefs: ExportPreferences): Promise<void> {
	await setPreference('export', prefs);
}
