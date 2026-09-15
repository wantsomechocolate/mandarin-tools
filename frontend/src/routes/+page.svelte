<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';
	import AccountMenu from '$lib/components/AccountMenu.svelte';
	import { difficultyLabel, difficultyColor, difficultyOutOfTen, difficultyPercent } from '$lib/wordDisplay';

	let inputTexts: any[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Inline title editing, one card at a time (pencil-click-to-edit, same
	// pattern as input-texts/[id]'s own title/note editing) - tracked by id
	// rather than a per-card boolean since only one card is ever mid-edit.
	let editingTitleId: number | null = $state(null);
	let titleDraft = $state('');
	let savingTitle = $state(false);

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

	function startEditTitle(text: any) {
		editingTitleId = text.id;
		titleDraft = text.title ?? '';
	}

	async function saveTitle(text: any) {
		savingTitle = true;
		try {
			const trimmed = titleDraft.trim();
			await api.updateInputText(text.id, { title: trimmed || null });
			text.title = trimmed || null;
			editingTitleId = null;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to rename';
		} finally {
			savingTitle = false;
		}
	}

	// Same click-passthrough pattern as analyze/[id]'s own handleRowClick -
	// anywhere on the card opens the text, unless the click actually landed
	// on the title link/edit pencil, the analyze/view-results link, the
	// trash button, or (while this card's title is mid-edit) its input/
	// Save/Cancel controls - all of which are real interactive elements the
	// generic `button, a, input` guard already covers with no need to name
	// each one individually.
	function handleCardClick(event: MouseEvent | KeyboardEvent, id: number) {
		const target = event.target as HTMLElement;
		if (target.closest('button, a, input, select, textarea')) return;
		goto(`/input-texts/${id}`);
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

<!-- Same pencil glyph as input-texts/[id]'s own title/note edit affordance
     - kept as its own copy per this file's existing per-file icon-snippet
     convention (see iconBarChart's comment above). -->
{#snippet iconPencil()}
	<svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
		<path d="M13.5 3.5a1.5 1.5 0 0 1 2.12 2.12L6.5 14.75l-3 .75.75-3 9.25-9z" />
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

<div class="min-h-screen bg-gray-50 dark:bg-slate-950">
	<!-- Static English title, no wrapping risk - so this row only needs
	     flex-wrap on the right-side action group for very narrow widths,
	     not the heavier two-row stacking analyze/[id] needs for its
	     unpredictable-length Chinese title. Three short actions wrapping
	     onto a second line reads fine here; don't "fix" this to match that
	     page's full-stack treatment, the two pages have different problems. -->
	<nav class="bg-white dark:bg-slate-900 shadow-sm px-6 py-4 flex justify-between items-center flex-wrap gap-3">
		<h1 class="text-xl font-bold text-gray-800 dark:text-slate-200">Mandarin Tools</h1>
		<div class="flex gap-4 items-center flex-wrap">
			<a href="/analyze" class="bg-blue-600 dark:bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-700 dark:hover:bg-blue-600 text-sm font-medium">
				New Analysis
			</a>
			<AccountMenu />
		</div>
	</nav>

	<main class="max-w-4xl mx-auto px-6 py-8">
		<h2 class="text-2xl font-bold text-gray-800 dark:text-slate-200 mb-6">Your Texts</h2>

		{#if error}
			<div class="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-400 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500 dark:text-slate-400">Loading...</p>
		{:else if inputTexts.length === 0}
			<div class="text-center py-16 text-gray-500 dark:text-slate-400">
				<p class="text-lg mb-4">No texts yet.</p>
				<a href="/analyze" class="bg-blue-600 dark:bg-blue-500 text-white px-6 py-3 rounded-md hover:bg-blue-700 dark:hover:bg-blue-600 font-medium">
					Analyze your first text
				</a>
			</div>
		{:else}
			<div class="space-y-3">
				{#each inputTexts as text}
					<div
						role="button"
						tabindex="0"
						onclick={(e) => handleCardClick(e, text.id)}
						onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCardClick(e, text.id); } }}
						class="bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4 flex justify-between items-center gap-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800/60"
					>
						<div class="min-w-0 flex-1">
							{#if editingTitleId === text.id}
								<div class="flex items-center gap-2">
									<input
										type="text"
										bind:value={titleDraft}
										placeholder="Untitled"
										class="flex-1 min-w-0 border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm"
										onkeydown={(e) => { if (e.key === 'Enter') saveTitle(text); if (e.key === 'Escape') editingTitleId = null; }}
									/>
									<button onclick={() => saveTitle(text)} disabled={savingTitle} class="text-xs px-2 py-1 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
										Save
									</button>
									<button onclick={() => editingTitleId = null} disabled={savingTitle} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">
										Cancel
									</button>
								</div>
							{:else}
								<div class="flex items-center gap-1.5">
									<a
										href="/input-texts/{text.id}"
										class="font-medium text-blue-600 dark:text-blue-400 hover:underline truncate"
									>
										{text.title ?? 'Untitled'}
									</a>
									<button
										onclick={() => startEditTitle(text)}
										class="text-gray-300 dark:text-slate-600 hover:text-blue-600 dark:hover:text-blue-400 shrink-0"
										aria-label="Edit title"
										title="Edit title"
									>
										{@render iconPencil()}
									</button>
									{#if text.latest_analysis_difficulty_band != null}
										<span
											title="{difficultyPercent(text.latest_analysis_difficulty_score)}% known-coverage"
											class="text-xs font-medium px-2 py-0.5 rounded-full shrink-0 {difficultyColor(text.latest_analysis_difficulty_band)}"
										>
											{difficultyOutOfTen(text.latest_analysis_difficulty_score)}/10 · {difficultyLabel(text.latest_analysis_difficulty_band)}
										</span>
									{/if}
								</div>
							{/if}
							<p class="text-sm text-gray-500 dark:text-slate-400 mt-1">
								{new Date(text.created_at).toLocaleDateString()}
								{#if text.latest_analysis_unique_words != null}
									· {text.latest_analysis_unique_words} unique words · {text.latest_analysis_total_words} total
								{/if}
							</p>
							{#if text.note}
								<p class="text-sm text-gray-500 dark:text-slate-400 mt-1 truncate" title={text.note}>
									{text.note}
								</p>
							{/if}
						</div>
						<div class="flex items-center gap-4 shrink-0">
							{#if text.latest_analysis_id}
								<a
									href="/analyze/{text.latest_analysis_id}"
									class="text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400"
									aria-label="View latest results"
									title="View latest results"
								>
									{@render iconBarChart()}
								</a>
							{/if}
							<button
								onclick={() => handleDelete(text.id)}
								class="text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400"
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