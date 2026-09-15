import { getPreference, setPreference } from './api';

// Account-level settings for the tokenizer's repeated-sequence pass
// (Account page's "Advanced" card) - backend-persisted (key
// "repeated_sequence", via the generic app.modules.preferences mechanism),
// same pattern as exportPreferences.ts. Deliberately NOT surfaced as a
// per-analysis option (analyze/+page.svelte, input-texts/[id]/+page.svelte)
// - these are account-wide defaults applied to every future analysis, not
// something to reconsider each time.
export interface RepeatedSequencePreferences {
	minTokenLength: number;
	minTokenCount: number;
}

// Mirrors the backend's own AnalyzeTextRequest/Analysis model defaults
// (schemas.py/models.py) - applied whenever the backend has no
// "repeated_sequence" row yet for this user.
export const DEFAULT_REPEATED_SEQUENCE_PREFERENCES: RepeatedSequencePreferences = {
	minTokenLength: 2,
	minTokenCount: 2,
};

export async function loadRepeatedSequencePreferences(): Promise<RepeatedSequencePreferences> {
	const { value } = await getPreference<Partial<RepeatedSequencePreferences>>('repeated_sequence');
	if (!value) return DEFAULT_REPEATED_SEQUENCE_PREFERENCES;
	return { ...DEFAULT_REPEATED_SEQUENCE_PREFERENCES, ...value };
}

export async function saveRepeatedSequencePreferences(prefs: RepeatedSequencePreferences): Promise<void> {
	await setPreference('repeated_sequence', prefs);
}
