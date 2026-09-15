// Shared by every profile word-list page's WordDetailModal swipe wiring
// (onSwipeNext/onSwipePrevious - see that component's own docstring for
// why this is opt-in per consumer). analyze/[id]/+page.svelte's own
// swipeToWord freezes its word order at panel-open time (swipeSessionWords)
// specifically because the analysis results table can be very large and
// its own filters/sort can reshuffle live under an in-progress swipe -
// these list pages are a much smaller, lower-stakes surface (same
// "accepted trade-off" precedent as their onGarbageMarked-only sync
// elsewhere, CLAUDE.md), so there's no separate frozen-list mechanism here:
// each page just re-reads its own current filtered()/sorted array on every
// swipe.
//
// Returns null (a dead end, same as analyze/[id]'s own swipeToWord - no
// wraparound) at either end of `list`, or if `current` isn't in `list` at
// all - e.g. it was removed by an edit made elsewhere while the panel
// stayed open on it (a cleared familiarity score, an unmarked star, etc.).
export function findNeighborWord<T extends { word: string }>(
	list: T[],
	current: string,
	direction: 'next' | 'prev'
): string | null {
	const idx = list.findIndex((r) => r.word === current);
	if (idx === -1) return null;
	const nextIdx = direction === 'next' ? idx + 1 : idx - 1;
	return nextIdx >= 0 && nextIdx < list.length ? list[nextIdx].word : null;
}
