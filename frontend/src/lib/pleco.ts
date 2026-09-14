// Pure formatter for Pleco's flashcard-import text format - no fetch, no
// DOM, easy to unit-test in isolation (same spirit as the backend's
// synthetic-dictionary segmenter tests). ExportDialog.svelte is the only
// caller: it gathers the inputs (which words to export, the bulk
// GET /analyze/{id}/export-data payload, the account's ExportPreferences)
// and hands them to buildPlecoExport, then downloads the result verbatim.
//
// Format (verified against Pleco's own docs/forums, not guessed):
//   //{Category}/{Subcategory}
//   word<TAB>pinyin<TAB>definition
// `//Category/Subcategory` is Pleco's real nested-category syntax. A blank
// pinyin or definition field is fine - Pleco looks the word up in its own
// dictionaries when a field is left empty, so there's no fallback
// placeholder to invent for a word with nothing resolved. Only one tab
// between fields, ever (Pleco's importer is picky about that), which is
// also why any literal tab/newline inside a word's own data gets
// neutralized in sanitizeField below rather than passed through.

import { sourceCategory, rarityLabel, type SourceCategory } from './wordDisplay';
import { entryLabel } from './wordDetailContext';
import type { ExportPreferences } from './exportPreferences';

export interface ExportUserEntry {
	scope: 'global' | 'text' | 'analysis';
	text_id: number | null;
	text_title: string | null;
	analysis_id: number | null;
	analysis_created_at: string | null;
	pronunciation: string | null;
	meaning: string | null;
}

export interface ExportWordData {
	word: string;
	pinyin: string | null;
	freq_per_million: number | null;
	rarity_tier: string | null;
	hsk_meanings: string[];
	cedict_definitions: string[];
	user_entries: ExportUserEntry[];
}

// The minimal shape buildPlecoExport needs from a word "to export" - a
// WordResult (or filteredResults() entry) satisfies this structurally.
export interface ExportableWord {
	word: string;
	source: string;
}

const CATEGORY_LABELS: Record<SourceCategory, string> = {
	main: 'Main',
	extra: 'Extra',
	sequence: 'Sequences',
};

// Pleco's private-use "newline within a plain-text-import field" character
// (U+EAB1) - a literal "\n" doesn't survive a line-oriented //Category
// import (each line is one card), but this codepoint does, letting a
// multi-source definition read as genuinely multiple lines inside Pleco
// rather than one run-on sentence.
const PLECO_LINE_BREAK = '';

// Neutralizes characters that would corrupt the tab-separated, one-
// card-per-line format if they slipped through from a word/pinyin/
// definition's own data - a literal tab would misalign the 3 fields, and a
// literal newline would split one card's line into two. Doesn't touch
// PLECO_LINE_BREAK itself, which is the intentional replacement for the
// second case.
function sanitizeField(text: string): string {
	return text.replace(/\t/g, ' ').replace(/\r\n|\r|\n/g, PLECO_LINE_BREAK);
}

// Builds one word's definition field from whichever sources are both
// enabled in `prefs` and actually resolved something for this word -
// Corpus, then HSK, then CC-CEDICT, then each present UserWord scope
// (Global, Text, Analysis, in that order.) A single resolved source is left
// unprefixed; two or more get each source's own label (matching how
// WordDetailPanel's "Dictionary"/"Your entries" sections already read) so
// a user opening the card in Pleco can tell which source said what.
function definitionField(word: ExportWordData, prefs: ExportPreferences): string {
	const sources = prefs.definitionSources;
	const lines: { label: string; text: string }[] = [];

	if (sources.corpusFrequency && word.rarity_tier) {
		const freq = word.freq_per_million != null ? ` (${word.freq_per_million.toFixed(1)}/million)` : '';
		lines.push({ label: 'Corpus', text: `${rarityLabel(word.rarity_tier)}${freq}` });
	}
	if (sources.hsk && word.hsk_meanings.length > 0) {
		lines.push({ label: 'HSK', text: word.hsk_meanings.join('; ') });
	}
	if (sources.cedict && word.cedict_definitions.length > 0) {
		lines.push({ label: 'CC-CEDICT', text: word.cedict_definitions.join(' / ') });
	}
	for (const entry of word.user_entries) {
		if (!entry.meaning) continue;
		const enabled =
			(entry.scope === 'global' && sources.userGlobal) ||
			(entry.scope === 'text' && sources.userText) ||
			(entry.scope === 'analysis' && sources.userAnalysis);
		if (!enabled) continue;
		lines.push({ label: entryLabel(entry), text: entry.meaning });
	}

	if (lines.length === 0) return '';
	const rendered = lines.length === 1 ? [lines[0].text] : lines.map((l) => `${l.label}: ${l.text}`);
	return sanitizeField(rendered.join(PLECO_LINE_BREAK));
}

// `categoryTitle` is the text's title (already resolved by the caller -
// falls back to something sensible there, e.g. "Untitled text", since this
// function has no opinion on that). `wordsToExport` decides which words go
// in at all (the caller applies "respect current filter" or not before
// calling this) and which of the 3 subcategories each lands in, via
// sourceCategory - `exportData` supplies everything else, looked up by
// word. A word present in `wordsToExport` but missing from `exportData`
// (shouldn't happen - the backend returns every word in the analysis) just
// gets blank pinyin/definition fields, same as any other word with nothing
// resolved.
export function buildPlecoExport(
	categoryTitle: string,
	wordsToExport: ExportableWord[],
	exportData: ExportWordData[],
	prefs: ExportPreferences
): string {
	const dataByWord = new Map(exportData.map((w) => [w.word, w]));
	const byCategory: Record<SourceCategory, string[]> = { main: [], extra: [], sequence: [] };

	for (const w of wordsToExport) {
		const data = dataByWord.get(w.word);
		const pinyin = prefs.includePinyin ? sanitizeField(data?.pinyin ?? '') : '';
		const definition = prefs.includeDefinitions && data ? definitionField(data, prefs) : '';
		byCategory[sourceCategory(w.source)].push(`${sanitizeField(w.word)}\t${pinyin}\t${definition}`);
	}

	const sections: string[] = [];
	for (const category of ['main', 'extra', 'sequence'] as const) {
		const lines = byCategory[category];
		if (lines.length === 0) continue;
		sections.push(`//${categoryTitle}/${CATEGORY_LABELS[category]}`);
		sections.push(...lines);
	}
	return sections.join('\n');
}

// A safe-ish filename from the text's title - Windows/macOS/Linux all
// forbid at least this character set; collapsing to underscores rather
// than stripping keeps distinct titles that differ only in punctuation
// from colliding into the same filename.
export function sanitizeFilename(title: string | null | undefined): string {
	const base = (title ?? '').trim();
	if (!base) return 'export';
	return base.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 100);
}
