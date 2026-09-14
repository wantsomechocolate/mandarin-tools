// Shared types/helpers for every export-format formatter (pleco.ts,
// xlsxExport.ts, and whatever comes next - see ROADMAP.md's "Additional
// export formats" entry). Extracted here once a second formatter needed
// the exact same ExportWordData shape and per-source text rendering that
// pleco.ts originally kept to itself - same "extract once a second
// consumer appears" precedent this codebase already follows elsewhere
// (wordDisplay.ts, wordDetailContext.ts).
//
// Every multi-line builder below returns `string[] | null` (lines, never
// pre-joined) rather than a string, so each formatter joins with its own
// line-break convention (real `\n` for xlsx cells, Pleco's U+EAB1 for a
// single flashcard field - see pleco.ts) from the exact same content, and
// both formats stay identical in substance even though the columns/fields
// they land in differ.

import { rarityLabel } from './wordDisplay';

export interface ExportHskForm {
	traditional: string | null;
	pinyin: string | null;
	meanings: string[];
	classifiers: string[];
}

export interface ExportCedictSense {
	traditional: string | null;
	pinyin: string | null;
	definitions: string[];
}

export interface ExportUserEntry {
	scope: 'global' | 'text' | 'analysis';
	text_id: number | null;
	text_title: string | null;
	analysis_id: number | null;
	pronunciation: string | null;
	meaning: string | null;
	notes: string | null;
}

// One occurrence's context, split into its three pieces rather than one
// pre-joined string - specifically so a formatter can render `match`
// distinctly from `before`/`after` (the .xlsx export bolds it as a real
// rich-text run; Pleco's plain-text field just concatenates all three).
// Each piece already had internal whitespace collapsed to single spaces
// by the backend - see ExportContext's docstring, schemas.py.
export interface ExportContext {
	before: string;
	match: string;
	after: string;
}

export interface ExportWordData {
	word: string;
	pinyin: string | null;
	evidence_tier: 'user' | 'dictionary' | 'corpus' | 'unknown';
	dictionary_source: 'hsk' | 'cedict' | null;
	frequency: number | null;
	freq_per_million: number | null;
	rarity_tier: string | null;
	hsk_forms: ExportHskForm[];
	hsk_radical: string | null;
	hsk_v2_2012: number | null;
	hsk_v3_2021: number | null;
	hsk_v3_2026: number | null;
	hsk_frequency: number | null;
	hsk_pos: string[];
	cedict_senses: ExportCedictSense[];
	// UNBOUNDED - every UserWord entry this word has anywhere, across
	// every text/analysis, not just this export's own context. See
	// ExportUserEntry's backend docstring (schemas.py).
	user_entries: ExportUserEntry[];
	enrichment_pinyin: string | null;
	enrichment_translation: string | null;
	familiarity: number | null;
	sample_sentences: string[];
	contexts: ExportContext[];
	note: string | null;
}

// The minimal shape an export formatter needs from a word "to export" - a
// WordResult (or filteredResults() entry) satisfies this structurally.
// `count` is the one field neither formatter gets from ExportWordData
// (it's per-analysis occurrence count, already on the page's own
// AnalysisResult-backed rows, not worth a second round trip for).
export interface ExportableWord {
	word: string;
	source: string;
	count?: number;
}

// "Segmentation Source" - the evidence-tier hierarchy (user > dictionary >
// corpus > unknown), with the dictionary tier split by which curated
// source backs it (HSK wins when both, same priority
// AnalysisSpan.dictionary_source uses). Deliberately its own literal
// casing ("Your Word", not evidenceTierLabel's "Your word") - this export
// has its own template to match, not the app's own UI label scale.
export function segmentationSourceText(word: ExportWordData): string {
	if (word.evidence_tier === 'user') return 'Your Word';
	if (word.evidence_tier === 'dictionary') {
		return word.dictionary_source === 'cedict' ? 'Dictionary (CC-CEDICT)' : 'Dictionary (HSK)';
	}
	if (word.evidence_tier === 'corpus') return 'Corpus';
	return 'None';
}

// Corpus: rarity label, raw frequency, freq-per-million - in that order
// (matching the template, not the order those three are read out
// elsewhere in the app). Omitted entirely (null) when the word has no
// corpus presence at all - same "omit if absent" convention this app uses
// for optional reference data everywhere else (HSK badges, rarity badge,
// etc).
export function corpusLines(word: ExportWordData): string[] | null {
	if (!word.rarity_tier && word.frequency == null) return null;
	return [
		rarityLabel(word.rarity_tier),
		word.frequency != null ? String(word.frequency) : '',
		word.freq_per_million != null ? `${word.freq_per_million.toFixed(1)} per million` : '',
	];
}

// HSK: every form (traditional/pinyin/meanings/classifiers), blank line
// between forms, then - after all forms - the entry-level fields (radical/
// level-per-edition/HSK frequency rank/POS). Omitted entirely when there's
// no HSK entry for this word at all (the common case - HSK covers a small
// fraction of real vocabulary), unlike Auto-Generated below, which always
// shows its labels even when blank: an HSK skeleton with everything empty
// would just be clutter for the ~90% of words with no HSK backing, while
// Auto-Generated's blank state is itself actionable information ("nothing
// generated for this word yet").
export function hskLines(word: ExportWordData): string[] | null {
	const hasEntry =
		word.hsk_forms.length > 0 ||
		!!word.hsk_radical ||
		word.hsk_frequency != null ||
		word.hsk_pos.length > 0 ||
		word.hsk_v2_2012 != null ||
		word.hsk_v3_2021 != null ||
		word.hsk_v3_2026 != null;
	if (!hasEntry) return null;

	const lines: string[] = [];
	word.hsk_forms.forEach((form, i) => {
		if (i > 0) lines.push('');
		lines.push(`Form ${i + 1}`);
		lines.push(`traditional: ${form.traditional ?? ''}`);
		lines.push(`pinyin: ${form.pinyin ?? ''}`);
		lines.push('meanings:');
		lines.push(...form.meanings);
		lines.push(`classifiers: ${form.classifiers.join(', ')}`);
	});

	if (word.hsk_forms.length > 0) lines.push('');
	lines.push(`Radical: ${word.hsk_radical ?? ''}`);
	// "N/A" for a missing level, not "-" - the line already uses "-" as the
	// separator between the three editions, so a bare "-" for a missing
	// value would be ambiguous ("2021: -" reads as a value, not "none").
	lines.push(`Level: 2012: ${word.hsk_v2_2012 ?? 'N/A'} - 2021: ${word.hsk_v3_2021 ?? 'N/A'} - 2026: ${word.hsk_v3_2026 ?? 'N/A'}`);
	lines.push(`HSK Frequency Rank: ${word.hsk_frequency ?? ''}`);
	lines.push(`POS: ${word.hsk_pos.join(', ')}`);
	return lines;
}

// CC-CEDICT: every sense (traditional/pinyin/meanings), blank line between
// senses - no classifiers line (CedictEntry has no separate classifiers
// field; a "CL:..." note, when present, is already embedded in the
// definitions themselves). Omitted when there are no senses at all.
export function cedictLines(word: ExportWordData): string[] | null {
	if (word.cedict_senses.length === 0) return null;
	const lines: string[] = [];
	word.cedict_senses.forEach((sense, i) => {
		if (i > 0) lines.push('');
		lines.push(`Sense ${i + 1}`);
		lines.push(`traditional: ${sense.traditional ?? ''}`);
		lines.push(`pinyin: ${sense.pinyin ?? ''}`);
		lines.push('meanings:');
		lines.push(...sense.definitions);
	});
	return lines;
}

// "Global" / "Text: {title}" / "Analysis: {title}-{analysis_id}" - a new
// label format for this export specifically, deliberately separate from
// wordDetailContext.ts's entryLabel (which keeps its own, different
// wording for its existing UI callers - the word-detail panel, Pleco's
// pre-existing per-scope lines).
export function exportUserEntryLabel(entry: ExportUserEntry): string {
	if (entry.scope === 'global') return 'Global';
	if (entry.scope === 'text') return `Text: ${entry.text_title ?? 'Untitled text'}`;
	return `Analysis: ${entry.text_title ?? 'Untitled text'}-${entry.analysis_id ?? ''}`;
}

// Filters an unbounded user_entries list down to the scopes the account's
// export preferences actually want shown - shared by both formatters so
// "which scopes count" can't drift between them.
export function filterUserEntries(
	entries: ExportUserEntry[],
	sources: { userGlobal: boolean; userText: boolean; userAnalysis: boolean }
): ExportUserEntry[] {
	return entries.filter(
		(e) =>
			(e.scope === 'global' && sources.userGlobal) ||
			(e.scope === 'text' && sources.userText) ||
			(e.scope === 'analysis' && sources.userAnalysis)
	);
}

// The full verbose per-entry block (label, then pinyin/meanings/note),
// blank line between entries - takes an already-filtered entry list (the
// caller applies the userGlobal/userText/userAnalysis toggles first) so
// this function has no preference-reading of its own. Omitted when the
// filtered list is empty.
export function userEntryLines(entries: ExportUserEntry[]): string[] | null {
	if (entries.length === 0) return null;
	const lines: string[] = [];
	entries.forEach((entry, i) => {
		if (i > 0) lines.push('');
		lines.push(exportUserEntryLabel(entry));
		lines.push(`pinyin: ${entry.pronunciation ?? ''}`);
		lines.push('meanings:');
		if (entry.meaning) lines.push(entry.meaning);
		lines.push(`note: ${entry.notes ?? ''}`);
	});
	return lines;
}

// Auto-Generated: both labels, blank for whichever piece is missing -
// omitted entirely (both null) when literally nothing's been generated
// for this word, same "omit if absent" convention as HSK/CC-CEDICT/User.
export function autoGeneratedLines(word: ExportWordData): string[] | null {
	if (!word.enrichment_pinyin && !word.enrichment_translation) return null;
	return [`pinyin: ${word.enrichment_pinyin ?? ''}`, `meanings: ${word.enrichment_translation ?? ''}`];
}

// Plain "before+match+after" concatenation - Pleco's own plain-text field
// has no rich-text runs to bold `match` with, so it just needs the flat
// string back; xlsxExport.ts renders the 3 pieces as separate runs instead
// (see its own buildContextRichText).
export function contextToPlainText(context: ExportContext): string {
	return context.before + context.match + context.after;
}

// A safe-ish filename from the text's title - Windows/macOS/Linux all
// forbid at least this character set; collapsing to underscores rather
// than stripping keeps distinct titles that differ only in punctuation
// from colliding into the same filename. Shared across formats - only the
// extension differs per format, appended by the caller.
export function sanitizeFilename(title: string | null | undefined): string {
	const base = (title ?? '').trim();
	if (!base) return 'export';
	return base.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 100);
}
