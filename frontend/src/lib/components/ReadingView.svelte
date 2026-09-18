<script lang="ts">
	import { browser } from '$app/environment';
	import * as api from '$lib/api';
	import { sourceDetailColor, rarityContinuousColor, familiarityColor } from '$lib/wordDisplay';
	import type { SourceDetailTier } from '$lib/wordDisplay';
	import WordDetailModal from './WordDetailModal.svelte';
	import type { WordDetailContext } from '$lib/wordDetailContext';
	import { saveOpenWordPanel, loadOpenWordPanel } from '$lib/panelWordPersistence';
	import { trackReadingViewScroll, restoreReadingViewScroll } from '$lib/readingViewPersistence';
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
		evidence_tier: 'user' | 'dictionary' | 'corpus' | 'repeated_sequence' | 'unknown' | null;
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

	// 'blank' is the true "no markings at all" mode (plain characters, still
	// clickable, nothing else) - the display label "None" moved here from
	// what's still internally called 'none', which keeps its old id for
	// localStorage backward-compatibility but is now labeled "Segmentation"
	// (it was never actually blank - it always drew the word-boundary
	// underline; the id just predates 'blank' existing to contrast against).
	type ColorBy = 'blank' | 'none' | 'source' | 'rarity' | 'familiarity';

	// Persisted globally (one shared preference across every text/analysis,
	// not scoped per-page like scrollPersistence.ts/panelWordPersistence.ts
	// below) - unlike which word's panel was open or where the page was
	// scrolled to, "I like reading with rarity highlighted" is a genuine
	// standing preference, not per-visit recovery state, so this is
	// localStorage (survives closing the tab) rather than sessionStorage,
	// same reasoning as this app's other *_STORAGE_KEY filter preferences.
	// Reading view itself is deliberately NOT reopened by panelWordPersistence
	// or anything else after a reload (readingViewOn, analyze/[id]/+page.svelte,
	// stays a plain, unpersisted $state) - only the mode a user picks the
	// next time they do open it is remembered.
	const COLOR_BY_STORAGE_KEY = 'mandarin_tools_reading_view_color_by';
	function loadStoredColorBy(): ColorBy {
		if (!browser) return 'none';
		try {
			const raw = localStorage.getItem(COLOR_BY_STORAGE_KEY);
			return raw === 'blank' || raw === 'source' || raw === 'rarity' || raw === 'familiarity' ? raw : 'none';
		} catch {
			return 'none';
		}
	}
	let colorBy: ColorBy = $state(loadStoredColorBy());
	$effect(() => {
		if (!browser) return;
		try {
			localStorage.setItem(COLOR_BY_STORAGE_KEY, colorBy);
		} catch {
			// e.g. storage disabled/full - the preference just won't persist
		}
	});

	// Text annotations - user-highlighted word-aligned ranges with an
	// optional note/translation/pronunciation (TextAnnotation, backend).
	let annotations: api.TextAnnotation[] = $state([]);

	// "Show annotations" - same inline localStorage pattern as colorBy above,
	// own storage key, default OFF: this view was already dense before
	// annotations existed, so highlighting stays opt-in even though creating
	// one is easy.
	const SHOW_ANNOTATIONS_STORAGE_KEY = 'mandarin_tools_reading_view_show_annotations';
	function loadShowAnnotations(): boolean {
		if (!browser) return false;
		try {
			return localStorage.getItem(SHOW_ANNOTATIONS_STORAGE_KEY) === '1';
		} catch {
			return false;
		}
	}
	let showAnnotations: boolean = $state(loadShowAnnotations());
	$effect(() => {
		if (!browser) return;
		try {
			localStorage.setItem(SHOW_ANNOTATIONS_STORAGE_KEY, showAnnotations ? '1' : '0');
		} catch {
			// e.g. storage disabled/full - the preference just won't persist
		}
	});

	// "Annotate" mode - an editing mode, not a viewing preference, so unlike
	// showAnnotations above this is a plain unpersisted $state (default off).
	let annotateMode: boolean = $state(false);

	// Tap-select pending range - indices into `spans` (word spans only), not
	// character offsets. Both null means no in-progress selection.
	let pendingStartIdx: number | null = $state(null);
	let pendingEndIdx: number | null = $state(null);

	// Which annotation's popover is open - an existing annotation's id, the
	// string 'pending' for the in-progress create popover, or null (closed).
	let annotationPopoverFor: number | 'pending' | null = $state(null);
	let annotationNoteDraft = $state('');
	let annotationTranslationDraft = $state('');
	let annotationPronunciationDraft = $state('');
	let savingAnnotation = $state(false);
	let annotationError = $state('');
	// Whether the open popover shows editable inputs or a read-only summary.
	// A brand-new (pending) annotation has nothing to show read-only, so it's
	// always editable; an existing annotation opens read-only first (the
	// "eye" click is a view action) and only becomes editable via its own
	// Edit button - see openAnnotationPopover/cancelEditing.
	let annotationEditing = $state(false);
	let generatingEnrichment = $state(false);

	// Leaving Annotate mode abandons any in-progress selection/popover.
	$effect(() => {
		if (!annotateMode) {
			pendingStartIdx = null;
			pendingEndIdx = null;
			if (annotationPopoverFor === 'pending') annotationPopoverFor = null;
		}
	});

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

	// Which `spans` index opened the panel - unlike every other word-list
	// page's swipe (findNeighborWord, wordListSwipe.ts), a plain "find this
	// word's row" lookup doesn't work here: the same word can occur many
	// times in a passage, and swiping is about walking reading order
	// (occurrence by occurrence), not jumping to that word's first
	// occurrence every time. Null whenever the panel was opened some other
	// way than a span click - see swipeToWord's own fallback for that case.
	let selectedSpanIndex: number | null = $state(null);

	// Mobile swipe-to-navigate (WordDetailModal's onSwipeNext/onSwipePrevious)
	// - walks `spans` by index from selectedSpanIndex, skipping gap spans,
	// same dead-end-at-either-end behavior as every other swipeToWord in
	// this app (no wraparound). Falls back to this word's first occurrence
	// in `spans` when selectedSpanIndex is null - the panel-reopened-after-
	// reload case (panelWordPersistence.ts only ever restores the word
	// string, not which occurrence was open) - a reasonable starting point
	// rather than refusing to swipe at all.
	function swipeToWord(direction: 'next' | 'prev') {
		if (!selectedWordForPanel) return;
		const start = selectedSpanIndex ?? spans.findIndex((s) => s.type === 'word' && s.word === selectedWordForPanel);
		if (start === -1) return;
		const step = direction === 'next' ? 1 : -1;
		for (let i = start + step; i >= 0 && i < spans.length; i += step) {
			const span = spans[i];
			if (span.type === 'word') {
				selectedWordForPanel = span.word;
				selectedSpanIndex = i;
				return;
			}
		}
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const data = await api.getAnalysisSpans(analysisId) as { input_text_id: number; spans: Span[] };
			spans = data.spans;
			textId = data.input_text_id;
			annotations = await api.listTextAnnotations(textId);
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

	// Scroll position, alongside analyze/[id]/+page.svelte's own
	// readingViewOn (readingViewPersistence.ts covers both) - "leave the
	// app and come back to right where I was reading" needs both remembered
	// together, or reopening reading view automatically just lands you back
	// at the top. Tracking starts immediately; restoring waits for
	// `loading` to flip false, since scrolling to a saved position makes no
	// sense before the spans this analysis's height depends on have
	// arrived. scrollRestoredForId (not a plain boolean) so switching this
	// same mounted instance to a different analysisId - see the load()
	// effect above - restores that analysis's own saved position too,
	// rather than being skipped as "already restored" from the last one.
	$effect(() => trackReadingViewScroll(analysisId));
	let scrollRestoredForId: number | null = null;
	$effect(() => {
		if (loading || scrollRestoredForId === analysisId) return;
		scrollRestoredForId = analysisId;
		restoreReadingViewScroll(analysisId);
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
		repeated_sequence: 'dark:bg-purple-400/30',
		none: 'dark:bg-slate-500/15',
	};
	const FAMILIARITY_TINT_DARK: Record<number, string> = {
		1: 'dark:bg-red-400/30',
		2: 'dark:bg-orange-400/30',
		3: 'dark:bg-yellow-400/30',
		// 4/5 deliberately don't follow the "full hue step brighter, roughly
		// double the opacity" rule above - a word you already know well or
		// have mastered is the one thing reading through a passage shouldn't
		// keep drawing the eye back to, the opposite of what every other
		// tint on this scale is for. Faded down instead, the same direction
		// rarityContinuousColor fades its own "as common as it gets" end
		// toward no visible tint at all - see FAMILIARITY_FILL_LIGHT below
		// for the light-mode half of this same change.
		4: 'dark:bg-green-500/10',
		5: '',
	};
	// Light-mode counterpart to the 4/5 fade above - familiarityColor's own
	// bg-green-100/bg-emerald-100 (what bgOnly(familiarityColor(...)) would
	// otherwise return) read as too prominent for "already know this" at
	// reading-view's full-word-fill size, the same complaint that motivated
	// FAMILIARITY_TINT_DARK's own bolder-than-familiarityColor departure in
	// the first place, just in the opposite direction. 5 goes fully
	// uncolored (mirrors rarityContinuousColor's own most-common stop, which
	// is literal white, not a pale green) rather than a paler version of its
	// own hue - "as known as it gets" reads as neutral, not as a color.
	const FAMILIARITY_FILL_LIGHT: Record<number, string> = {
		4: 'bg-green-50',
		5: '',
	};

	// User > HSK > CC-CEDICT > Corpus > Repeated sequence > None - see
	// AnalysisSpan.dictionary_source's docstring (schemas.py) for the same
	// order and the HSK-over-CC-CEDICT tie-break. Falls back to
	// evidence_tier's own "corpus"/"repeated_sequence"/"unknown" for the
	// cases dictionary_source doesn't cover (it's only ever "hsk"/"cedict"/
	// null).
	function sourceDetailTier(span: WordSpan): SourceDetailTier {
		if (span.userword_scopes.length > 0) return 'user';
		if (span.dictionary_source) return span.dictionary_source;
		if (span.evidence_tier === 'corpus') return 'corpus';
		if (span.evidence_tier === 'repeated_sequence') return 'repeated_sequence';
		return 'none';
	}

	function spanClass(span: WordSpan): string {
		// True "no markings" mode - plain characters, still clickable, no
		// boundary/color of any kind. See ColorBy's own docstring above for
		// why this is a separate id from 'none' rather than a renamed one.
		// The base `rounded px-0.5` every button otherwise gets (spanInner,
		// below) is also stripped for this mode specifically - that padding
		// is what gives a color fill some breathing room and gives the
		// Segmentation underline mode's word-to-word gaps their visibility,
		// but with no fill/border to pad here it was just injecting a small,
		// unwanted gap between words that plain text doesn't have.
		if (colorBy === 'blank') return '';
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
			// 4/5 fade toward uncolored instead of familiarityColor's own
			// bg-green-100/bg-emerald-100 - see FAMILIARITY_FILL_LIGHT's own
			// docstring above.
			const fill = span.familiarity && span.familiarity >= 4
				? FAMILIARITY_FILL_LIGHT[span.familiarity]
				: bgOnly(familiarityColor(span.familiarity));
			return fill + ' ' + tint;
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

	// Word-button click - either opens the word panel (Annotate mode off,
	// today's existing behavior) or drives tap-select range picking (on).
	// First click sets pendingStartIdx (clearing any prior completed pair and
	// discarding a stale 'pending' popover); a second click on a different
	// word sets pendingEndIdx, normalized to min/max so click order doesn't
	// matter, and opens the create popover; a further click restarts the
	// selection from that word.
	function handleWordClick(span: WordSpan, idx: number) {
		if (!annotateMode) {
			selectedWordForPanel = span.word;
			selectedSpanIndex = idx;
			return;
		}
		if (pendingStartIdx === null || pendingEndIdx !== null) {
			pendingStartIdx = idx;
			pendingEndIdx = null;
			if (annotationPopoverFor === 'pending') annotationPopoverFor = null;
			return;
		}
		if (idx === pendingStartIdx) return;
		pendingEndIdx = idx;
		if (pendingStartIdx > pendingEndIdx) {
			[pendingStartIdx, pendingEndIdx] = [pendingEndIdx, pendingStartIdx];
		}
		openAnnotationPopover('pending');
	}

	// Svelte requires balanced HTML within any {#each}/{#if} block, so a
	// wrapping <span> can't be opened on one loop iteration and closed on a
	// later one inside a single flat {#each spans as span} - grouping spans
	// into contiguous runs up front is what makes wrapping a multi-word range
	// possible at all. See RenderGroup's own use in the template below.
	type RenderGroup =
		| { kind: 'plain'; span: Span; idx: number }
		| { kind: 'selecting'; span: Span; idx: number }
		| { kind: 'annotated'; annotationId: number | 'pending'; items: { span: Span; idx: number }[] };

	// Membership uses range overlap, not exact boundary match, for both the
	// pending selection and confirmed annotations - a later re-analysis of
	// the same InputText can re-segment differently than whatever analysis's
	// word occurrences were used to pick the range originally (annotations
	// anchor to InputText, not Analysis - see TextAnnotation's docstring,
	// models.py), so exact alignment to a span boundary isn't guaranteed to
	// survive. Applied uniformly to word and gap spans alike - a punctuation
	// gap inside a selected/annotated range must still join the group, or
	// the highlight visibly breaks across it.
	//
	// 'selecting' is the tap-select start word before a second click - purely
	// a visual acknowledgement that the first click registered, distinct from
	// 'pending' (both endpoints chosen, ready to save): no marker/popover is
	// attached to it, since there's nothing to save yet.
	function ownerFor(span: Span): number | 'pending' | 'selecting' | null {
		if (pendingStartIdx !== null) {
			const startSpan = spans[pendingStartIdx];
			if (pendingEndIdx !== null) {
				const endSpan = spans[pendingEndIdx];
				if (startSpan && endSpan && span.start < endSpan.end && span.end > startSpan.start) {
					return 'pending';
				}
			} else if (startSpan && span.start < startSpan.end && span.end > startSpan.start) {
				return 'selecting';
			}
		}
		if (!showAnnotations) return null;
		for (const a of annotations) {
			if (span.start < a.end_offset && span.end > a.start_offset) return a.id;
		}
		return null;
	}

	const renderGroups: RenderGroup[] = $derived.by(() => {
		if (!showAnnotations && pendingStartIdx === null) {
			return spans.map((span, idx) => ({ kind: 'plain', span, idx }) as RenderGroup);
		}

		const groups: RenderGroup[] = [];
		let currentOwner: number | 'pending' | 'selecting' | null = null;
		let currentItems: { span: Span; idx: number }[] = [];

		function flush() {
			if (currentItems.length === 0) return;
			if (currentOwner === null) {
				for (const item of currentItems) groups.push({ kind: 'plain', span: item.span, idx: item.idx });
			} else if (currentOwner === 'selecting') {
				for (const item of currentItems) groups.push({ kind: 'selecting', span: item.span, idx: item.idx });
			} else {
				groups.push({ kind: 'annotated', annotationId: currentOwner, items: currentItems });
			}
			currentItems = [];
		}

		for (let idx = 0; idx < spans.length; idx++) {
			const span = spans[idx];
			const owner = ownerFor(span);
			if (owner !== currentOwner) {
				flush();
				currentOwner = owner;
			}
			currentItems.push({ span, idx });
		}
		flush();

		return groups;
	});

	function openAnnotationPopover(id: number | 'pending') {
		if (annotationPopoverFor === id) {
			annotationPopoverFor = null;
			return;
		}
		annotationError = '';
		if (id === 'pending') {
			annotationNoteDraft = '';
			annotationTranslationDraft = '';
			annotationPronunciationDraft = '';
			annotationEditing = true;
		} else {
			const existing = annotations.find((a) => a.id === id);
			annotationNoteDraft = existing?.note ?? '';
			annotationTranslationDraft = existing?.translation ?? '';
			annotationPronunciationDraft = existing?.pronunciation ?? '';
			// The "eye"/marker click is a view action - editing an existing
			// annotation needs an explicit Edit click (see cancelEditing for
			// the reverse: Cancel while editing drops back to this view
			// rather than closing the popover outright).
			annotationEditing = false;
		}
		annotationPopoverFor = id;
	}

	function cancelAnnotationPopover() {
		if (annotationPopoverFor === 'pending') {
			pendingStartIdx = null;
			pendingEndIdx = null;
		}
		annotationPopoverFor = null;
	}

	// Cancel from inside the edit form - a brand-new (pending) annotation has
	// nothing to go "back" to, so this abandons the whole selection like
	// cancelAnnotationPopover; an existing annotation instead discards the
	// in-progress edits and returns to its read-only view.
	function cancelEditing() {
		if (annotationPopoverFor === 'pending' || annotationPopoverFor === null) {
			cancelAnnotationPopover();
			return;
		}
		const existing = annotations.find((a) => a.id === annotationPopoverFor);
		annotationNoteDraft = existing?.note ?? '';
		annotationTranslationDraft = existing?.translation ?? '';
		annotationPronunciationDraft = existing?.pronunciation ?? '';
		annotationEditing = false;
	}

	// Reading order text for the in-progress tap-select range, used as the
	// auto-generate source before an annotation has been saved (a confirmed
	// annotation already has this captured server-side as highlighted_text).
	function pendingRangeText(): string {
		if (pendingStartIdx === null || pendingEndIdx === null) return '';
		return spans
			.slice(pendingStartIdx, pendingEndIdx + 1)
			.map((s) => (s.type === 'word' ? s.word : s.text))
			.join('');
	}

	async function generateEnrichment() {
		const text = annotationPopoverFor === 'pending'
			? pendingRangeText()
			: annotations.find((a) => a.id === annotationPopoverFor)?.highlighted_text ?? '';
		if (!text) return;
		generatingEnrichment = true;
		annotationError = '';
		try {
			const result = await api.generateAnnotationEnrichment(text);
			annotationTranslationDraft = result.translation;
			annotationPronunciationDraft = result.pinyin;
		} catch (e: unknown) {
			annotationError = e instanceof Error ? e.message : 'Failed to auto-generate';
		} finally {
			generatingEnrichment = false;
		}
	}

	async function saveAnnotation() {
		if (annotationPopoverFor === null || textId === null) return;
		savingAnnotation = true;
		annotationError = '';
		try {
			if (annotationPopoverFor === 'pending') {
				if (pendingStartIdx === null || pendingEndIdx === null) return;
				const startSpan = spans[pendingStartIdx];
				const endSpan = spans[pendingEndIdx];
				const created = await api.createTextAnnotation(textId, {
					start_offset: startSpan.start,
					end_offset: endSpan.end,
					note: annotationNoteDraft.trim() || null,
					translation: annotationTranslationDraft.trim() || null,
					pronunciation: annotationPronunciationDraft.trim() || null,
				});
				annotations = [...annotations, created].sort((a, b) => a.start_offset - b.start_offset);
				pendingStartIdx = null;
				pendingEndIdx = null;
			} else {
				const updated = await api.updateTextAnnotation(annotationPopoverFor, {
					note: annotationNoteDraft.trim() || null,
					translation: annotationTranslationDraft.trim() || null,
					pronunciation: annotationPronunciationDraft.trim() || null,
				});
				annotations = annotations.map((a) => (a.id === updated.id ? updated : a));
			}
			annotationPopoverFor = null;
		} catch (e: unknown) {
			annotationError = e instanceof Error ? e.message : 'Failed to save annotation';
		} finally {
			savingAnnotation = false;
		}
	}

	async function deleteAnnotationFromPopover() {
		if (typeof annotationPopoverFor !== 'number') return;
		savingAnnotation = true;
		annotationError = '';
		try {
			await api.deleteTextAnnotation(annotationPopoverFor);
			annotations = annotations.filter((a) => a.id !== annotationPopoverFor);
			annotationPopoverFor = null;
		} catch (e: unknown) {
			annotationError = e instanceof Error ? e.message : 'Failed to delete annotation';
		} finally {
			savingAnnotation = false;
		}
	}
</script>

{#snippet spanInner(span: Span, idx: number)}
	{#if span.type === 'gap'}<span>{span.text}</span
	>{:else}<button
			onclick={() => handleWordClick(span, idx)}
			class="hover:ring-1 hover:ring-blue-400 {colorBy === 'blank' ? '' : 'rounded px-0.5'} {spanClass(span)}"
			style={spanStyle(span)}
			title={spanTitle(span)}
		>{span.word}</button
		>{/if}
{/snippet}

{#snippet annotationMarkerIcon(isPending: boolean)}
	{#if isPending}
		<svg class="w-3 h-3 inline" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M10 4v12M4 10h12" /></svg>
	{:else}
		<svg class="w-3 h-3 inline" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10s2.5-5 6-5 6 5 6 5-2.5 5-6 5-6-5-6-5z" /><circle cx="10" cy="10" r="1.6" /></svg>
	{/if}
{/snippet}

<!-- Shared form body for the annotation popover. A brand-new (id === 'pending')
     annotation is always shown in edit mode (nothing to view read-only
     yet); an existing annotation opens read-only (annotationEditing false -
     see openAnnotationPopover) and only shows the edit form once its own
     Edit button is clicked. Field order (Translation, Pronunciation, Note)
     matches both modes. -->
{#snippet annotationFormBody(id: number | 'pending')}
	<div class="flex flex-col gap-2 p-3" onclick={(e) => e.stopPropagation()} role="presentation">
		{#if annotationError}<p class="text-xs text-red-600 dark:text-red-400">{annotationError}</p>{/if}
		{#if annotationEditing}
			<input bind:value={annotationTranslationDraft} placeholder="Translation" class="border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm" />
			<input bind:value={annotationPronunciationDraft} placeholder="Pronunciation" class="border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm" />
			<input bind:value={annotationNoteDraft} placeholder="Note" class="border border-gray-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 rounded px-2 py-1 text-sm" />
			<button
				onclick={generateEnrichment}
				disabled={generatingEnrichment}
				class="self-start text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
			>
				{generatingEnrichment ? 'Generating...' : 'Auto-generate translation/pronunciation'}
			</button>
			<div class="flex items-center gap-2 mt-1">
				<button onclick={saveAnnotation} disabled={savingAnnotation} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600 disabled:opacity-50">
					{savingAnnotation ? 'Saving...' : 'Save'}
				</button>
				<button onclick={cancelEditing} disabled={savingAnnotation} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Cancel</button>
				{#if typeof id === 'number'}
					<button onclick={deleteAnnotationFromPopover} disabled={savingAnnotation} class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 ml-auto">Delete</button>
				{/if}
			</div>
		{:else}
			{#if annotationTranslationDraft}
				<p class="text-sm text-gray-800 dark:text-slate-200"><span class="text-xs text-gray-400 dark:text-slate-500">Translation</span><br />{annotationTranslationDraft}</p>
			{/if}
			{#if annotationPronunciationDraft}
				<p class="text-sm text-gray-800 dark:text-slate-200"><span class="text-xs text-gray-400 dark:text-slate-500">Pronunciation</span><br />{annotationPronunciationDraft}</p>
			{/if}
			{#if annotationNoteDraft}
				<p class="text-sm text-gray-800 dark:text-slate-200"><span class="text-xs text-gray-400 dark:text-slate-500">Note</span><br />{annotationNoteDraft}</p>
			{/if}
			{#if !annotationTranslationDraft && !annotationPronunciationDraft && !annotationNoteDraft}
				<p class="text-sm text-gray-400 dark:text-slate-500">No details yet.</p>
			{/if}
			<div class="flex items-center gap-2 mt-1">
				<button onclick={() => annotationEditing = true} class="text-xs px-3 py-1.5 bg-blue-600 dark:bg-blue-500 text-white rounded hover:bg-blue-700 dark:hover:bg-blue-600">Edit</button>
				<button onclick={cancelAnnotationPopover} class="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300">Close</button>
				<button onclick={deleteAnnotationFromPopover} disabled={savingAnnotation} class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-400 ml-auto">Delete</button>
			</div>
		{/if}
	</div>
{/snippet}

<!-- Dual dropdown (>=700px) / bottom-sheet (<700px) popover, same pattern as
     analyze/[id]/+page.svelte's visibilityAction: stopPropagation at every
     layer so a click doesn't bubble into a row/word's own onclick, backdrop
     click closes without saving. -->
{#snippet annotationPopover(id: number | 'pending')}
	<div class="hidden min-[700px]:block fixed inset-0 z-40" onclick={(e) => { e.stopPropagation(); cancelAnnotationPopover(); }} role="presentation"></div>
	<div class="hidden min-[700px]:block absolute left-0 top-full mt-1 z-50 w-64 bg-white dark:bg-slate-900 rounded-lg shadow-lg border border-gray-100 dark:border-slate-800" onclick={(e) => e.stopPropagation()} role="presentation">
		{@render annotationFormBody(id)}
	</div>

	<div class="min-[700px]:hidden fixed inset-0 z-40 bg-black/30" onclick={(e) => { e.stopPropagation(); cancelAnnotationPopover(); }} role="presentation"></div>
	<div class="min-[700px]:hidden fixed inset-x-0 bottom-0 z-50 bg-white dark:bg-slate-900 rounded-t-2xl shadow-sm max-h-[70vh] overflow-y-auto" onclick={(e) => e.stopPropagation()} role="presentation">
		{@render annotationFormBody(id)}
	</div>
{/snippet}

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
				<option value="blank">None</option>
				<option value="none">Segmentation</option>
				<!-- Colors by sourceDetailTier() - User > HSK > CC-CEDICT > Corpus >
				     None, a finer split of evidenceTierColor's own 4-tier scale
				     (see sourceDetailColor's docstring, wordDisplay.ts). -->
				<option value="source">Source</option>
				<option value="rarity">Rarity</option>
				<option value="familiarity">Familiarity</option>
			</select>
		</label>
		<label class="flex items-center gap-1.5 text-sm text-gray-700 dark:text-slate-300">
			<input type="checkbox" bind:checked={showAnnotations} />
			Show annotations
		</label>
		<button
			onclick={() => annotateMode = !annotateMode}
			aria-pressed={annotateMode}
			class="text-sm px-2.5 py-1 rounded border {annotateMode ? 'bg-blue-100 dark:bg-blue-500/15 border-blue-300 dark:border-blue-500/40 text-blue-700 dark:text-blue-400' : 'bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800'}"
		>
			Annotate
		</button>
	</div>

	{#if loading}
		<p class="text-gray-500 dark:text-slate-400 text-sm">Loading...</p>
	{:else if error}
		<p class="text-red-600 dark:text-red-400 text-sm">{error}</p>
	{:else}
		<p class="text-xl leading-loose whitespace-pre-wrap break-words text-gray-900 dark:text-slate-100">
			{#each renderGroups as group}
				{#if group.kind === 'plain'}{@render spanInner(group.span, group.idx)}
				{:else if group.kind === 'selecting'}<span class="rounded bg-blue-100 dark:bg-blue-500/20 ring-1 ring-blue-400"
					>{@render spanInner(group.span, group.idx)}</span
					>{:else}<span class="relative {group.annotationId === 'pending' ? 'bg-blue-100 dark:bg-blue-500/20' : 'border-b-2 border-dashed border-amber-500 dark:border-amber-400'}"
					>{#each group.items as item}{@render spanInner(item.span, item.idx)}{/each}<button
						onclick={(e) => { e.stopPropagation(); openAnnotationPopover(group.annotationId); }}
						class="align-super text-[10px] px-0.5 {group.annotationId === 'pending' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'}"
						title={group.annotationId === 'pending' ? 'Save annotation' : 'View annotation'}
					>{@render annotationMarkerIcon(group.annotationId === 'pending')}</button
					>{#if annotationPopoverFor === group.annotationId}{@render annotationPopover(group.annotationId)}{/if}</span
					>{/if}
			{/each}
		</p>
	{/if}
</div>

	<WordDetailModal
		word={selectedWordForPanel}
		context={panelContext}
		onClose={() => { selectedWordForPanel = null; selectedSpanIndex = null; }}
		onFamiliarityChanged={(familiarity) => {
			const word = selectedWordForPanel;
			if (!word) return;
			spans = spans.map((s) => s.type === 'word' && s.word === word ? { ...s, familiarity } : s);
		}}
		onSwipeNext={() => swipeToWord('next')}
		onSwipePrevious={() => swipeToWord('prev')}
	/>
</div>
