<script lang="ts">
	import { familiarityLabel, familiarityDotColor } from '$lib/wordDisplay';

	// Shared familiarity control - 5 clickable dots (filled up to the
	// current score, in that score's own color) plus a small ✕ to clear it,
	// extracted from analyze/[id]'s desktop table so the profile "Known
	// Words" page (and anything else that wants the same compact widget)
	// doesn't need its own copy. The caller owns the actual data - this
	// component only renders the current value and reports clicks back via
	// onSetFamiliarity, the same "dumb control" shape WordDetailPanel's own
	// sub-pieces already use.
	//
	// dotSize is a parameter, not a fixed w-2 h-2, because the two call
	// sites want genuinely different sizes: analyze/[id]'s results table is
	// a dense 7-column layout where small dots matter, while Known Words
	// has just two columns and room to make the control easier to click -
	// callers pass their own Tailwind size classes rather than this
	// component guessing a "right" size for every context.
	let {
		familiarity,
		disabled = false,
		dotSize = 'w-2 h-2',
		onSetFamiliarity,
	}: {
		familiarity: number | null;
		disabled?: boolean;
		dotSize?: string;
		onSetFamiliarity: (score: number | null) => void;
	} = $props();
</script>

<!-- Every button is itself inline-flex items-center justify-center, not
     just relying on the parent row's own items-center - a button whose
     only child is a block span (the dots) has no inline-formatting-context
     "strut," but the ✕ button's child is inline-flex, which does get one,
     making that button's own line box taller than the dot buttons' and
     leaving its glyph sitting off-center (baseline-aligned within that
     taller box, not vertically centered) if the button itself isn't also
     a flex container centering its own content directly. -->
<div class="flex items-center gap-0.5">
	{#each [1, 2, 3, 4, 5] as score}
		<button
			onclick={() => onSetFamiliarity(score)}
			{disabled}
			class="p-1 rounded hover:bg-gray-100 disabled:opacity-50 inline-flex items-center justify-center"
			title={familiarityLabel(score)}
			aria-label={familiarityLabel(score)}
			aria-pressed={familiarity === score}
		>
			<span class="block {dotSize} rounded-full {familiarity !== null && score <= familiarity ? familiarityDotColor(familiarity) : 'bg-gray-200'}"></span>
		</button>
	{/each}
	<button
		onclick={() => onSetFamiliarity(null)}
		disabled={disabled || familiarity === null}
		class="p-1 rounded hover:bg-gray-100 disabled:opacity-50 inline-flex items-center justify-center text-gray-500 hover:text-gray-700 ml-0.5 {familiarity === null ? 'invisible' : ''}"
		title="Clear familiarity"
		aria-label="Clear familiarity"
	>
		<span class="inline-flex items-center justify-center {dotSize} text-[10px] leading-none">✕</span>
	</button>
</div>
