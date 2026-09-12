import { browser } from '$app/environment';
import { tick } from 'svelte';

const STORAGE_PREFIX = 'mandarin_tools_reading_view:';

// Remembers, per analysis, whether reading view (rather than the results
// table) was the active mode, and where the page was scrolled to within it
// - together, what "leave the app and come back to right where I was
// reading" needs.
//
// localStorage, not sessionStorage - deliberately different from this
// app's usual "resume where I was interrupted" family (panelWordPersistence.ts,
// scrollPersistence.ts, wordDraftPersistence.ts), all of which use
// sessionStorage specifically so they DON'T resurrect state from a browsing
// session the user actually ended. This is the one case that's supposed to:
// the request this was built for is explicitly "I leave the app and come
// back" (closing the tab/browser entirely, possibly much later), which
// sessionStorage doesn't survive. readingViewOn and the scroll position
// have to share this same durability - reopening reading view automatically
// but landing back at the top would defeat half the point.
//
// Keyed by analysisId (not pathname, unlike scrollPersistence.ts) - a
// plain number is a more direct, less brittle key than string-matching a
// route, and reading view is already analysis-centric everywhere else
// (see ReadingView.svelte's own docstring).

function onKey(analysisId: number): string {
	return `${STORAGE_PREFIX}${analysisId}:on`;
}
function scrollKey(analysisId: number): string {
	return `${STORAGE_PREFIX}${analysisId}:scroll`;
}

export function loadReadingViewOn(analysisId: number): boolean {
	if (!browser) return false;
	try {
		return localStorage.getItem(onKey(analysisId)) === '1';
	} catch {
		return false;
	}
}

export function saveReadingViewOn(analysisId: number, on: boolean): void {
	if (!browser) return;
	try {
		if (on) localStorage.setItem(onKey(analysisId), '1');
		else localStorage.removeItem(onKey(analysisId));
	} catch {
		// e.g. storage disabled/full - reading view just won't reopen on its own next time
	}
}

function saveScrollPosition(analysisId: number, y: number): void {
	if (!browser) return;
	try {
		localStorage.setItem(scrollKey(analysisId), String(Math.round(y)));
	} catch {
		// e.g. storage disabled/full - scroll position just won't be remembered
	}
}

function loadScrollPosition(analysisId: number): number | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(scrollKey(analysisId));
		if (raw === null) return null;
		const n = Number(raw);
		return Number.isFinite(n) ? n : null;
	} catch {
		return null;
	}
}

// Same shape as scrollPersistence.ts's trackScrollPosition (coalesced to at
// most once per animation frame) - call from an $effect and let its own
// cleanup-on-rerun/unmount convention pick up the returned function:
//   $effect(() => trackReadingViewScroll(analysisId));
export function trackReadingViewScroll(analysisId: number): () => void {
	if (!browser) return () => {};
	let ticking = false;
	const onScroll = () => {
		if (ticking) return;
		ticking = true;
		requestAnimationFrame(() => {
			saveScrollPosition(analysisId, window.scrollY);
			ticking = false;
		});
	};
	window.addEventListener('scroll', onScroll, { passive: true });
	return () => window.removeEventListener('scroll', onScroll);
}

// Applies a saved scroll position once reading view's content has actually
// loaded - restoring before then would scroll to a position the
// still-loading spans don't have the height for yet. `await tick()` waits
// for Svelte's pending DOM update (the just-loaded spans) to apply before
// the requestAnimationFrame measures/sets scroll. Call right after spans
// arrive (e.g. inside an $effect gated on `loading` turning false), not
// eagerly on mount - see ReadingView.svelte's own use of this.
export async function restoreReadingViewScroll(analysisId: number): Promise<void> {
	const saved = loadScrollPosition(analysisId);
	if (saved === null) return;
	await tick();
	requestAnimationFrame(() => window.scrollTo(0, saved));
}
