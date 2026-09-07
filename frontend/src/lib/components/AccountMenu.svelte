<script lang="ts">
	import { logout } from '$lib/auth';

	// Account-menu trigger - a single icon + dropdown (Word Lists / Account /
	// Sign out) shared across every page's header bar, rather than each page carrying
	// its own copy of the open/close state and dropdown markup (unlike the
	// plain, stateless icon snippets - iconHome/iconBook/etc. - that stay
	// duplicated per-file by this codebase's convention, this one has real
	// interactive state worth sharing one implementation of). Originally
	// built directly in the root page's own nav; extracted here once three
	// more pages wanted the identical menu.
	let open = $state(false);
</script>

{#snippet iconUser()}
	<svg class="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<circle cx="10" cy="7" r="3" />
		<path d="M4 16.5c0-3 2.7-5 6-5s6 2 6 5" />
	</svg>
{/snippet}

<!-- Relative wrapper + backdrop-click-to-close, same pattern analyze/[id]'s
     own popovers (visibilityAction/userWordAction) use - stopPropagation on
     the backdrop is defensive on pages with no row click handler underneath
     to leak into, but costs nothing and matches the established
     convention. -->
<div class="relative">
	<button
		onclick={() => open = !open}
		class="w-9 h-9 flex items-center justify-center rounded-full text-gray-600 hover:bg-gray-100 hover:text-gray-800"
		aria-label="Account menu"
		aria-expanded={open}
	>
		{@render iconUser()}
	</button>
	{#if open}
		<div class="fixed inset-0 z-40" onclick={(e) => { e.stopPropagation(); open = false; }} role="presentation"></div>
		<div class="absolute right-0 top-full mt-1 z-50 w-40 bg-white rounded-lg shadow-lg border border-gray-100 py-1">
			<a
				href="/word-lists"
				class="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
				onclick={() => open = false}
			>
				Word Lists
			</a>
			<a
				href="/profile"
				class="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
				onclick={() => open = false}
			>
				Account
			</a>
			<button
				onclick={() => { open = false; logout(); }}
				class="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
			>
				Sign out
			</button>
		</div>
	{/if}
</div>
