import { browser } from '$app/environment';
import type { AffectsDag } from './api';

const STORAGE_PREFIX = 'mandarin_tools_word_draft:';
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

export interface UserWordFieldsDraft {
	pronunciation: string;
	meaning: string;
	notes: string;
	affectsDag: AffectsDag | null;
}

export interface WordPanelDraft {
	newSentenceDraft: string;
	editingNote: boolean;
	noteDraft: string;
	uwAddingGlobal: boolean;
	uwAddingText: boolean;
	uwAddingAnalysis: boolean;
	uwNewDraft: UserWordFieldsDraft;
	uwEditingIds: number[];
	uwDrafts: Record<number, UserWordFieldsDraft>;
}

// The other half of panelWordPersistence.ts's mobile-reload recovery (see
// its docstring) - this half recovers WHAT was being typed/pasted into a
// word's "+ Add entry"/"Edit" forms (and the note/sample-sentence drafts),
// not just which word's panel was open. Keyed per word (not a single slot)
// so switching between two words mid-edit doesn't clobber either draft -
// see WordDetailPanel.svelte's own load()/persistence $effect for how
// these get restored/saved.
//
// Deliberately does NOT get cleared just because the panel is dismissed
// without an explicit Save/Cancel (e.g. tapping the backdrop, or a mobile
// reload happening again before the user finishes) - only a real Save or
// Cancel (which reset the underlying $state back to "nothing in
// progress") clears it, plus the MAX_AGE_MS safety net below. This errs
// toward "don't lose what someone typed," even at the cost of an old draft
// silently reappearing if the same word's panel is reopened later in the
// same browser session - considered the better failure mode than the
// reverse (this is the whole feature's reason to exist).
export function saveWordDraft(word: string, draft: WordPanelDraft): void {
	if (!browser) return;
	try {
		sessionStorage.setItem(STORAGE_PREFIX + word, JSON.stringify({ ...draft, savedAt: Date.now() }));
	} catch {
		// e.g. storage disabled/full - the draft just won't survive a reload, no need to surface an error
	}
}

export function clearWordDraft(word: string): void {
	if (!browser) return;
	try {
		sessionStorage.removeItem(STORAGE_PREFIX + word);
	} catch {
		// ignore
	}
}

export function loadWordDraft(word: string): WordPanelDraft | null {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(STORAGE_PREFIX + word);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as WordPanelDraft & { savedAt: number };
		if (Date.now() - parsed.savedAt > MAX_AGE_MS) {
			sessionStorage.removeItem(STORAGE_PREFIX + word);
			return null;
		}
		const { savedAt: _savedAt, ...draft } = parsed;
		return draft;
	} catch {
		return null;
	}
}
