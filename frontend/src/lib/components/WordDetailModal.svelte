<script lang="ts">
	import WordDetailPanel from './WordDetailPanel.svelte';
	import type { UserWordEntry, VisibilityEntry } from './WordDetailPanel.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

	// Shared wrapper around WordDetailPanel, pulled out of the 5 places that
	// used to duplicate this markup by hand (analyze/[id]/+page.svelte, the
	// three profile list pages, ReadingView.svelte) - see this component's
	// own docstring below for the actual bug this centralization fixes.
	let {
		word,
		context,
		onClose,
		onUserWordEntriesChanged,
		onVisibilityEntriesChanged,
		onFamiliarityChanged,
		onNoteChanged,
		onGarbageMarked,
		onSwipeNext,
		onSwipePrevious,
	}: {
		word: string | null;
		context: WordDetailContext;
		onClose: () => void;
		onUserWordEntriesChanged?: (entries: UserWordEntry[]) => void;
		onVisibilityEntriesChanged?: (entries: VisibilityEntry[]) => void;
		onFamiliarityChanged?: (familiarity: number | null) => void;
		onNoteChanged?: (note: string | null) => void;
		onGarbageMarked?: () => void;
		// Optional - only analyze/[id]/+page.svelte supplies these today (it's
		// the only page with a natural "current sorted/filtered list" to walk
		// - see its own swipeToWord). Every other consumer of this modal
		// (the profile list pages, ReadingView) just omits them, and the
		// gesture handling below never arms at all when neither is provided.
		onSwipeNext?: () => void;
		onSwipePrevious?: () => void;
	} = $props();

	// Swipe-to-navigate (mobile only - see canSwipe) - left = next word,
	// right = previous, matching the direction a horizontal card/carousel
	// swipe conventionally means. Deliberately NOT a live drag-follow
	// (no CSS transform tracking the finger, no spring-back animation) -
	// the panel just swaps to the neighboring word on a completed swipe,
	// the same visual jump a tap on a different row already produces.
	// That's a much smaller, lower-risk first cut than a real animated
	// carousel; revisit only if this plain version actually feels good
	// enough to build on.
	//
	// Pointer Events (not legacy touchstart/touchmove/touchend) - one API
	// for touch/mouse/pen, and unlike touchmove, Svelte doesn't register
	// pointermove listeners as passive by default, so preventDefault()
	// below actually works without a manual addEventListener call.
	const SWIPE_DEAD_ZONE = 10; // px - ignore tiny jitter before committing to a direction at all
	const SWIPE_H_V_RATIO = 1.5; // horizontal move must beat vertical by this much to commit as a swipe, not a scroll
	// There used to be a separate, larger SWIPE_COMMIT_THRESHOLD (70px) that
	// had to be crossed after commitment, checked on every subsequent move,
	// before actually navigating. Removed - live on-screen debug logging on
	// a real device showed only ONE real pointermove ever arrives before
	// something (almost certainly Android's own system gesture-navigation,
	// not this app's touch-action/preventDefault, which can't reach that
	// layer) cancels the touch, often well before the finger is anywhere
	// near a screen edge. There's no reliable second event to check a
	// distance threshold against, so direction-commitment (SWIPE_DEAD_ZONE
	// + SWIPE_H_V_RATIO, both already required to rule out jitter/scroll)
	// is now itself the trigger - see handlePointerMove.

	let dragPointerId: number | null = null;
	let dragStartX = 0;
	let dragStartY = 0;

	// window.innerWidth is only ever read from inside these pointer
	// handlers, which can't fire during SSR (there's no pointer to press) -
	// this app also runs with SSR disabled entirely (see CLAUDE.md), so no
	// `browser` guard is needed here the way module-level/$state-initializer
	// code elsewhere in this app needs one.
	function canSwipe(): boolean {
		// Below `lg` only - at `lg`+ this same element is part of the
		// docked-sidebar layout (see the markup below), where a horizontal
		// swipe would just be normal text selection, not "go to another
		// word." Matches the exact breakpoint that already decides
		// bottom-sheet vs. docked presentation.
		return window.innerWidth < 1024 && (!!onSwipeNext || !!onSwipePrevious);
	}

	function handlePointerDown(e: PointerEvent) {
		if (e.pointerType !== 'touch' || dragPointerId !== null || !canSwipe()) return;
		// Don't hijack taps/drags that start on an actual control - a user
		// selecting text in the pronunciation field, or pressing a
		// familiarity dot, shouldn't have the whole panel swap words out
		// from under them mid-interaction.
		if ((e.target as HTMLElement).closest('input, textarea, select, button, a')) return;
		dragPointerId = e.pointerId;
		dragStartX = e.clientX;
		dragStartY = e.clientY;
	}

	function handlePointerMove(e: PointerEvent) {
		if (e.pointerId !== dragPointerId) return;
		const dx = e.clientX - dragStartX;
		const dy = e.clientY - dragStartY;
		if (Math.abs(dx) < SWIPE_DEAD_ZONE && Math.abs(dy) < SWIPE_DEAD_ZONE) {
			// Still too early to know direction - but suppress the browser's
			// own native pan-y scroll for this event anyway. touch-action:
			// pan-y lets the browser start a real native vertical scroll the
			// instant early movement looks even slightly vertical, and it
			// decides that on its own compositor-thread heuristic, not ours -
			// a real finger never swipes in a perfectly straight line, so
			// without this the browser can win that race and pointercancel
			// us before we ever get to make our own horizontal/vertical call
			// below. Costs a genuinely-vertical scroll only its first few
			// (dead-zone-bounded) pixels before we back off below.
			e.preventDefault();
			return;
		}
		e.preventDefault();
		// Decide direction and act immediately on this same event, rather
		// than setting a "committed" flag and waiting for a later move to
		// cross some further distance - live on-screen debug logging on a
		// real device showed only ONE real pointermove ever arrives before
		// something (almost certainly Android's own system gesture
		// navigation, not this app's touch-action/preventDefault, which
		// can't reach that layer) cancels the touch outright, often well
		// before the finger is anywhere near a screen edge. There's no
		// reliable second event to wait for, so clearing SWIPE_DEAD_ZONE
		// with a horizontal-dominant ratio is itself the trigger. This also
		// means a committed-but-still-short horizontal move now fires
		// immediately rather than requiring a further travel distance -
		// deliberate, since the alternative (waiting) is what was silently
		// losing every real-device attempt.
		dragPointerId = null; // resolved either way - stop tracking this pointer
		if (Math.abs(dx) <= Math.abs(dy) * SWIPE_H_V_RATIO) {
			// Predominantly vertical - this is a scroll, not our gesture.
			return;
		}
		if (dx < 0) onSwipeNext?.();
		else onSwipePrevious?.();
	}

	function endDrag(e: PointerEvent) {
		// Navigation now fires from handlePointerMove itself (see above) -
		// this only needs to stop tracking a pointer that never moved past
		// the dead zone at all (a tap, or a drag too short to judge).
		if (e.pointerId !== dragPointerId) return;
		dragPointerId = null;
	}
</script>

<!-- The bug this fixes: the old duplicated wrapper's middle <div> had no
     width class of its own, so below `lg` it sized to whatever content sat
     inside it - WordDetailPanel's own `w-full` had no definite ancestor
     width to resolve against, so adding a long sample sentence visibly
     widened the whole bottom sheet as you typed. `w-full max-w-sm mx-auto`
     below `lg` gives it a real, content-independent width; `lg:max-w-none
     lg:w-auto` gets out of the way at `lg`+, where WordDetailPanel switches
     to its own fixed `lg:w-72`. -->
{#if word}
	<div
		class="fixed inset-0 z-40 flex items-end justify-center bg-black/30 lg:contents"
		onclick={onClose}
		role="presentation"
	>
		<div
			class="w-full max-w-sm mx-auto lg:max-w-none lg:w-auto self-start lg:sticky lg:top-4 touch-pan-y"
			onclick={(e) => e.stopPropagation()}
			onpointerdown={handlePointerDown}
			onpointermove={handlePointerMove}
			onpointerup={endDrag}
			onpointercancel={endDrag}
			role="presentation"
		>
			<WordDetailPanel {word} {context} {onClose} {onUserWordEntriesChanged} {onVisibilityEntriesChanged} {onFamiliarityChanged} {onNoteChanged} {onGarbageMarked} />
		</div>
	</div>
{/if}
