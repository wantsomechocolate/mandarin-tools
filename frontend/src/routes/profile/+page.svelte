<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	// Counts only - each card links to its own full management page. Loaded
	// in parallel; a card shows "…" until its own count resolves rather than
	// blocking the whole page on the slowest list.
	let counts: Record<string, number | null> = $state({
		knownWords: null,
		userWords: null,
		garbageWords: null,
		stopwords: null,
		starredWords: null,
	});
	let error = $state('');

	const cards = [
		{ key: 'knownWords', href: '/profile/known-words', label: 'Known Words', description: 'Familiarity scores for vocabulary you’re studying.' },
		{ key: 'userWords', href: '/profile/user-words', label: 'User Words', description: 'Your custom dictionary entries, across every text and analysis.' },
		{ key: 'garbageWords', href: '/profile/garbage-words', label: 'Garbage Words', description: 'Numbers, punctuation, and junk excluded from results by default.' },
		{ key: 'stopwords', href: '/profile/stopwords', label: 'Stopwords', description: 'Words excluded from the segmenter’s own algorithms.' },
		{ key: 'starredWords', href: '/profile/starred-words', label: 'Starred Words', description: 'Words you’ve bookmarked for later.' },
	];

	onMount(() => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		// Fired independently (not Promise.all) so one slow/failing list
		// doesn't hold back the others' counts from appearing.
		api.listKnownWords().then((r: any) => counts = { ...counts, knownWords: r.length }).catch(() => {});
		api.listAllUserWords().then((r: any) => counts = { ...counts, userWords: r.length }).catch(() => {});
		api.listGarbageWords().then((r: any) => counts = { ...counts, garbageWords: r.length }).catch(() => {});
		api.listStopwords().then((r: any) => counts = { ...counts, stopwords: r.length }).catch(() => {});
		api.listStarredWords().then((r: any) => counts = { ...counts, starredWords: r.length }).catch(() => {});
	});
</script>

{#if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
		{error}
	</div>
{/if}

<div class="grid sm:grid-cols-2 gap-4">
	{#each cards as card}
		<a
			href={card.href}
			class="bg-white rounded-lg shadow-sm p-5 hover:shadow-md transition-shadow"
		>
			<div class="flex items-baseline justify-between mb-1">
				<h2 class="text-lg font-semibold text-gray-800">{card.label}</h2>
				<span class="text-2xl font-bold text-blue-600">
					{counts[card.key] ?? '…'}
				</span>
			</div>
			<p class="text-sm text-gray-500">{card.description}</p>
		</a>
	{/each}
</div>
