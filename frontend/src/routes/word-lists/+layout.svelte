<script lang="ts">
	import { page } from '$app/stores';
	import AccountMenu from '$lib/components/AccountMenu.svelte';

	let { children } = $props();

	// One tab per manageable list - each a top-level entity with no
	// existing "see everything" view before this (see each sub-page's own
	// docstring for what it shows and why). Search first - it's the entry
	// point into everything else here (find a word from any source, then
	// the same WordDetailPanel every other tab opens takes it from there),
	// not itself a managed list the way the rest of these tabs are. Then
	// Starred (the words you most actively chose to flag), then Known/User
	// (day-to-day vocabulary management), then Notes (words you've
	// annotated, regardless of starred/known/user-word status - see
	// WordNote's docstring, models.py), then Hidden (results-visibility
	// overrides - a step further removed from day-to-day vocabulary than
	// Notes, but still something a user chose deliberately, unlike the
	// maintenance/cleanup Stopwords/Garbage tabs after it), then Stopwords/
	// Garbage last (maintenance/cleanup lists, touched less often).
	const tabs = [
		{ href: '/word-lists/search', label: 'Search' },
		{ href: '/word-lists/starred-words', label: 'Starred Words' },
		{ href: '/word-lists/known-words', label: 'Known Words' },
		{ href: '/word-lists/user-words', label: 'User Words' },
		{ href: '/word-lists/notes', label: 'Notes' },
		{ href: '/word-lists/hidden-words', label: 'Hidden Words' },
		{ href: '/word-lists/stopwords', label: 'Stopwords' },
		{ href: '/word-lists/garbage-words', label: 'Garbage Words' },
	];
</script>

<!-- Same home glyph as analyze/[id] and input-texts/[id]'s own header
     icons (see iconHome's docstring there) - kept as its own copy per this
     codebase's existing per-file icon-snippet convention. -->
{#snippet iconHome()}
	<svg class="w-8 h-8 block" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7.75a0.25 0.25 0 0 0 0.25 0.25h9.5a0.25 0.25 0 0 0 0.25-0.25v-7.75" />
	</svg>
{/snippet}

<div class="min-h-screen bg-gray-50 dark:bg-slate-950">
	<!-- No mobile-stacking fix needed: "Word Lists" is a fixed, short English
	     string with no competing right-side content, same reasoning as
	     analyze/+page.svelte's header. The tab bar below (overflow-x-auto +
	     whitespace-nowrap) is a deliberate, separate exception to "stack
	     instead of squeeze" and is untouched. -->
	<nav class="bg-white dark:bg-slate-900 shadow-sm px-6 py-4 flex items-center justify-between gap-4">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400" aria-label="Home" title="Home">
				{@render iconHome()}
			</a>
			<h1 class="text-xl font-bold text-gray-800 dark:text-slate-200">Word Lists</h1>
		</div>
		<AccountMenu />
	</nav>

	<div class="bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800 px-6">
		<div class="max-w-5xl mx-auto flex gap-1 overflow-x-auto">
			{#each tabs as tab}
				<a
					href={tab.href}
					class="px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap
					{$page.url.pathname === tab.href
						? 'border-blue-600 dark:border-blue-500 text-blue-600 dark:text-blue-400'
						: 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 hover:border-gray-300 dark:hover:border-slate-500'}"
				>
					{tab.label}
				</a>
			{/each}
		</div>
	</div>

	<main class="max-w-5xl mx-auto px-6 py-8">
		{@render children()}
	</main>
</div>
