import { browser } from '$app/environment';
import { tick } from 'svelte';

const STORAGE_PREFIX = 'mandarin_tools_scroll:';

// Restores the page's scroll position across a page reload - same
// motivation as panelWordPersistence.ts (mobile backgrounding can cause
// the OS/browser to discard and reload the page, wiping everything
// including scroll position), but for scroll instead of "which word's
// panel was open." SvelteKit has its own scroll restoration, but it only
// reapplies on SvelteKit's own client-side navigations (back/forward,
// goto) - a hard reload of the current URL from the OS discarding the
// page isn't one of those, so nothing SvelteKit already does covers it.
//
// sessionStorage, keyed by the exact pathname (not a fixed key) - so e.g.
// analyze/103 and analyze/104 each remember their own scroll position
// independently, the same way panelWordPersistence.ts's per-page keying
// works. Disposable "resume where I was interrupted" state, not a
// persistent preference, so sessionStorage over localStorage - same
// reasoning as that module.
function saveScrollPosition(key: string, y: number): void {
	if (!browser) return;
	try {
		sessionStorage.setItem(STORAGE_PREFIX + key, String(y));
	} catch {
		// e.g. storage disabled/full - scroll position just won't survive a reload
	}
}

function loadScrollPosition(key: string): number | null {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
		if (raw === null) return null;
		const n = Number(raw);
		return Number.isFinite(n) ? n : null;
	} catch {
		return null;
	}
}

// Attaches a window scroll listener that keeps saveScrollPosition up to
// date, coalesced to at most once per animation frame (a raw 'scroll'
// listener can fire many times a second - this keeps the sessionStorage
// write cheap and off the hot path). Returns a cleanup function - call
// from an $effect and let its own cleanup-on-rerun/unmount convention
// pick up the return value:
//   $effect(() => trackScrollPosition(location.pathname));
export function trackScrollPosition(key: string): () => void {
	if (!browser) return () => {};
	let ticking = false;
	const onScroll = () => {
		if (ticking) return;
		ticking = true;
		requestAnimationFrame(() => {
			saveScrollPosition(key, window.scrollY);
			ticking = false;
		});
	};
	window.addEventListener('scroll', onScroll, { passive: true });
	return () => window.removeEventListener('scroll', onScroll);
}

// Applies a saved scroll position once a page's content has actually
// loaded - restoring before then would scroll to a position a
// still-empty/loading page doesn't have yet. `await tick()` waits for
// Svelte's own pending DOM updates (the just-loaded list) to be applied
// before the requestAnimationFrame measures/sets scroll, so this needs to
// be called right after the data that determines page height has arrived
// (e.g. inside an $effect gated on `loading` turning false), not
// eagerly on mount:
//   let scrollRestored = false;
//   $effect(() => {
//       if (loading || scrollRestored) return;
//       scrollRestored = true;
//       restoreScrollPosition(location.pathname);
//   });
export async function restoreScrollPosition(key: string): Promise<void> {
	const saved = loadScrollPosition(key);
	if (saved === null) return;
	await tick();
	requestAnimationFrame(() => window.scrollTo(0, saved));
}
