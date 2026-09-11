import { browser } from '$app/environment';

const STORAGE_KEY_PREFIX = 'mandarin_tools_open_word_panel';
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

// `slot` disambiguates two panels that can both be open on the SAME page at
// once - analyze/[id]/+page.svelte's own results-table panel and the
// ReadingView.svelte component it can toggle to both track their own
// selectedWordForPanel independently, so they need independent storage
// keys (defaulting to 'default' keeps every other single-panel page's call
// sites unchanged).

interface StoredPanelWord {
	word: string;
	path: string;
	savedAt: number;
	// Optional - only analyze/[id]/+page.svelte's swipe-to-navigate ever
	// passes these (see loadOpenWordPanelNeighbors below for why it needs
	// them); every other caller just omits the third saveOpenWordPanel
	// argument and these stay undefined, unread.
	prevWord?: string | null;
	nextWord?: string | null;
}

// Remembers which word's detail panel (WordDetailModal/WordDetailPanel) was
// open on THIS page, across a page reload - see wordDraftPersistence.ts for
// the matching "what was typed" half of this. Exists specifically for
// mobile: backgrounding the tab (e.g. to copy text from another app before
// pasting into a UserWord field) can cause the OS/browser to fully discard
// and reload the page under memory pressure, which wipes
// selectedWordForPanel (plain $state, in-memory only, in each of the 7
// pages that open this modal) and silently closes whatever panel was open.
// There's no way to intercept or prevent that reload from JS - by the time
// this code runs again, it's already a fresh page load - so instead this
// makes the reload's effect on the open panel invisible: whichever word's
// panel was open comes back on its own, and wordDraftPersistence.ts brings
// back whatever was being typed/pasted into it.
//
// sessionStorage, not localStorage - this is disposable "resume where I
// was interrupted" state, not a persistent preference, and shouldn't
// resurrect a panel from a browsing session the user actually ended.
//
// Scoped by pathname (not just "was something open") so a stale entry left
// over from a panel that was open when the user navigated away entirely
// (without explicitly closing it first) doesn't reopen on some unrelated
// page later - restoration only fires when the saved path matches the page
// currently loading, since a same-URL reload (the actual scenario this
// exists for) always preserves the path.
export function saveOpenWordPanel(
	word: string | null,
	slot: string = 'default',
	neighbors?: { prevWord: string | null; nextWord: string | null }
): void {
	if (!browser) return;
	try {
		const key = `${STORAGE_KEY_PREFIX}:${slot}`;
		if (word === null) {
			sessionStorage.removeItem(key);
			return;
		}
		const entry: StoredPanelWord = { word, path: location.pathname, savedAt: Date.now() };
		if (neighbors) {
			entry.prevWord = neighbors.prevWord;
			entry.nextWord = neighbors.nextWord;
		}
		sessionStorage.setItem(key, JSON.stringify(entry));
	} catch {
		// e.g. storage disabled/full - the panel just won't survive a reload, no need to surface an error
	}
}

export function loadOpenWordPanel(slot: string = 'default'): string | null {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(`${STORAGE_KEY_PREFIX}:${slot}`);
		if (!raw) return null;
		const entry = JSON.parse(raw) as StoredPanelWord;
		if (entry.path !== location.pathname) return null;
		if (Date.now() - entry.savedAt > MAX_AGE_MS) return null;
		return entry.word;
	} catch {
		return null;
	}
}

// The swipe-to-navigate neighbor cache's other half (see analyze/[id]/
// +page.svelte's own lastKnownNeighbors docstring for the full picture of
// why this needs to survive a reload, not just live in memory): a word's
// immediate prev/next in the currently-filtered results, refreshed every
// time that word IS found there. Read back on mount so a reload that lands
// with the open word ALREADY filtered out (e.g. an edit made from its own
// panel just before the tab got backgrounded and reloaded) still has
// somewhere to recover its neighbors from - in-memory-only state has
// nothing to fall back to in that case, since this fresh page load never
// itself observed the word while it was still visible.
export function loadOpenWordPanelNeighbors(
	slot: string = 'default'
): { prevWord: string | null; nextWord: string | null } | null {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(`${STORAGE_KEY_PREFIX}:${slot}`);
		if (!raw) return null;
		const entry = JSON.parse(raw) as StoredPanelWord;
		if (entry.path !== location.pathname) return null;
		if (Date.now() - entry.savedAt > MAX_AGE_MS) return null;
		if (entry.prevWord === undefined && entry.nextWord === undefined) return null;
		return { prevWord: entry.prevWord ?? null, nextWord: entry.nextWord ?? null };
	} catch {
		return null;
	}
}
