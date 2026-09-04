<script lang="ts">
	import * as api from '$lib/api';
	import { sourceColor, rarityColor, familiarityColor } from '$lib/wordDisplay';
	import WordDetailPanel from './WordDetailPanel.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';

	// Read-only foundation for the reading view - renders the source text
	// with its best-guess (dag/overlay-sourced) segmentation visually
	// marked. Deliberately does NOT support drag-to-correct boundaries or
	// any other editing interaction - that's a follow-up phase, not built
	// here (see GET /analyze/{id}/spans' docstring, router.py, for the
	// backend side of this same split).
	//
	// Analysis-centric (driven by `analysisId` alone, textTitle/
	// analysisTitle passed in for the panel's context rather than re-fetched)
	// rather than tied to anything analyze/[id]-specific, so this could be
	// embedded from input-texts/[id] later (e.g. to show a text's latest
	// analysis) without a rewrite - that page would just need to pick which
	// analysisId to pass in, which is its own separate future piece of work.
	let {
		analysisId,
		textTitle,
		analysisTitle,
	}: {
		analysisId: number;
		textTitle: string | null;
		analysisTitle: string | null;
	} = $props();

	interface WordSpan {
		type: 'word';
		start: number;
		end: number;
		word: string;
		source: string;
		familiarity: number | null;
		is_hidden: boolean;
		hidden_governing_scope: string;
		rarity_tier: string | null;
		userword_scopes: string[];
		userword_resolved_affects_dag: boolean;
	}
	interface GapSpan {
		type: 'gap';
		start: number;
		end: number;
		text: string;
	}
	type Span = WordSpan | GapSpan;

	let spans: Span[] = $state([]);
	let textId: number | null = $state(null);
	let loading = $state(true);
	let error = $state('');

	type ColorBy = 'none' | 'source' | 'rarity' | 'familiarity';
	let colorBy: ColorBy = $state('none');

	let selectedWordForPanel: string | null = $state(null);
	const panelContext: WordDetailContext = $derived(
		textId != null
			? { type: 'analysis', textId, textTitle, analysisId, analysisTitle }
			: { type: 'global' } // unreachable in practice - textId is always set once spans have loaded, before any word is clickable
	);

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await api.getAnalysisSpans(analysisId) as { input_text_id: number; spans: Span[] };
			spans = data.spans;
			textId = data.input_text_id;
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load reading view';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		analysisId; // re-fetch if the parent points this at a different analysis
		load();
	});

	// Alternating parity among WORD spans only (gaps don't count) - the
	// default "Color by: None" boundary indicator. Computed once per spans
	// load, not per-render.
	const wordParity = $derived(() => {
		const parity = new Map<WordSpan, number>();
		let i = 0;
		for (const s of spans) {
			if (s.type === 'word') {
				parity.set(s, i % 2);
				i++;
			}
		}
		return parity;
	});

	// The color scale functions (wordDisplay.ts) return a combined
	// "bg-X-100 text-X-700" pair for use as small colored badges elsewhere
	// in the app - reused here for the actual color mapping (not a new
	// palette), but only the bg-* half, so reading text stays black rather
	// than turning every word a different text color, which would defeat
	// "keep it light/legible".
	function bgOnly(classes: string): string {
		return classes.split(' ')[0] ?? '';
	}

	function spanClass(span: WordSpan): string {
		if (colorBy === 'source') return bgOnly(sourceColor(span.source));
		if (colorBy === 'rarity') return bgOnly(rarityColor(span.rarity_tier));
		if (colorBy === 'familiarity') return bgOnly(familiarityColor(span.familiarity));
		// 'none' - the default subtle alternating tint, just enough to show
		// where one word ends and the next begins without any semantic
		// meaning attached to the color itself.
		return wordParity().get(span) === 0 ? 'bg-slate-100' : 'bg-white';
	}

	function spanTitle(span: WordSpan): string {
		const parts = [span.word];
		if (span.familiarity != null) parts.push(`familiarity ${span.familiarity}`);
		if (span.rarity_tier) parts.push(span.rarity_tier.replace(/_/g, ' '));
		if (span.userword_scopes.length > 0) parts.push('in your dictionary');
		return parts.join(' — ');
	}
</script>

<!-- Shared flex row with the panel below (lg and up) - same mechanism as
     the analysis results table/profile list pages: the panel's own
     backdrop wrapper collapses to `display: contents` at `lg`, so its
     child joins this row as a sticky-positioned sibling instead of
     floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white rounded-lg shadow-sm p-4">
	<div class="flex items-center justify-between gap-3 mb-3 flex-wrap">
		<p class="text-xs font-medium text-gray-400 uppercase tracking-wide">Reading view</p>
		<label class="flex items-center gap-1.5 text-sm text-gray-700">
			Color by
			<select bind:value={colorBy} class="border border-gray-300 rounded px-2 py-1 text-sm">
				<option value="none">None</option>
				<option value="source">Source</option>
				<option value="rarity">Rarity</option>
				<option value="familiarity">Familiarity</option>
			</select>
		</label>
	</div>

	{#if loading}
		<p class="text-gray-500 text-sm">Loading...</p>
	{:else if error}
		<p class="text-red-600 text-sm">{error}</p>
	{:else}
		<p class="text-xl leading-loose whitespace-pre-wrap break-words">
			{#each spans as span}
				{#if span.type === 'gap'}<span>{span.text}</span
				>{:else}<button
						onclick={() => selectedWordForPanel = span.word}
						class="rounded px-0.5 hover:ring-1 hover:ring-blue-400 {spanClass(span)}"
						title={spanTitle(span)}
					>{span.word}</button
					>{/if}
			{/each}
		</p>
	{/if}
</div>

{#if selectedWordForPanel}
	<div
		class="fixed inset-0 z-40 flex items-end justify-center bg-black/30 lg:contents"
		onclick={() => selectedWordForPanel = null}
		role="presentation"
	>
		<div class="self-start lg:sticky lg:top-4" onclick={(e) => e.stopPropagation()} role="presentation">
			<WordDetailPanel
				word={selectedWordForPanel}
				context={panelContext}
				onClose={() => selectedWordForPanel = null}
				onFamiliarityChanged={(familiarity) => {
					const word = selectedWordForPanel;
					if (!word) return;
					spans = spans.map((s) => s.type === 'word' && s.word === word ? { ...s, familiarity } : s);
				}}
			/>
		</div>
	</div>
{/if}
</div>
