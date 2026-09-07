<script lang="ts">
	import { page } from '$app/stores';
	import { logout } from '$lib/auth';

	let { children } = $props();

	// One tab per manageable list - each a top-level entity with no
	// existing "see everything" view before this (see each sub-page's own
	// docstring for what it shows and why). Order matches the review-
	// workflow ordering already established for the results page's filter
	// chips (Garbage, then the rest) where these overlap.
	const tabs = [
		{ href: '/profile/known-words', label: 'Known Words' },
		{ href: '/profile/user-words', label: 'User Words' },
		{ href: '/profile/garbage-words', label: 'Garbage Words' },
		{ href: '/profile/stopwords', label: 'Stopwords' },
		{ href: '/profile/starred-words', label: 'Starred Words' },
	];
</script>

<!-- Same home glyph as analyze/[id] and input-texts/[id]'s own header
     icons (see iconHome's docstring there) - kept as its own copy per this
     codebase's existing per-file icon-snippet convention. -->
{#snippet iconHome()}
	<svg class="w-8 h-8" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 9.5L10 4l6.5 5.5" />
		<path d="M5 8.5v7a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-7" />
		<path d="M8 16.5v-4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4" />
	</svg>
{/snippet}

<div class="min-h-screen bg-gray-50">
	<!-- No mobile-stacking fix needed: "Profile" is a fixed, short English
	     string with no competing right-side content, same reasoning as
	     analyze/+page.svelte's header. The tab bar below (overflow-x-auto +
	     whitespace-nowrap) is a deliberate, separate exception to "stack
	     instead of squeeze" and is untouched. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex items-center justify-between gap-4">
		<div class="flex items-center gap-4">
			<a href="/" class="text-gray-400 hover:text-blue-600" aria-label="Home" title="Home">
				{@render iconHome()}
			</a>
			<h1 class="text-xl font-bold text-gray-800">Profile</h1>
		</div>
		<button onclick={logout} class="text-gray-600 hover:text-gray-800 text-sm font-medium">
			Sign out
		</button>
	</nav>

	<div class="bg-white border-b border-gray-200 px-6">
		<div class="max-w-5xl mx-auto flex gap-1 overflow-x-auto">
			{#each tabs as tab}
				<a
					href={tab.href}
					class="px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap
					{$page.url.pathname === tab.href
						? 'border-blue-600 text-blue-600'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
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
