// Shared by every profile word-list page's WordDetailModal swipe wiring
// (onSwipeNext/onSwipePrevious - see that component's own docstring for
// why this is opt-in per consumer).
//
// findNeighborWord originally just re-read each page's own live
// filtered()/sorted array on every swipe, with no frozen session list the
// way analyze/[id]/+page.svelte's own swipeToWord has - reasoned at the
// time as an acceptable simplification for a smaller, lower-stakes surface
// (same precedent as these pages' onGarbageMarked-only sync elsewhere,
// CLAUDE.md). That missed a real failure mode, found live: an edit made
// from the panel that removes the CURRENTLY OPEN word from that page's own
// list (un-hiding it on Hidden Words, clearing familiarity on Known Words,
// unstarring on Starred Words, removing the UserWord entry on User Words,
// unmarking garbage on Garbage Words, deleting a note on Notes) leaves
// `current` absent from every future re-read of the live list too - not
// just a missed step, a permanent dead end for the rest of that panel
// session, since there's nothing to fall back to once `current` itself is
// gone from the list being searched.
//
// `frozen` (optional, 4th param) fixes this the same way analyze/[id]'s own
// swipeSessionWords does: each page now owns a `sessionWords: string[] |
// null` $state, captured once (a plain word list, by identity) the instant
// a panel opens from fully closed and held fixed - order AND membership -
// until it closes, via this exact two-line effect (copy this shape, not a
// shared effect - see below for why):
//
//   let sessionWords: string[] | null = $state(null);
//   $effect(() => {
//       if (selectedWordForPanel && sessionWords === null) {
//           sessionWords = filtered().map((r) => r.word);
//       } else if (!selectedWordForPanel) {
//           sessionWords = null;
//       }
//   });
//
// That capture effect is deliberately NOT itself a shared function here,
// even though it's identical on every page - Svelte's $effect only tracks
// filtered() as a dependency because the read happens inside the branch
// that's conditionally taken (only on first capture); calling a shared
// function with `filtered()` already evaluated as an argument would read
// it - and so re-track it - on every single call, defeating the freeze
// entirely. The one-line lookup below has no such constraint, so it's the
// piece that's actually shared.
//
// Falls back to the live `list` (exactly today's pre-frozen behavior,
// dead end included) whenever `frozen` is null (no session captured yet,
// or omitted by a caller not opted in) or doesn't contain `current` (in
// practice: a fresh capture racing the very first render, not a case
// that's expected to matter in steady state - the frozen list is a
// superset of everything visible at session-start and never shrinks on
// its own afterward).
//
// Returns null (a dead end, same as analyze/[id]'s own swipeToWord - no
// wraparound) at either end of whichever list actually resolved `current`.
export function findNeighborWord<T extends { word: string }>(
	list: T[],
	current: string,
	direction: 'next' | 'prev',
	frozen?: string[] | null
): string | null {
	if (frozen) {
		const idx = frozen.indexOf(current);
		if (idx !== -1) {
			const nextIdx = direction === 'next' ? idx + 1 : idx - 1;
			return nextIdx >= 0 && nextIdx < frozen.length ? frozen[nextIdx] : null;
		}
	}
	const idx = list.findIndex((r) => r.word === current);
	if (idx === -1) return null;
	const nextIdx = direction === 'next' ? idx + 1 : idx - 1;
	return nextIdx >= 0 && nextIdx < list.length ? list[nextIdx].word : null;
}
