<script lang="ts">
	import * as api from '$lib/api';
	import { sourceDetailColor, rarityContinuousColor, familiarityColor } from '$lib/wordDisplay';
	import type { SourceDetailTier } from '$lib/wordDisplay';
	import WordDetailModal from './WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';
	import { isDarkMode } from '$lib/theme.svelte';

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
		userword_resolved_affects_dag: api.AffectsDag;
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

	// 'reading-view' slot - see panelWordPersistence.ts's docstring - this
	// component and analyze/[id]/+page.svelte's own results-table panel can
	// both be open (in the sense of "was open before a reload") on the same
	// page, so each needs its own storage slot rather than sharing the
	// default one.
	let selectedWordForPanel: string | null = $state(loadOpenWordPanel('reading-view'));
	$effect(() => {
		saveOpenWordPanel(selectedWordForPanel, 'reading-view');
	});
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

	// Dark-mode tints for "Color by: Source"/"Color by: Familiarity" -
	// deliberately NOT wordDisplay.ts's own dark:bg-{hue}-500/15 halves
	// (bgOnly would otherwise grab the light bg-{hue}-100 token and leave
	// the dark: variant to apply itself via CSS same as everywhere else).
	// That wash is tuned for a small chip sitting next to text of its own
	// color; applied as a large fill behind a whole word on a black
	// background it read as barely-there. These run a full hue step
	// brighter and roughly double the opacity - bg-{hue}-400/30 instead of
	// bg-{hue}-500/15 - so a tinted word is unmistakable at a glance
	// against a dark page, the same bar the light mode fills already clear
	// against a white one.
	// 'none' still gets a (subtle) dark tint, not '' - bgOnly() below only
	// ever keeps the LIGHT half of sourceDetailColor/familiarityColor's
	// returned class pair, so an empty string here would leave that word's
	// span with nothing but its light-mode bg-gray-100 class - which,
	// unlike a dark: class, applies unconditionally regardless of theme,
	// painting a bright box behind now-light text in dark mode instead of
	// no visible tint at all.
	const SOURCE_TINT_DARK: Record<SourceDetailTier, string> = {
		user: 'dark:bg-yellow-400/30',
		hsk: 'dark:bg-blue-400/30',
		cedict: 'dark:bg-fuchsia-400/30',
		corpus: 'dark:bg-teal-400/30',
		none: 'dark:bg-slate-500/15',
	};
	const FAMILIARITY_TINT_DARK: Record<number, string> = {
		1: 'dark:bg-red-400/30',
		2: 'dark:bg-orange-400/30',
		3: 'dark:bg-yellow-400/30',
		4: 'dark:bg-green-400/30',
		5: 'dark:bg-emerald-400/30',
	};

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
		if (colorBy === 'source') {
			const tier = sourceDetailTier(span);
			return bgOnly(sourceDetailColor(tier)) + ' ' + SOURCE_TINT_DARK[tier];
		}
		// Rarity is the one mode with no bg-* class at all - see spanStyle.
		if (colorBy === 'rarity') return '';
		if (colorBy === 'familiarity') {
			// Same "'' would leave an unconditional light bg-gray-100 applied
			// in dark mode too" reasoning as SOURCE_TINT_DARK's 'none' entry
			// above - a word with no familiarity score set still needs an
			// explicit (subtle) dark tint, not an absent one.
			const tint = span.familiarity ? FAMILIARITY_TINT_DARK[span.familiarity] : 'dark:bg-slate-500/15';
			return bgOnly(familiarityColor(span.familiarity)) + ' ' + tint;
		}
		// 'none' - word boundaries shown as a broken underline instead of
		// the old alternating bg-slate-100/bg-white tint (reported as hard
		// on the eyes across a full page - a flat color field behind every
		// other word is a much stronger signal than a boundary needs to
		// be). Each word gets its own short bottom-border segment; the
		// small trailing margin is what breaks the line between one word's
		// segment and the next, rather than a continuous underline running
		// the whole sentence.
		return 'border-b-2 border-gray-400 dark:border-slate-500 mr-0.5';
	}

	// Rarity is the one "Color by" mode that isn't one of a fixed set of
	// Tailwind classes - rarityContinuousColor interpolates an actual color
	// from the word's real frequency (see its docstring, wordDisplay.ts),
	// so it has to be applied as an inline style rather than a class. Every
	// other mode returns '' here and relies on spanClass instead. isDarkMode()
	// is the one reactive read in this whole component that isn't a plain
	// `dark:` class - see its own docstring, theme.svelte.ts, for why an
	// inline-computed color needs to be told the mode directly instead of
	// reacting to a `dark` ancestor class the way every other span here does.
	function spanStyle(span: WordSpan): string {
		if (colorBy !== 'rarity') return '';
		return `background-color: ${rarityContinuousColor(span.freq_per_million, isDarkMode())}`;
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
     the analysis results table/word-list pages: the panel's own
     backdrop wrapper collapses to `display: contents` at `lg`, so its
     child joins this row as a sticky-positioned sibling instead of
     floating as a modal. -->
<div class="flex flex-col lg:flex-row gap-4">
<div class="flex-1 min-w-0 bg-white dark:bg-slate-900 rounded-lg shadow-sm p-4">
	<div class="flex items-center justify-between gap-3 mb-3 flex-wrap">
		<p class="text-xs font-medium text-gray-400 dark:text-slate-500 uppercase tracking-wide">Reading view</p>
		<label class="flex items-center gap-1.5 text-sm text-gray-700 dark:text-slate-300">
			Color by
			<select bind:value={colorBy} class="border border-gray-300 rounded px-2 py-1 text-sm bg-white dark:bg-slate-800 dark:border-slate-600 dark:text-slate-200">
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
		<p class="text-gray-500 dark:text-slate-400 text-sm">Loading...</p>
	{:else if error}
		<p class="text-red-600 dark:text-red-400 text-sm">{error}</p>
	{:else}
		<p class="text-xl leading-loose whitespace-pre-wrap break-words text-gray-900 dark:text-slate-100">
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
