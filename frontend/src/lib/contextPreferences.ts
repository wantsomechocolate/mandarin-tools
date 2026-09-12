import { browser } from '$app/environment';

// How many characters of surrounding text GET /analyze/{id}/context/{word}
// (and its frontend callers - the results-row/card accordion and
// WordDetailPanel's own Context section) shows on each side of a match.
// One global preference, not per-word/per-analysis - "I like more
// surrounding context" is a standing reading preference the same way
// colorBy (ReadingView.svelte) or the section-visibility defaults
// (sectionVisibilityPersistence.ts) are, so localStorage, configured from
// /profile's Preferences section alongside those.
const STORAGE_KEY = 'mandarin_tools_context_chars';

// Matches the backend's own default (context_chars=15, get_word_context's
// signature, router.py) - kept here too so a never-touched preference and
// an explicitly-set-back-to-15 one are indistinguishable, which is fine
// since there's nothing scoped that would need to tell them apart (unlike
// sectionVisibilityPersistence.ts's per-word overrides).
const DEFAULT_CONTEXT_CHARS = 15;
const MIN_CONTEXT_CHARS = 5;
const MAX_CONTEXT_CHARS = 60;

export function getContextChars(): number {
	if (!browser) return DEFAULT_CONTEXT_CHARS;
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw === null) return DEFAULT_CONTEXT_CHARS;
		const n = Number(raw);
		if (!Number.isFinite(n)) return DEFAULT_CONTEXT_CHARS;
		return Math.min(MAX_CONTEXT_CHARS, Math.max(MIN_CONTEXT_CHARS, Math.round(n)));
	} catch {
		return DEFAULT_CONTEXT_CHARS;
	}
}

export function setContextChars(chars: number): void {
	if (!browser) return;
	try {
		const clamped = Math.min(MAX_CONTEXT_CHARS, Math.max(MIN_CONTEXT_CHARS, Math.round(chars)));
		localStorage.setItem(STORAGE_KEY, String(clamped));
	} catch {
		// e.g. storage disabled/full - the preference just won't stick, no need to surface an error
	}
}

export { DEFAULT_CONTEXT_CHARS, MIN_CONTEXT_CHARS, MAX_CONTEXT_CHARS };
