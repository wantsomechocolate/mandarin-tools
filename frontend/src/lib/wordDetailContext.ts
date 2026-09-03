// Shared by WordDetailPanel.svelte and any page that opens it - the
// "viewing context" a panel instance is opened with, and the pure
// hierarchy-match rule that decides which Visibility/UserWord entries are
// editable from that context (see isEntryEditable below).
//
// 'analysis' context carries textId too, since an analysis belongs to a
// specific text - needed so a text-scoped entry can be judged editable
// from an analysis page (an analysis page IS viewing that text, even
// though it's not itself "the text page").
export type WordDetailContext =
	| { type: 'global' }
	| { type: 'text'; textId: number; textTitle: string | null }
	| { type: 'analysis'; textId: number; textTitle: string | null; analysisId: number; analysisTitle: string | null };

// The minimal shape isEntryEditable needs from an entry - both
// UserWordEntryDetail and VisibilityEntryDetail (schemas.py) satisfy this
// structurally, no adapter needed.
export interface ScopedEntry {
	scope: 'global' | 'text' | 'analysis';
	text_id: number | null;
	analysis_id: number | null;
}

// One small pure function, testable in isolation - the hierarchy match
// deciding whether `entry` can be edited from `context`:
//   - global entries are always editable, everywhere.
//   - a text-scoped entry is editable only when `context` has a textId
//     (true for both 'text' and 'analysis' context types, since an
//     analysis page is viewing a specific text) AND it's the SAME textId -
//     never editable from a different text's page, even via one of ITS
//     analyses.
//   - an analysis-scoped entry is editable ONLY from that exact analysis's
//     own page (context.type === 'analysis' with a matching analysisId) -
//     specifically NOT editable from its own text's text-level page, even
//     though the analysis belongs to that text.
// A 'global' context (no textId/analysisId at all) therefore never matches
// a text- or analysis-scoped entry - this falls out of the rule above with
// no special case, since `context.textId`/`context.analysisId` are simply
// absent to compare against.
export function isEntryEditable(entry: ScopedEntry, context: WordDetailContext): boolean {
	if (entry.scope === 'global') return true;
	if (entry.scope === 'text') {
		return (context.type === 'text' || context.type === 'analysis') && entry.text_id === context.textId;
	}
	// entry.scope === 'analysis'
	return context.type === 'analysis' && entry.analysis_id === context.analysisId;
}
