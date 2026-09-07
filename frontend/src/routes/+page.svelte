<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import AccountMenu from '$lib/components/AccountMenu.svelte';

	let inputTexts: any[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			inputTexts = await api.listInputTexts() as any[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load texts';
		} finally {
			loading = false;
		}
	});

	async function handleDelete(id: number) {
		if (!confirm('Delete this text?')) return;
		try {
			await api.deleteInputText(id);
			inputTexts = inputTexts.filter((t) => t.id !== id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete';
		}
	}
</script>

<!-- Same bar-chart glyph as input-texts/[id]'s own "view latest results"
     link (see its docstring there) - kept as its own copy rather than a
     shared import, matching this codebase's existing per-file icon-snippet
     convention (iconChevron/iconBook/etc. in analyze/[id], for instance). -->
{#snippet iconBarChart()}
	<svg class="w-7 h-7" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M3.5 16.5h13" />
		<path d="M6 16.5V11" />
		<path d="M10 16.5V6.5" />
		<path d="M14 16.5V9" />
	</svg>
{/snippet}

<!-- A literal trash-can shape - deliberately NOT the existing iconTrash
     snippet used elsewhere in this app (analyze/[id]'s results table),
     which despite its name is actually a circle-with-diagonal-slash
     "no-entry" glyph for marking a word as garbage - a different, milder
     action than permanently deleting an entire input text, and reusing
     that glyph here would read as "block," not "delete." -->
{#snippet iconTrashCan()}
	<svg class="w-7 h-7" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M4.5 6h11" />
		<path d="M8 6V4.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V6" />
		<path d="M6 6l.7 9.5a1 1 0 0 0 1 .93h4.6a1 1 0 0 0 1-.93L14 6" />
		<path d="M8.5 9v4.5" />
		<path d="M11.5 9v4.5" />
	</svg>
{/snippet}

<div class="min-h-screen bg-gray-50">
	<!-- Static English title, no wrapping risk - so this row only needs
	     flex-wrap on the right-side action group for very narrow widths,
	     not the heavier two-row stacking analyze/[id] needs for its
	     unpredictable-length Chinese title. Three short actions wrapping
	     onto a second line reads fine here; don't "fix" this to match that
	     page's full-stack treatment, the two pages have different problems. -->
	<nav class="bg-white shadow-sm px-6 py-4 flex justify-between items-center flex-wrap gap-3">
		<h1 class="text-xl font-bold text-gray-800">Mandarin Tools</h1>
		<div class="flex gap-4 items-center flex-wrap">
			<a href="/analyze" class="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium">
				New Analysis
			</a>
			<AccountMenu />
		</div>
	</nav>

	<main class="max-w-4xl mx-auto px-6 py-8">
		<h2 class="text-2xl font-bold text-gray-800 mb-6">Your Texts</h2>

		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500">Loading...</p>
		{:else if inputTexts.length === 0}
			<div class="text-center py-16 text-gray-500">
				<p class="text-lg mb-4">No texts yet.</p>
				<a href="/analyze" class="bg-blue-600 text-white px-6 py-3 rounded-md hover:bg-blue-700 font-medium">
					Analyze your first text
				</a>
			</div>
		{:else}
			<div class="space-y-3">
				{#each inputTexts as text}
					<div class="bg-white rounded-lg shadow-sm p-4 flex justify-between items-center">
						<div>
							<a
							href="/input-texts/{text.id}"
							    class="font-medium text-blue-600 hover:underline"
							>
							    {text.title ?? 'Untitled'}
							</a>
							<p class="text-sm text-gray-500 mt-1">
								{new Date(text.created_at).toLocaleDateString()}
							</p>
						</div>
						<div class="flex items-center gap-4">
							{#if text.latest_analysis_id}
								<a
									href="/analyze/{text.latest_analysis_id}"
									class="text-gray-400 hover:text-blue-600"
									aria-label="View latest results"
									title="View latest results"
								>
									{@render iconBarChart()}
								</a>
							{/if}
							<button
								onclick={() => handleDelete(text.id)}
								class="text-gray-400 hover:text-red-600"
								aria-label="Delete"
								title="Delete"
							>
								{@render iconTrashCan()}
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</main>
</div>