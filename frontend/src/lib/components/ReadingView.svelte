<script lang="ts">
	import * as api from '$lib/api';
	import { sourceDetailColor, rarityContinuousColor, familiarityColor } from '$lib/wordDisplay';
	import type { SourceDetailTier } from '$lib/wordDisplay';
	import WordDetailModal from './WordDetailModal.svelte';
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
		// Raw occurrences-per-million, alongside rarity_tier - "Color by:
		// Rarity" interpolates a color directly from this (rarityContinuousColor),
		// rather than snapping to rarity_tier's 5 buckets the way the chips
		// elsewhere in the app still do. See AnalysisSpan.freq_per_million's
		// docstring, schemas.py, for why the two travel together.
		freq_per_million: number | null;
		userword_scopes: string[];
		userword_resolved_affects_dag: boolean;
		// Same resolved-fresh evidence tier as the results table's per-row
		// chip (WordResult.evidence_tier) - see get_analysis_spans'
		// docstring, router.py. This view's "Color by: Source" mode uses the
		// finer sourceDetailTier() below instead, but evidence_tier stays
		// on the span (spanTitle still reads off it via dictionary_source's
		// presence, and it's the fallback if dictionary_source is ever null
		// on an otherwise-"dictionary" word - see sourceDetailTier).
		evidence_tier: 'user' | 'dictionary' | 'corpus' | 'unknown' | null;
		// Splits evidence_tier's "dictionary" value into which curated
		// source backs the word - see AnalysisSpan.dictionary_source's
		// docstring, schemas.py, for the null cases and the HSK > CC-CEDICT
		// precedence when a word is backed by both.
		dictionary_source: 'hsk' | 'cedict' | null;
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

	// The color scale functions (wordDisplay.ts) return a combined
	// "bg-X-100 text-X-700" pair for use as small colored badges elsewhere
	// in the app - reused here for the actual color mapping (not a new
	// palette), but only the bg-* half, so reading text stays black rather
	// than turning every word a different text color, which would defeat
	// "keep it light/legible".
	function bgOnly(classes: string): string {
		return classes.split(' ')[0] ?? '';
	}

	// User > HSK > CC-CEDICT > Corpus > None - see AnalysisSpan.
	// dictionary_source's docstring (schemas.py) for the same order and
	// the HSK-over-CC-CEDICT tie-break. Falls back to evidence_tier's own
	// "corpus"/"unknown" for the two cases dictionary_source doesn't cover
	// (it's only ever "hsk"/"cedict"/null).
	function sourceDetailTier(span: WordSpan): SourceDetailTier {
		if (span.userword_scopes.length > 0) return 'user';
		if (span.dictionary_source) return span.dictionary_source;
		if (span.evidence_tier === 'corpus') return 'corpus';
		return 'none';
	}

	function spanClass(span: WordSpan): string {
		if (colorBy === 'source') return bgOnly(sourceDetailColor(sourceDetailTier(span)));
		// Rarity is the one mode with no bg-* class at all - see spanStyle.
		if (colorBy === 'rarity') return '';
		if (colorBy === 'familiarity') return bgOnly(familiarityColor(span.familiarity));
		// 'none' - word boundaries shown as a broken underline instead of
		// the old alternating bg-slate-100/bg-white tint (reported as hard
		// on the eyes across a full page - a flat color field behind every
		// other word is a much stronger signal than a boundary needs to
		// be). Each word gets its own short bottom-border segment; the
		// small trailing margin is what breaks the line between one word's
		// segment and the next, rather than a continuous underline running
		// the whole sentence.
		return 'border-b-2 border-gray-400 mr-0.5';
	}

	// Rarity is the one "Color by" mode that isn't one of a fixed set of
	// Tailwind classes - rarityContinuousColor interpolates an actual color
	// from the word's real frequency (see its docstring, wordDisplay.ts),
	// so it has to be applied as an inline style rather than a class. Every
	// other mode returns '' here and relies on spanClass instead.
	function spanStyle(span: WordSpan): string {
		if (colorBy !== 'rarity') return '';
		return `background-color: ${rarityContinuousColor(span.freq_per_million)}`;
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
				<!-- Colors by sourceDetailTier() - User > HSK > CC-CEDICT > Corpus >
				     None, a finer split of evidenceTierColor's own 4-tier scale
				     (see sourceDetailColor's docstring, wordDisplay.ts). -->
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
						style={spanStyle(span)}
						title={spanTitle(span)}
					>{span.word}</button
					>{/if}
			{/each}
		</p>
	{/if}
</div>

	<WordDetailModal
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
