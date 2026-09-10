<script lang="ts">
	import { logout } from '$lib/auth';
	import { getThemePreference, setThemePreference, type ThemePreference } from '$lib/theme.svelte';

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
		class="w-9 h-9 flex items-center justify-center rounded-full text-gray-600 hover:bg-gray-100 hover:text-gray-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
		aria-label="Account menu"
		aria-expanded={open}
	>
		{@render iconUser()}
	</button>
	{#if open}
		<div class="fixed inset-0 z-40" onclick={(e) => { e.stopPropagation(); open = false; }} role="presentation"></div>
		<div class="absolute right-0 top-full mt-1 z-50 w-44 bg-white rounded-lg shadow-lg border border-gray-100 py-1 dark:bg-slate-900 dark:border-slate-800">
			<a
				href="/word-lists"
				class="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:text-slate-300 dark:hover:bg-slate-800"
				onclick={() => open = false}
			>
				Word Lists
			</a>
			<a
				href="/profile"
				class="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:text-slate-300 dark:hover:bg-slate-800"
				onclick={() => open = false}
			>
				Account
			</a>
			<!-- System/Light/Dark, not a two-way toggle - see theme.svelte.ts's
			     ThemePreference docstring for why 'system' (follow the OS,
			     live) is a real third state rather than just an initial
			     default that's lost the moment someone picks a side. -->
			<div class="px-4 py-2 border-t border-gray-100 dark:border-slate-800 mt-1">
				<label for="theme-select" class="block text-xs text-gray-400 dark:text-slate-500 mb-1">Theme</label>
				<select
					id="theme-select"
					value={getThemePreference()}
					onchange={(e) => setThemePreference(e.currentTarget.value as ThemePreference)}
					class="w-full text-sm border border-gray-300 rounded px-2 py-1 bg-white text-gray-700 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200"
				>
					<option value="system">System</option>
					<option value="light">Light</option>
					<option value="dark">Dark</option>
				</select>
			</div>
			<button
				onclick={() => { open = false; logout(); }}
				class="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:text-slate-300 dark:hover:bg-slate-800"
			>
				Sign out
			</button>
		</div>
	{/if}
</div>
