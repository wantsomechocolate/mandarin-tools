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
		onGarbageMarked,
	}: {
		word: string | null;
		context: WordDetailContext;
		onClose: () => void;
		onUserWordEntriesChanged?: (entries: UserWordEntry[]) => void;
		onVisibilityEntriesChanged?: (entries: VisibilityEntry[]) => void;
		onFamiliarityChanged?: (familiarity: number | null) => void;
		onGarbageMarked?: () => void;
	} = $props();
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
			class="w-full max-w-sm mx-auto lg:max-w-none lg:w-auto self-start lg:sticky lg:top-4"
			onclick={(e) => e.stopPropagation()}
			role="presentation"
		>
			<WordDetailPanel {word} {context} {onClose} {onUserWordEntriesChanged} {onVisibilityEntriesChanged} {onFamiliarityChanged} {onGarbageMarked} />
		</div>
	</div>
{/if}
